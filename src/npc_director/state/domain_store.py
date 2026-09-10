from __future__ import annotations

import asyncio
import hashlib
import sqlite3
from collections.abc import Collection
from dataclasses import dataclass
from datetime import datetime
from fnmatch import fnmatchcase
from functools import partial
from pathlib import Path

from npc_director.contracts import (
    EngineEvent,
    EngineEventType,
    NPCDomainState,
    StateChangeProposal,
    extract_state_change_paths,
)
from npc_director.state._sqlite import (
    SQLiteStore,
    datetime_text,
    json_dumps,
    parse_datetime,
    utc_now,
)
from npc_director.state.errors import (
    IdempotencyConflictError,
    OptimisticLockError,
    StatePatchPermissionError,
)


@dataclass(frozen=True, slots=True)
class StateCommitResult:
    turn_id: str
    npc_id: str
    state: NPCDomainState
    applied: bool
    committed_at: datetime
    session_id: str | None = None

    @property
    def version(self) -> int:
        return self.state.version

    @property
    def relationship(self) -> dict[str, int]:
        return self.state.relationship

    @property
    def world_flags(self) -> dict[str, bool]:
        return self.state.world_flags

    @property
    def quests(self) -> dict[str, str]:
        return self.state.quests


def _patch_hash(patch: StateChangeProposal) -> str:
    return hashlib.sha256(
        json_dumps(patch.model_dump(mode="json", exclude_none=True)).encode()
    ).hexdigest()


def _unauthorized_paths(patch: StateChangeProposal, allowed_paths: Collection[str]) -> set[str]:
    return {
        path
        for path in extract_state_change_paths(patch)
        if not any(fnmatchcase(path, pattern) for pattern in allowed_paths)
    }


def _apply_patch(state: NPCDomainState, patch: StateChangeProposal) -> NPCDomainState:
    updated = state.model_copy(deep=True)
    if patch.relationship is not None:
        relationship = updated.relationship.copy()
        if patch.relationship.trust_delta:
            relationship["trust"] = relationship.get("trust", 0) + patch.relationship.trust_delta
        if patch.relationship.affinity_delta:
            relationship["affinity"] = (
                relationship.get("affinity", 0) + patch.relationship.affinity_delta
            )
        updated.relationship = relationship
    updated.world_flags.update({flag.name: flag.value for flag in patch.flags})
    updated.quests.update({quest.quest_id: quest.status for quest in patch.quests})
    return updated


def _scope(session_id: str | None) -> tuple[str, str, str, tuple[str, ...]]:
    if session_id is None:
        return "npc_domain_states", "state_commits", "", ()
    if not session_id.strip():
        raise ValueError("session_id must not be blank")
    return "scoped_npc_domain_states", "scoped_state_commits", "session_id = ? AND ", (session_id,)


class DomainStateStore(SQLiteStore):
    """Scoped NPC truth with optimistic commits; session_id=None is legacy only."""

    def __init__(self, database: str | Path) -> None:
        super().__init__(database)

    def get(self, npc_id: str, *, session_id: str | None = None) -> NPCDomainState | None:
        table, _, clause, scope = _scope(session_id)
        with self.connection() as connection:
            row = connection.execute(
                f"SELECT state_json FROM {table} WHERE {clause}npc_id = ?", (*scope, npc_id)
            ).fetchone()
        return None if row is None else NPCDomainState.model_validate_json(row["state_json"])

    @staticmethod
    def _insert_state(
        connection: sqlite3.Connection,
        state: NPCDomainState,
        session_id: str | None,
        *,
        ignore: bool = False,
    ) -> None:
        table, _, _, scope = _scope(session_id)
        columns = "session_id, " if session_id is not None else ""
        placeholders = "?, " if session_id is not None else ""
        verb = "INSERT OR IGNORE" if ignore else "INSERT"
        connection.execute(
            f"{verb} INTO {table} ({columns}npc_id, state_json, version, updated_at) "
            f"VALUES ({placeholders}?, ?, ?, ?)",
            (*scope, state.npc_id, state.model_dump_json(), state.version, datetime_text()),
        )

    def get_or_create(self, npc_id: str, *, session_id: str | None = None) -> NPCDomainState:
        table, _, clause, scope = _scope(session_id)
        with self.transaction() as connection:
            self._insert_state(connection, NPCDomainState(npc_id=npc_id), session_id, ignore=True)
            row = connection.execute(
                f"SELECT state_json FROM {table} WHERE {clause}npc_id = ?", (*scope, npc_id)
            ).fetchone()
        assert row is not None
        return NPCDomainState.model_validate_json(row["state_json"])

    def create(self, state: NPCDomainState, *, session_id: str | None = None) -> NPCDomainState:
        with self.transaction() as connection:
            self._insert_state(connection, state, session_id)
        return state

    def save(
        self,
        state: NPCDomainState,
        *,
        expected_version: int | None = None,
        session_id: str | None = None,
    ) -> NPCDomainState:
        table, _, clause, scope = _scope(session_id)
        expected = state.version if expected_version is None else expected_version
        updated = state.model_copy(update={"version": expected + 1}, deep=True)
        with self.transaction() as connection:
            cursor = connection.execute(
                f"UPDATE {table} SET state_json = ?, version = ?, updated_at = ? "
                f"WHERE {clause}npc_id = ? AND version = ?",
                (
                    updated.model_dump_json(),
                    updated.version,
                    datetime_text(),
                    *scope,
                    updated.npc_id,
                    expected,
                ),
            )
            if cursor.rowcount != 1:
                raise OptimisticLockError(
                    f"NPC {(session_id, state.npc_id)!r} no longer has version {expected}"
                )
        return updated

    def commit_completed(
        self,
        turn_id: str,
        npc_id: str,
        patch: StateChangeProposal,
        *,
        expected_version: int,
        allowed_paths: Collection[str] = (),
        session_id: str | None = None,
    ) -> StateCommitResult:
        with self.transaction() as connection:
            return self.commit_completed_in_connection(
                connection,
                turn_id,
                npc_id,
                patch,
                expected_version=expected_version,
                allowed_paths=allowed_paths,
                session_id=session_id,
            )

    def commit_completed_in_connection(
        self,
        connection: sqlite3.Connection,
        turn_id: str,
        npc_id: str,
        patch: StateChangeProposal,
        *,
        expected_version: int,
        allowed_paths: Collection[str] = (),
        session_id: str | None = None,
    ) -> StateCommitResult:
        """Participate in a caller-owned completion transaction; never commits it."""
        if not connection.in_transaction:
            raise ValueError("completion requires an active transaction")
        unauthorized = _unauthorized_paths(patch, allowed_paths)
        if unauthorized:
            raise StatePatchPermissionError(
                "State patch paths are not allowed: " + ", ".join(sorted(unauthorized))
            )
        table, commits, clause, scope = _scope(session_id)
        fingerprint = _patch_hash(patch)
        existing = connection.execute(
            f"SELECT npc_id, patch_hash, expected_version, state_json, committed_at "
            f"FROM {commits} WHERE {clause}turn_id = ?",
            (*scope, turn_id),
        ).fetchone()
        if existing is not None:
            if (
                existing["npc_id"] != npc_id
                or existing["patch_hash"] != fingerprint
                or existing["expected_version"] != expected_version
            ):
                raise IdempotencyConflictError(
                    f"Turn {(session_id, turn_id)!r} already has a different commit"
                )
            return StateCommitResult(
                turn_id,
                npc_id,
                NPCDomainState.model_validate_json(existing["state_json"]),
                False,
                parse_datetime(existing["committed_at"]),
                session_id,
            )
        row = connection.execute(
            f"SELECT state_json, version FROM {table} WHERE {clause}npc_id = ?",
            (*scope, npc_id),
        ).fetchone()
        if row is None:
            current = NPCDomainState(npc_id=npc_id)
            self._insert_state(connection, current, session_id)
        else:
            current = NPCDomainState.model_validate_json(row["state_json"])
        has_changes = bool(extract_state_change_paths(patch))
        if has_changes and current.version != expected_version:
            raise OptimisticLockError(
                f"NPC {(session_id, npc_id)!r} expected version {expected_version}, "
                f"found {current.version}"
            )
        updated = _apply_patch(current, patch)
        if has_changes:
            updated.version = current.version + 1
            cursor = connection.execute(
                f"UPDATE {table} SET state_json = ?, version = ?, updated_at = ? "
                f"WHERE {clause}npc_id = ? AND version = ?",
                (
                    updated.model_dump_json(),
                    updated.version,
                    datetime_text(),
                    *scope,
                    npc_id,
                    expected_version,
                ),
            )
            if cursor.rowcount != 1:
                raise OptimisticLockError(f"NPC {npc_id!r} changed during commit")
        committed_at = utc_now()
        columns = "session_id, " if session_id is not None else ""
        placeholders = "?, " if session_id is not None else ""
        connection.execute(
            f"INSERT INTO {commits} ({columns}turn_id, npc_id, patch_hash, expected_version, "
            f"resulting_version, state_json, committed_at) "
            f"VALUES ({placeholders}?, ?, ?, ?, ?, ?, ?)",
            (
                *scope,
                turn_id,
                npc_id,
                fingerprint,
                expected_version,
                updated.version,
                updated.model_dump_json(),
                datetime_text(committed_at),
            ),
        )
        return StateCommitResult(turn_id, npc_id, updated, True, committed_at, session_id)

    def commit_completed_event(
        self,
        event: EngineEvent,
        npc_id: str,
        patch: StateChangeProposal,
        *,
        expected_version: int,
        allowed_paths: Collection[str] = (),
        session_id: str | None = None,
    ) -> StateCommitResult:
        if EngineEventType(event.event_type) is not EngineEventType.COMPLETED:
            raise ValueError("Domain state can only be committed after a completed event")
        if session_id is not None and event.session_id != session_id:
            raise ValueError("completed event belongs to a different session")
        return self.commit_completed(
            event.turn_id,
            npc_id,
            patch,
            expected_version=expected_version,
            allowed_paths=allowed_paths,
            session_id=session_id,
        )

    def apply_patch(
        self,
        npc_id: str,
        patch: StateChangeProposal,
        *,
        turn_id: str,
        expected_version: int,
        allowed_paths: Collection[str] = (),
        session_id: str | None = None,
    ) -> StateCommitResult:
        return self.commit_completed(
            turn_id,
            npc_id,
            patch,
            expected_version=expected_version,
            allowed_paths=allowed_paths,
            session_id=session_id,
        )

    def has_commit(self, turn_id: str, *, session_id: str | None = None) -> bool:
        _, table, clause, scope = _scope(session_id)
        with self.connection() as connection:
            row = connection.execute(
                f"SELECT 1 FROM {table} WHERE {clause}turn_id = ?",
                (*scope, turn_id),
            ).fetchone()
        return row is not None

    load = get
    initialize = get_or_create
    apply_completed_event = commit_completed_event
    commit_on_completed = commit_completed_event

    async def aget(self, npc_id: str, *, session_id: str | None = None) -> NPCDomainState | None:
        return await asyncio.to_thread(self.get, npc_id, session_id=session_id)

    async def aget_or_create(self, npc_id: str, *, session_id: str | None = None) -> NPCDomainState:
        return await asyncio.to_thread(self.get_or_create, npc_id, session_id=session_id)

    async def acommit_completed(
        self,
        turn_id: str,
        npc_id: str,
        patch: StateChangeProposal,
        *,
        expected_version: int,
        allowed_paths: Collection[str] = (),
        session_id: str | None = None,
    ) -> StateCommitResult:
        operation = partial(
            self.commit_completed,
            turn_id,
            npc_id,
            patch,
            expected_version=expected_version,
            allowed_paths=allowed_paths,
            session_id=session_id,
        )
        return await asyncio.to_thread(operation)
