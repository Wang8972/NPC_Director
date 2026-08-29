from __future__ import annotations

import hashlib
import sqlite3
from pathlib import Path

from npc_director.prototype.models import (
    NPC_IDS,
    ActionCommitResult,
    ApprovedAction,
    PendingActionRecord,
    PendingActionSummary,
    PrototypeNpcState,
    PrototypeWorldState,
    build_action_idempotency_key,
    initial_npc_state,
)
from npc_director.state._sqlite import SQLiteStore, datetime_text, json_dumps, utc_now
from npc_director.state.errors import IdempotencyConflictError, RecordNotFoundError

PROTOTYPE_SCHEMA = """
CREATE TABLE IF NOT EXISTS prototype_game_session_states (
    session_id TEXT PRIMARY KEY,
    state_json TEXT NOT NULL,
    world_version INTEGER NOT NULL CHECK (world_version >= 0),
    revision INTEGER NOT NULL DEFAULT 0 CHECK (revision >= 0),
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS prototype_npc_session_states (
    session_id TEXT NOT NULL,
    npc_id TEXT NOT NULL,
    state_json TEXT NOT NULL,
    version INTEGER NOT NULL CHECK (version >= 0),
    revision INTEGER NOT NULL DEFAULT 0 CHECK (revision >= 0),
    updated_at TEXT NOT NULL,
    PRIMARY KEY (session_id, npc_id)
);

CREATE TABLE IF NOT EXISTS prototype_pending_actions (
    action_id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL UNIQUE,
    idempotency_key TEXT NOT NULL UNIQUE,
    record_json TEXT NOT NULL,
    effect_hash TEXT NOT NULL,
    status TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS prototype_action_commits (
    action_id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL,
    idempotency_key TEXT NOT NULL UNIQUE,
    effect_hash TEXT NOT NULL,
    result_json TEXT NOT NULL,
    resulting_world_version INTEGER NOT NULL,
    committed_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS prototype_chain_jobs (
    source_action_id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL,
    target_npc_id TEXT NOT NULL,
    status TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
"""


class PrototypeVersionConflict(RuntimeError):
    """A pending action was completed against an obsolete world or NPC basis."""


class InjectedCommitFailure(RuntimeError):
    """Test-only failure raised inside the atomic commit transaction."""


def _effect_hash(approved: ApprovedAction) -> str:
    payload = approved.effect.model_dump(mode="json")
    return hashlib.sha256(json_dumps(payload).encode()).hexdigest()


class PrototypeStateRepository(SQLiteStore):
    """Session-scoped world/NPC state and atomic scene-action commit ledger."""

    def __init__(self, database: str | Path) -> None:
        super().__init__(database)
        with self.transaction() as connection:
            connection.executescript(PROTOTYPE_SCHEMA)

    def initialize(self, session_id: str) -> PrototypeWorldState:
        initial_world = PrototypeWorldState(session_id=session_id)
        with self.transaction() as connection:
            connection.execute(
                """
                INSERT OR IGNORE INTO prototype_game_session_states
                    (session_id, state_json, world_version, revision, updated_at)
                VALUES (?, ?, ?, 0, ?)
                """,
                (
                    session_id,
                    initial_world.model_dump_json(),
                    initial_world.version,
                    datetime_text(),
                ),
            )
            for npc_id in NPC_IDS:
                state = initial_npc_state(session_id, npc_id)
                connection.execute(
                    """
                    INSERT OR IGNORE INTO prototype_npc_session_states
                        (session_id, npc_id, state_json, version, revision, updated_at)
                    VALUES (?, ?, ?, ?, 0, ?)
                    """,
                    (
                        session_id,
                        npc_id,
                        state.model_dump_json(),
                        state.version,
                        datetime_text(),
                    ),
                )
        return self.get_world(session_id)

    def reset(self, session_id: str) -> PrototypeWorldState:
        """Delete exactly one prototype session and recreate its frozen initial state."""
        with self.transaction() as connection:
            connection.execute(
                "DELETE FROM prototype_chain_jobs WHERE session_id = ?", (session_id,)
            )
            connection.execute(
                "DELETE FROM prototype_action_commits WHERE session_id = ?", (session_id,)
            )
            connection.execute(
                "DELETE FROM prototype_pending_actions WHERE session_id = ?", (session_id,)
            )
            connection.execute(
                "DELETE FROM prototype_npc_session_states WHERE session_id = ?", (session_id,)
            )
            connection.execute(
                "DELETE FROM prototype_game_session_states WHERE session_id = ?", (session_id,)
            )
        return self.initialize(session_id)

    def get_world(self, session_id: str) -> PrototypeWorldState:
        with self.connection() as connection:
            row = connection.execute(
                """
                SELECT state_json FROM prototype_game_session_states
                WHERE session_id = ?
                """,
                (session_id,),
            ).fetchone()
        if row is None:
            raise RecordNotFoundError(f"Prototype session {session_id!r} does not exist")
        return PrototypeWorldState.model_validate_json(row["state_json"])

    def get_npc(self, session_id: str, npc_id: str) -> PrototypeNpcState:
        with self.connection() as connection:
            row = connection.execute(
                """
                SELECT state_json FROM prototype_npc_session_states
                WHERE session_id = ? AND npc_id = ?
                """,
                (session_id, npc_id),
            ).fetchone()
        if row is None:
            raise RecordNotFoundError(
                f"Prototype NPC state {(session_id, npc_id)!r} does not exist"
            )
        return PrototypeNpcState.model_validate_json(row["state_json"])

    def get_npcs(self, session_id: str) -> dict[str, PrototypeNpcState]:
        return {npc_id: self.get_npc(session_id, npc_id) for npc_id in NPC_IDS}

    def get_pending(self, action_id: str) -> PendingActionRecord | None:
        with self.connection() as connection:
            row = connection.execute(
                """
                SELECT record_json FROM prototype_pending_actions
                WHERE action_id = ?
                """,
                (action_id,),
            ).fetchone()
        return None if row is None else PendingActionRecord.model_validate_json(row["record_json"])

    def prepare_action(self, approved: ApprovedAction) -> PendingActionRecord:
        candidate = approved.candidate
        key = build_action_idempotency_key(candidate)
        record = PendingActionRecord(approved=approved, idempotency_key=key)
        fingerprint = _effect_hash(approved)
        with self.transaction() as connection:
            committed = connection.execute(
                """
                SELECT idempotency_key, effect_hash, result_json
                FROM prototype_action_commits WHERE action_id = ?
                """,
                (candidate.action_id,),
            ).fetchone()
            if committed is not None:
                if committed["idempotency_key"] != key or committed["effect_hash"] != fingerprint:
                    raise IdempotencyConflictError(
                        f"Action {candidate.action_id!r} was committed with different data"
                    )
                return record.model_copy(update={"status": "completed"})

            existing = connection.execute(
                """
                SELECT idempotency_key, effect_hash, record_json
                FROM prototype_pending_actions WHERE action_id = ?
                """,
                (candidate.action_id,),
            ).fetchone()
            if existing is not None:
                if existing["idempotency_key"] != key or existing["effect_hash"] != fingerprint:
                    raise IdempotencyConflictError(
                        f"Action {candidate.action_id!r} was prepared with different data"
                    )
                return PendingActionRecord.model_validate_json(existing["record_json"])

            world_row = connection.execute(
                """
                SELECT state_json, world_version, revision
                FROM prototype_game_session_states WHERE session_id = ?
                """,
                (candidate.session_id,),
            ).fetchone()
            if world_row is None:
                raise RecordNotFoundError(f"Prototype session {candidate.session_id!r} missing")
            world = PrototypeWorldState.model_validate_json(world_row["state_json"])
            if world.pending_action is not None:
                raise PrototypeVersionConflict(
                    f"Session already has pending action {world.pending_action.action_id!r}"
                )
            if world.version != approved.basis_world_version:
                raise PrototypeVersionConflict(
                    f"World expected {approved.basis_world_version}, found {world.version}"
                )
            for npc_id, expected in approved.basis_npc_versions.items():
                npc_row = connection.execute(
                    """
                    SELECT version FROM prototype_npc_session_states
                    WHERE session_id = ? AND npc_id = ?
                    """,
                    (candidate.session_id, npc_id),
                ).fetchone()
                actual = None if npc_row is None else npc_row["version"]
                if actual != expected:
                    raise PrototypeVersionConflict(
                        f"NPC {npc_id!r} expected {expected}, found {actual}"
                    )

            world.pending_action = PendingActionSummary(
                action_id=candidate.action_id,
                actor_id=candidate.actor_id,
                action_type=candidate.action_type,
                basis_world_version=approved.basis_world_version,
            )
            now = datetime_text()
            connection.execute(
                """
                UPDATE prototype_game_session_states
                SET state_json = ?, revision = ?, updated_at = ?
                WHERE session_id = ?
                """,
                (
                    world.model_dump_json(),
                    world_row["revision"] + 1,
                    now,
                    candidate.session_id,
                ),
            )
            connection.execute(
                """
                INSERT INTO prototype_pending_actions
                    (action_id, session_id, idempotency_key, record_json, effect_hash,
                     status, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    candidate.action_id,
                    candidate.session_id,
                    key,
                    record.model_dump_json(),
                    fingerprint,
                    record.status,
                    now,
                    now,
                ),
            )
        return record

    def mark_lifecycle(self, action_id: str, status: str) -> PendingActionRecord:
        if status not in {"ack", "started"}:
            raise ValueError("Only ack/started can be marked without committing or cancelling")
        with self.transaction() as connection:
            row = connection.execute(
                "SELECT record_json FROM prototype_pending_actions WHERE action_id = ?",
                (action_id,),
            ).fetchone()
            if row is None:
                raise RecordNotFoundError(f"Pending action {action_id!r} not found")
            record = PendingActionRecord.model_validate_json(row["record_json"])
            updated = record.model_copy(update={"status": status})
            connection.execute(
                """
                UPDATE prototype_pending_actions
                SET record_json = ?, status = ?, updated_at = ?
                WHERE action_id = ?
                """,
                (updated.model_dump_json(), status, datetime_text(), action_id),
            )
        return updated

    def cancel_action(self, action_id: str, *, status: str) -> bool:
        if status not in {"interrupted", "error"}:
            raise ValueError("Cancellation status must be interrupted or error")
        with self.transaction() as connection:
            row = connection.execute(
                """
                SELECT session_id FROM prototype_pending_actions WHERE action_id = ?
                """,
                (action_id,),
            ).fetchone()
            if row is None:
                return False
            session_id = row["session_id"]
            world_row = connection.execute(
                """
                SELECT state_json, revision FROM prototype_game_session_states
                WHERE session_id = ?
                """,
                (session_id,),
            ).fetchone()
            assert world_row is not None
            world = PrototypeWorldState.model_validate_json(world_row["state_json"])
            world.pending_action = None
            connection.execute(
                """
                UPDATE prototype_game_session_states
                SET state_json = ?, revision = ?, updated_at = ?
                WHERE session_id = ?
                """,
                (
                    world.model_dump_json(),
                    world_row["revision"] + 1,
                    datetime_text(),
                    session_id,
                ),
            )
            connection.execute(
                "DELETE FROM prototype_pending_actions WHERE action_id = ?",
                (action_id,),
            )
        return True

    def commit_completed(
        self,
        action_id: str,
        idempotency_key: str,
        *,
        fail_after_world_write: bool = False,
    ) -> ActionCommitResult:
        with self.transaction() as connection:
            existing = connection.execute(
                """
                SELECT idempotency_key, result_json FROM prototype_action_commits
                WHERE action_id = ?
                """,
                (action_id,),
            ).fetchone()
            if existing is not None:
                if existing["idempotency_key"] != idempotency_key:
                    raise IdempotencyConflictError(
                        f"Action {action_id!r} completed with a different key"
                    )
                result = ActionCommitResult.model_validate_json(existing["result_json"])
                return result.model_copy(update={"applied": False})

            pending_row = connection.execute(
                """
                SELECT session_id, idempotency_key, record_json, effect_hash
                FROM prototype_pending_actions WHERE action_id = ?
                """,
                (action_id,),
            ).fetchone()
            if pending_row is None:
                raise RecordNotFoundError(f"Pending action {action_id!r} not found")
            if pending_row["idempotency_key"] != idempotency_key:
                raise IdempotencyConflictError(f"Action {action_id!r} key mismatch")
            record = PendingActionRecord.model_validate_json(pending_row["record_json"])
            approved = record.approved
            session_id = pending_row["session_id"]

            world_row = connection.execute(
                """
                SELECT state_json, world_version, revision
                FROM prototype_game_session_states WHERE session_id = ?
                """,
                (session_id,),
            ).fetchone()
            assert world_row is not None
            world = PrototypeWorldState.model_validate_json(world_row["state_json"])
            if world.version != approved.basis_world_version:
                raise PrototypeVersionConflict(
                    f"World expected {approved.basis_world_version}, found {world.version}"
                )
            npc_states: dict[str, PrototypeNpcState] = {}
            for npc_id in NPC_IDS:
                npc_row = connection.execute(
                    """
                    SELECT state_json FROM prototype_npc_session_states
                    WHERE session_id = ? AND npc_id = ?
                    """,
                    (session_id, npc_id),
                ).fetchone()
                assert npc_row is not None
                npc_states[npc_id] = PrototypeNpcState.model_validate_json(
                    npc_row["state_json"]
                )
            for npc_id, expected in approved.basis_npc_versions.items():
                actual = npc_states[npc_id].version
                if actual != expected:
                    raise PrototypeVersionConflict(
                        f"NPC {npc_id!r} expected {expected}, found {actual}"
                    )

            effect = approved.effect
            updated_world = world.model_copy(deep=True)
            updated_world.object_states.update(effect.set_object_states)
            updated_world.item_locations.update(effect.set_item_locations)
            updated_world.discovered_fact_ids.update(effect.add_player_fact_ids)
            for name, value in effect.set_route_flags.items():
                setattr(updated_world.route_flags, name, value)
            if effect.objective_state is not None:
                updated_world.objective_state = effect.objective_state  # type: ignore[assignment]
            updated_world.pending_action = None
            if effect.changes_world():
                updated_world.version += 1

            now = datetime_text()
            connection.execute(
                """
                UPDATE prototype_game_session_states
                SET state_json = ?, world_version = ?, revision = ?, updated_at = ?
                WHERE session_id = ?
                """,
                (
                    updated_world.model_dump_json(),
                    updated_world.version,
                    world_row["revision"] + 1,
                    now,
                    session_id,
                ),
            )
            if fail_after_world_write:
                raise InjectedCommitFailure("injected after world write, before NPC write")

            changed_npcs = set(effect.npc_fact_additions) | set(effect.npc_event_additions)
            for npc_id in changed_npcs:
                current = npc_states[npc_id]
                updated = current.model_copy(deep=True)
                updated.known_fact_ids.update(effect.npc_fact_additions.get(npc_id, set()))
                updated.observed_event_ids.update(effect.npc_event_additions.get(npc_id, set()))
                if (
                    updated.known_fact_ids != current.known_fact_ids
                    or updated.observed_event_ids != current.observed_event_ids
                ):
                    updated.version += 1
                    connection.execute(
                        """
                        UPDATE prototype_npc_session_states
                        SET state_json = ?, version = ?, revision = revision + 1, updated_at = ?
                        WHERE session_id = ? AND npc_id = ? AND version = ?
                        """,
                        (
                            updated.model_dump_json(),
                            updated.version,
                            now,
                            session_id,
                            npc_id,
                            current.version,
                        ),
                    )
                    npc_states[npc_id] = updated

            if effect.internal_reply_target is not None:
                connection.execute(
                    """
                    INSERT INTO prototype_chain_jobs
                        (source_action_id, session_id, target_npc_id, status,
                         created_at, updated_at)
                    VALUES (?, ?, ?, 'ready', ?, ?)
                    """,
                    (
                        action_id,
                        session_id,
                        effect.internal_reply_target,
                        now,
                        now,
                    ),
                )

            result = ActionCommitResult(
                action_id=action_id,
                idempotency_key=idempotency_key,
                world=updated_world,
                npc_states=npc_states,
                reveal_fact_ids=effect.reveal_fact_ids,
                applied=True,
            )
            connection.execute(
                """
                INSERT INTO prototype_action_commits
                    (action_id, session_id, idempotency_key, effect_hash, result_json,
                     resulting_world_version, committed_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    action_id,
                    session_id,
                    idempotency_key,
                    pending_row["effect_hash"],
                    result.model_dump_json(),
                    updated_world.version,
                    datetime_text(utc_now()),
                ),
            )
            connection.execute(
                "DELETE FROM prototype_pending_actions WHERE action_id = ?",
                (action_id,),
            )
        return result

    def dispatch_chain_job_once(self, source_action_id: str) -> tuple[str, str] | None:
        with self.transaction() as connection:
            row = connection.execute(
                """
                SELECT session_id, target_npc_id, status
                FROM prototype_chain_jobs WHERE source_action_id = ?
                """,
                (source_action_id,),
            ).fetchone()
            if row is None or row["status"] != "ready":
                return None
            cursor = connection.execute(
                """
                UPDATE prototype_chain_jobs SET status = 'dispatched', updated_at = ?
                WHERE source_action_id = ? AND status = 'ready'
                """,
                (datetime_text(), source_action_id),
            )
            if cursor.rowcount != 1:
                return None
        return row["session_id"], row["target_npc_id"]

    def finish_chain_job(self, source_action_id: str, status: str) -> bool:
        if status not in {"completed", "interrupted", "error"}:
            raise ValueError("Internal reply must finish with a terminal status")
        with self.transaction() as connection:
            cursor = connection.execute(
                """
                UPDATE prototype_chain_jobs SET status = ?, updated_at = ?
                WHERE source_action_id = ? AND status = 'dispatched'
                """,
                (status, datetime_text(), source_action_id),
            )
        return cursor.rowcount == 1

    def count_commits(self, *, session_id: str | None = None) -> int:
        with self.connection() as connection:
            if session_id is None:
                row = connection.execute(
                    "SELECT COUNT(*) AS count FROM prototype_action_commits"
                ).fetchone()
            else:
                row = connection.execute(
                    """
                    SELECT COUNT(*) AS count FROM prototype_action_commits
                    WHERE session_id = ?
                    """,
                    (session_id,),
                ).fetchone()
        assert row is not None
        return row["count"]

    def force_world_version_for_test(self, session_id: str) -> int:
        """Create a stale basis without opening a second pending action."""
        with self.transaction() as connection:
            row = connection.execute(
                """
                SELECT state_json, revision FROM prototype_game_session_states
                WHERE session_id = ?
                """,
                (session_id,),
            ).fetchone()
            assert row is not None
            world = PrototypeWorldState.model_validate_json(row["state_json"])
            world.version += 1
            connection.execute(
                """
                UPDATE prototype_game_session_states
                SET state_json = ?, world_version = ?, revision = ?, updated_at = ?
                WHERE session_id = ?
                """,
                (
                    world.model_dump_json(),
                    world.version,
                    row["revision"] + 1,
                    datetime_text(),
                    session_id,
                ),
            )
        return world.version

    def force_npc_version_for_test(self, session_id: str, npc_id: str) -> int:
        """Create a stale NPC basis without changing knowledge contents."""
        with self.transaction() as connection:
            row = connection.execute(
                """
                SELECT state_json FROM prototype_npc_session_states
                WHERE session_id = ? AND npc_id = ?
                """,
                (session_id, npc_id),
            ).fetchone()
            assert row is not None
            state = PrototypeNpcState.model_validate_json(row["state_json"])
            state.version += 1
            connection.execute(
                """
                UPDATE prototype_npc_session_states
                SET state_json = ?, version = ?, revision = revision + 1, updated_at = ?
                WHERE session_id = ? AND npc_id = ?
                """,
                (state.model_dump_json(), state.version, datetime_text(), session_id, npc_id),
            )
        return state.version

    def raw_table_counts(self) -> dict[str, int]:
        tables = (
            "prototype_game_session_states",
            "prototype_npc_session_states",
            "prototype_pending_actions",
            "prototype_action_commits",
            "prototype_chain_jobs",
        )
        with self.connection() as connection:
            return {
                table: connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                for table in tables
            }


def sqlite_supports_transactions() -> bool:
    return sqlite3.sqlite_version_info >= (3, 8, 0)
