from __future__ import annotations

import asyncio
import hashlib
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
    payload = patch.model_dump(mode="json", exclude_none=True)
    return hashlib.sha256(json_dumps(payload).encode()).hexdigest()


def _unauthorized_paths(
    patch: StateChangeProposal,
    allowed_paths: Collection[str],
) -> set[str]:
    proposed_paths = extract_state_change_paths(patch)
    return {
        path
        for path in proposed_paths
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

    world_flags = updated.world_flags.copy()
    for flag in patch.flags:
        world_flags[flag.name] = flag.value
    updated.world_flags = world_flags

    quests = updated.quests.copy()
    for quest in patch.quests:
        quests[quest.quest_id] = quest.status
    updated.quests = quests
    return updated


class DomainStateStore(SQLiteStore):
    """SQLite source of truth for NPC state with optimistic, idempotent commits."""

    def __init__(self, database: str | Path) -> None:
        super().__init__(database)

    def get(self, npc_id: str) -> NPCDomainState | None:
        with self.connection() as connection:
            row = connection.execute(
                "SELECT state_json FROM npc_domain_states WHERE npc_id = ?",
                (npc_id,),
            ).fetchone()
        if row is None:
            return None
        return NPCDomainState.model_validate_json(row["state_json"])

    def get_or_create(self, npc_id: str) -> NPCDomainState:
        initial = NPCDomainState(npc_id=npc_id)
        serialized = initial.model_dump_json()
        with self.transaction() as connection:
            connection.execute(
                """
                INSERT OR IGNORE INTO npc_domain_states
                    (npc_id, state_json, version, updated_at)
                VALUES (?, ?, ?, ?)
                """,
                (npc_id, serialized, initial.version, datetime_text()),
            )
            row = connection.execute(
                "SELECT state_json FROM npc_domain_states WHERE npc_id = ?",
                (npc_id,),
            ).fetchone()
        assert row is not None
        return NPCDomainState.model_validate_json(row["state_json"])

    def create(self, state: NPCDomainState) -> NPCDomainState:
        with self.transaction() as connection:
            connection.execute(
                """
                INSERT INTO npc_domain_states (npc_id, state_json, version, updated_at)
                VALUES (?, ?, ?, ?)
                """,
                (
                    state.npc_id,
                    state.model_dump_json(),
                    state.version,
                    datetime_text(),
                ),
            )
        return state

    def save(
        self,
        state: NPCDomainState,
        *,
        expected_version: int | None = None,
    ) -> NPCDomainState:
        expected = state.version if expected_version is None else expected_version
        updated = state.model_copy(update={"version": expected + 1}, deep=True)
        with self.transaction() as connection:
            cursor = connection.execute(
                """
                UPDATE npc_domain_states
                SET state_json = ?, version = ?, updated_at = ?
                WHERE npc_id = ? AND version = ?
                """,
                (
                    updated.model_dump_json(),
                    updated.version,
                    datetime_text(),
                    updated.npc_id,
                    expected,
                ),
            )
            if cursor.rowcount != 1:
                current = connection.execute(
                    "SELECT version FROM npc_domain_states WHERE npc_id = ?",
                    (updated.npc_id,),
                ).fetchone()
                actual = None if current is None else current["version"]
                raise OptimisticLockError(
                    f"NPC {updated.npc_id!r} expected version {expected}, found {actual}"
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
    ) -> StateCommitResult:
        unauthorized = _unauthorized_paths(patch, allowed_paths)
        if unauthorized:
            paths = ", ".join(sorted(unauthorized))
            raise StatePatchPermissionError(f"State patch paths are not allowed: {paths}")

        fingerprint = _patch_hash(patch)
        with self.transaction() as connection:
            existing = connection.execute(
                """
                SELECT npc_id, patch_hash, expected_version, state_json, committed_at
                FROM state_commits
                WHERE turn_id = ?
                """,
                (turn_id,),
            ).fetchone()
            if existing is not None:
                if (
                    existing["npc_id"] != npc_id
                    or existing["patch_hash"] != fingerprint
                    or existing["expected_version"] != expected_version
                ):
                    raise IdempotencyConflictError(
                        f"Turn {turn_id!r} was already committed with different state data"
                    )
                return StateCommitResult(
                    turn_id=turn_id,
                    npc_id=npc_id,
                    state=NPCDomainState.model_validate_json(existing["state_json"]),
                    applied=False,
                    committed_at=parse_datetime(existing["committed_at"]),
                )

            row = connection.execute(
                "SELECT state_json, version FROM npc_domain_states WHERE npc_id = ?",
                (npc_id,),
            ).fetchone()
            if row is None:
                current = NPCDomainState(npc_id=npc_id)
                connection.execute(
                    """
                    INSERT INTO npc_domain_states (npc_id, state_json, version, updated_at)
                    VALUES (?, ?, ?, ?)
                    """,
                    (npc_id, current.model_dump_json(), current.version, datetime_text()),
                )
            else:
                current = NPCDomainState.model_validate_json(row["state_json"])

            has_changes = bool(extract_state_change_paths(patch))
            if has_changes and current.version != expected_version:
                raise OptimisticLockError(
                    f"NPC {npc_id!r} expected version {expected_version}, found {current.version}"
                )

            updated = _apply_patch(current, patch)
            if has_changes:
                updated.version = current.version + 1
                cursor = connection.execute(
                    """
                    UPDATE npc_domain_states
                    SET state_json = ?, version = ?, updated_at = ?
                    WHERE npc_id = ? AND version = ?
                    """,
                    (
                        updated.model_dump_json(),
                        updated.version,
                        datetime_text(),
                        npc_id,
                        expected_version,
                    ),
                )
                if cursor.rowcount != 1:
                    raise OptimisticLockError(
                        f"NPC {npc_id!r} changed while committing turn {turn_id!r}"
                    )

            committed_at = utc_now()
            connection.execute(
                """
                INSERT INTO state_commits
                    (turn_id, npc_id, patch_hash, expected_version, resulting_version,
                     state_json, committed_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    turn_id,
                    npc_id,
                    fingerprint,
                    expected_version,
                    updated.version,
                    updated.model_dump_json(),
                    datetime_text(committed_at),
                ),
            )
        return StateCommitResult(
            turn_id=turn_id,
            npc_id=npc_id,
            state=updated,
            applied=True,
            committed_at=committed_at,
        )

    def commit_completed_event(
        self,
        event: EngineEvent,
        npc_id: str,
        patch: StateChangeProposal,
        *,
        expected_version: int,
        allowed_paths: Collection[str] = (),
    ) -> StateCommitResult:
        if EngineEventType(event.event_type) is not EngineEventType.COMPLETED:
            raise ValueError("Domain state can only be committed after a completed event")
        return self.commit_completed(
            event.turn_id,
            npc_id,
            patch,
            expected_version=expected_version,
            allowed_paths=allowed_paths,
        )

    def apply_patch(
        self,
        npc_id: str,
        patch: StateChangeProposal,
        *,
        turn_id: str,
        expected_version: int,
        allowed_paths: Collection[str] = (),
    ) -> StateCommitResult:
        return self.commit_completed(
            turn_id,
            npc_id,
            patch,
            expected_version=expected_version,
            allowed_paths=allowed_paths,
        )

    def has_commit(self, turn_id: str) -> bool:
        with self.connection() as connection:
            row = connection.execute(
                "SELECT 1 FROM state_commits WHERE turn_id = ?",
                (turn_id,),
            ).fetchone()
        return row is not None

    load = get
    initialize = get_or_create
    apply_completed_event = commit_completed_event
    commit_on_completed = commit_completed_event

    async def aget(self, npc_id: str) -> NPCDomainState | None:
        return await asyncio.to_thread(self.get, npc_id)

    async def aget_or_create(self, npc_id: str) -> NPCDomainState:
        return await asyncio.to_thread(self.get_or_create, npc_id)

    async def acommit_completed(
        self,
        turn_id: str,
        npc_id: str,
        patch: StateChangeProposal,
        *,
        expected_version: int,
        allowed_paths: Collection[str] = (),
    ) -> StateCommitResult:
        operation = partial(
            self.commit_completed,
            turn_id,
            npc_id,
            patch,
            expected_version=expected_version,
            allowed_paths=allowed_paths,
        )
        return await asyncio.to_thread(operation)
