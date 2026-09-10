"""Durable event-driven episodes, scoped perception, and completion transactions."""

from __future__ import annotations

import asyncio
import hashlib
import sqlite3
from collections.abc import Callable, Mapping, Sequence
from contextlib import nullcontext
from datetime import timedelta
from pathlib import Path
from typing import Any

from pydantic_core import to_jsonable_python

from npc_director.contracts.episodes import (
    DialogueEvent,
    DialogueState,
    EpisodeBudget,
    EpisodeJob,
    EpisodeRecord,
    EpisodeRequest,
    KnowledgeClaim,
    NodeLedgerRecord,
    NpcMessage,
)
from npc_director.state._sqlite import SQLiteStore, datetime_text, json_dumps, json_loads, utc_now
from npc_director.state.errors import (
    IdempotencyConflictError,
    OptimisticLockError,
    RecordNotFoundError,
)

_TERMINAL = {"completed", "cancelled", "failed", "unsupported", "budget_exhausted", "no_progress"}
_RESOURCE_FIELDS = {
    "model_call": ("used_model_calls", "max_model_calls"),
    "npc_turn": ("used_npc_turns", "max_npc_turns"),
    "node": ("used_nodes", "max_nodes"),
    "plan_revision": ("used_plan_revisions", "max_plan_revisions"),
    "repair": ("used_repairs", "max_repairs"),
    "new_quest": ("reserved_quests", "max_new_quests"),
}


def _digest(value: Any) -> str:
    return hashlib.sha256(json_dumps(value).encode()).hexdigest()


def _identifier(prefix: str, *parts: str) -> str:
    return f"{prefix}:{hashlib.sha256(chr(0).join(parts).encode()).hexdigest()[:40]}"


def _require_session(session_id: str) -> None:
    if not session_id.strip():
        raise ValueError("session_id must not be blank")


class EpisodeStore(SQLiteStore):
    def __init__(self, database: str | Path) -> None:
        super().__init__(database)

    def _write_connection(self, connection: sqlite3.Connection | None):
        if connection is None:
            return self.transaction()
        if not connection.in_transaction:
            raise ValueError("composed writes require an active transaction")
        return nullcontext(connection)

    @staticmethod
    def get_in_connection(connection: sqlite3.Connection, episode_id: str) -> EpisodeRecord:
        row = connection.execute(
            "SELECT record_json FROM episodes WHERE episode_id = ?", (episode_id,)
        ).fetchone()
        if row is None:
            raise RecordNotFoundError(f"Episode {episode_id!r} does not exist")
        return EpisodeRecord.model_validate_json(row["record_json"])

    def get_episode(self, episode_id: str) -> EpisodeRecord | None:
        with self.connection() as connection:
            try:
                return self.get_in_connection(connection, episode_id)
            except RecordNotFoundError:
                return None

    get = get_episode

    def create_episode(
        self,
        request: EpisodeRequest,
        *,
        budget: EpisodeBudget | None = None,
        episode_id: str | None = None,
    ) -> EpisodeRecord:
        resolved_budget = budget or EpisodeBudget()
        participants = set(request.participants) | {request.npc_id}
        if len(participants) > resolved_budget.max_participants:
            raise ValueError("episode participant budget exceeded")
        identity = episode_id or _identifier("episode", request.session_id, request.event_id)
        fingerprint = _digest(request.model_dump(mode="json"))
        with self.transaction() as connection:
            previous = connection.execute(
                "SELECT episode_id, request_hash FROM episodes "
                "WHERE session_id = ? AND event_id = ?",
                (request.session_id, request.event_id),
            ).fetchone()
            if previous is not None:
                if previous["request_hash"] != fingerprint or (
                    episode_id is not None and previous["episode_id"] != episode_id
                ):
                    raise IdempotencyConflictError("episode event was reused with different input")
                existing = self.get_in_connection(connection, previous["episode_id"])
                if budget is not None and existing.budget != budget:
                    raise IdempotencyConflictError("episode budget is immutable")
                return existing
            record = EpisodeRecord(
                id=identity, session_id=request.session_id, request=request, budget=resolved_budget
            )
            connection.execute(
                """INSERT INTO episodes
                (episode_id, session_id, event_id, request_hash, status, revision,
                 record_json, created_at, updated_at) VALUES (?, ?, ?, ?, ?, 0, ?, ?, ?)""",
                (
                    record.id,
                    record.session_id,
                    request.event_id,
                    fingerprint,
                    record.status,
                    record.model_dump_json(),
                    datetime_text(record.created_at),
                    datetime_text(record.updated_at),
                ),
            )
        return record

    @staticmethod
    def save_in_connection(
        connection: sqlite3.Connection,
        record: EpisodeRecord,
        *,
        expected_revision: int | None = None,
    ) -> EpisodeRecord:
        if not connection.in_transaction:
            raise ValueError("episode save requires an active transaction")
        record = EpisodeRecord.model_validate(record.model_dump())
        current = EpisodeStore.get_in_connection(connection, record.id)
        if current.session_id != record.session_id or current.request != record.request:
            raise ValueError("episode identity and originating request are immutable")
        if current.budget != record.budget:
            raise ValueError("episode budget is immutable")
        counters = (
            "used_model_calls",
            "used_npc_turns",
            "used_nodes",
            "used_tokens",
            "active_seconds",
            "used_plan_revisions",
            "used_repairs",
            "published_quests",
            "epoch",
        )
        if any(getattr(record, field) < getattr(current, field) for field in counters):
            raise ValueError("episode consumption and epoch cannot move backwards")
        expected = record.revision if expected_revision is None else expected_revision
        updated = record.model_copy(update={"revision": expected + 1, "updated_at": utc_now()})
        cursor = connection.execute(
            """UPDATE episodes SET status = ?, revision = ?, record_json = ?, updated_at = ?
            WHERE episode_id = ? AND revision = ?""",
            (
                updated.status,
                updated.revision,
                updated.model_dump_json(),
                datetime_text(updated.updated_at),
                updated.id,
                expected,
            ),
        )
        if cursor.rowcount != 1:
            raise OptimisticLockError(f"Episode {record.id!r} changed since revision {expected}")
        return updated

    def save_episode(
        self, record: EpisodeRecord, *, expected_revision: int | None = None
    ) -> EpisodeRecord:
        with self.transaction() as connection:
            return self.save_in_connection(connection, record, expected_revision=expected_revision)

    def list_episodes(self, session_id: str, *, active_only: bool = False) -> list[EpisodeRecord]:
        with self.connection() as connection:
            rows = connection.execute(
                "SELECT record_json FROM episodes WHERE session_id = ? ORDER BY created_at",
                (session_id,),
            ).fetchall()
        records = [EpisodeRecord.model_validate_json(row["record_json"]) for row in rows]
        return [r for r in records if not active_only or r.status not in _TERMINAL]

    def record_event(
        self,
        episode_id: str,
        event_id: str,
        event_type: str,
        payload: Mapping[str, Any],
        *,
        connection: sqlite3.Connection | None = None,
    ) -> bool:
        with self._write_connection(connection) as conn:
            episode = self.get_in_connection(conn, episode_id)
            serialized = json_dumps(dict(payload))
            row = conn.execute(
                "SELECT episode_id, event_type, payload_json FROM episode_events "
                "WHERE session_id = ? AND event_id = ?",
                (episode.session_id, event_id),
            ).fetchone()
            if row is not None:
                if (
                    row["episode_id"] != episode_id
                    or row["event_type"] != event_type
                    or row["payload_json"] != serialized
                ):
                    raise IdempotencyConflictError("episode event payload changed")
                return False
            conn.execute(
                "INSERT INTO episode_events VALUES (?, ?, ?, ?, ?, ?)",
                (episode.session_id, event_id, episode_id, event_type, serialized, datetime_text()),
            )
            return True

    def reserve_budget(
        self,
        episode_id: str,
        *,
        operation_id: str,
        resource: str,
        role: str = "",
        token_reservation: int = 0,
    ) -> bool:
        """Reserve before work. An exact retry reuses its reservation without charging twice."""
        if resource not in _RESOURCE_FIELDS:
            raise ValueError(f"unknown episode resource: {resource}")
        if token_reservation < 0 or (resource != "model_call" and token_reservation):
            raise ValueError("only model calls may reserve nonnegative tokens")
        with self.transaction() as connection:
            episode = self.get_in_connection(connection, episode_id)
            existing = connection.execute(
                "SELECT resource, role, status, token_reservation FROM episode_reservations "
                "WHERE episode_id = ? AND operation_id = ?",
                (episode_id, operation_id),
            ).fetchone()
            if existing is not None:
                if (
                    existing["resource"] != resource
                    or existing["role"] != role
                    or existing["token_reservation"] != token_reservation
                ):
                    raise IdempotencyConflictError("budget operation identity changed")
                return existing["status"] != "released"
            if episode.status in _TERMINAL:
                return False
            field, maximum = _RESOURCE_FIELDS[resource]
            used = getattr(episode, field)
            limit = getattr(episode.budget, maximum)
            if resource == "repair":
                used = connection.execute(
                    "SELECT COUNT(*) FROM episode_reservations "
                    "WHERE episode_id = ? AND resource = 'repair' AND role = ? "
                    "AND status != 'released'",
                    (episode_id, role),
                ).fetchone()[0]
            if resource == "new_quest":
                used += episode.published_quests
            exhausted = used >= limit
            if resource == "model_call":
                exhausted |= episode.used_tokens >= episode.budget.max_total_tokens
                exhausted |= episode.active_seconds >= episode.budget.max_active_seconds
                exhausted |= (
                    episode.used_tokens + episode.reserved_tokens + token_reservation
                    > episode.budget.max_total_tokens
                )
            if exhausted:
                return False
            connection.execute(
                "INSERT INTO episode_reservations "
                "(episode_id, operation_id, resource, role, token_reservation, status, created_at) "
                "VALUES (?, ?, ?, ?, ?, 'reserved', ?)",
                (episode_id, operation_id, resource, role, token_reservation, datetime_text()),
            )
            self.save_in_connection(
                connection,
                episode.model_copy(
                    update={
                        field: getattr(episode, field) + 1,
                        "reserved_tokens": episode.reserved_tokens + token_reservation,
                    }
                ),
            )
            return True

    async def reserve_model_call(
        self, episode_id: str, *, operation_id: str, role: str, token_reservation: int = 0
    ) -> bool:
        return await asyncio.to_thread(
            self.reserve_budget,
            episode_id,
            operation_id=operation_id,
            resource="model_call",
            role=role,
            token_reservation=token_reservation,
        )

    async def reserve_npc_turn(
        self, episode_id: str, *, operation_id: str, role: str = "npc"
    ) -> bool:
        return await asyncio.to_thread(
            self.reserve_budget,
            episode_id,
            operation_id=operation_id,
            resource="npc_turn",
            role=role,
        )

    def _record_model_usage(
        self,
        episode_id: str,
        operation_id: str,
        *,
        input_tokens: int = 0,
        output_tokens: int = 0,
        total_tokens: int = 0,
        elapsed_seconds: float = 0,
        usage_known: bool = True,
    ) -> bool:
        if min(input_tokens, output_tokens, total_tokens, elapsed_seconds) < 0:
            raise ValueError("model usage must not be negative")
        usage = {
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "total_tokens": max(total_tokens, input_tokens + output_tokens),
            "elapsed_seconds": elapsed_seconds,
            "usage_known": usage_known,
        }
        serialized = json_dumps(usage)
        with self.transaction() as connection:
            episode = self.get_in_connection(connection, episode_id)
            row = connection.execute(
                "SELECT resource, usage_json, token_reservation FROM episode_reservations "
                "WHERE episode_id = ? AND operation_id = ?",
                (episode_id, operation_id),
            ).fetchone()
            if row is None or row["resource"] != "model_call":
                raise ValueError("model usage has no matching call reservation")
            if row["usage_json"] is not None:
                if row["usage_json"] != serialized:
                    raise IdempotencyConflictError("model usage changed on replay")
                return False
            reservation = row["token_reservation"]
            charged_tokens = (
                usage["total_tokens"]
                if usage_known
                else max(usage["total_tokens"], reservation or episode.budget.max_total_tokens)
            )
            connection.execute(
                "UPDATE episode_reservations SET usage_json = ?, status = 'consumed' "
                "WHERE episode_id = ? AND operation_id = ?",
                (serialized, episode_id, operation_id),
            )
            self.save_in_connection(
                connection,
                episode.model_copy(
                    update={
                        "used_tokens": episode.used_tokens + charged_tokens,
                        "reserved_tokens": max(0, episode.reserved_tokens - reservation),
                        "active_seconds": episode.active_seconds + elapsed_seconds,
                    }
                ),
            )
            return True

    async def record_model_usage(
        self,
        episode_id: str,
        operation_id: str,
        *,
        input_tokens: int = 0,
        output_tokens: int = 0,
        total_tokens: int = 0,
        elapsed_seconds: float = 0,
        usage_known: bool = True,
    ) -> bool:
        return await asyncio.to_thread(
            self._record_model_usage,
            episode_id,
            operation_id,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            total_tokens=total_tokens,
            elapsed_seconds=elapsed_seconds,
            usage_known=usage_known,
        )

    def record_node(self, record: NodeLedgerRecord) -> NodeLedgerRecord:
        with self.transaction() as connection:
            episode = self.get_in_connection(connection, record.episode_id)
            row = connection.execute(
                "SELECT record_json FROM episode_nodes WHERE episode_id = ? AND node_id = ?",
                (record.episode_id, record.node_id),
            ).fetchone()
            if row is not None:
                previous = NodeLedgerRecord.model_validate_json(row["record_json"])
                if previous.input_digest != record.input_digest or previous.kind != record.kind:
                    raise IdempotencyConflictError("node input identity changed")
                if previous.status in {"completed", "skipped"}:
                    fields = {"created_at", "updated_at"}
                    if previous.model_dump(exclude=fields) != record.model_dump(exclude=fields):
                        raise IdempotencyConflictError("completed node result changed")
                    return previous
                record = record.model_copy(
                    update={"created_at": previous.created_at, "updated_at": utc_now()}
                )
            else:
                if episode.status in _TERMINAL or episode.used_nodes >= episode.budget.max_nodes:
                    raise ValueError("episode node budget exhausted")
                self.save_in_connection(
                    connection, episode.model_copy(update={"used_nodes": episode.used_nodes + 1})
                )
            connection.execute(
                "INSERT INTO episode_nodes VALUES (?, ?, ?) "
                "ON CONFLICT(episode_id, node_id) DO UPDATE SET record_json = excluded.record_json",
                (record.episode_id, record.node_id, record.model_dump_json()),
            )
            return record

    def get_node(self, episode_id: str, node_id: str) -> NodeLedgerRecord | None:
        with self.connection() as connection:
            row = connection.execute(
                "SELECT record_json FROM episode_nodes WHERE episode_id = ? AND node_id = ?",
                (episode_id, node_id),
            ).fetchone()
        return None if row is None else NodeLedgerRecord.model_validate_json(row["record_json"])

    def list_nodes(self, episode_id: str) -> list[NodeLedgerRecord]:
        with self.connection() as connection:
            rows = connection.execute(
                "SELECT record_json FROM episode_nodes WHERE episode_id = ? ORDER BY rowid",
                (episode_id,),
            ).fetchall()
        return [NodeLedgerRecord.model_validate_json(row["record_json"]) for row in rows]

    def queue_job(
        self,
        episode_id: str,
        message: NpcMessage,
        *,
        parent_turn_id: str | None = None,
        source_event_id: str | None = None,
        dedupe_key: str | None = None,
        turn_id: str | None = None,
        connection: sqlite3.Connection | None = None,
    ) -> EpisodeJob:
        with self._write_connection(connection) as conn:
            episode = self.get_in_connection(conn, episode_id)
            roster = set(episode.request.participants) | {episode.request.npc_id}
            if message.target_npc_id not in roster:
                raise ValueError("target NPC is not a trusted episode participant")
            if message.speaker_id not in roster and message.speaker_id not in {"player", "world"}:
                raise ValueError("speaker is not a trusted episode participant")
            key = dedupe_key or _digest(
                {
                    "parent": parent_turn_id,
                    "source": source_event_id,
                    "message": message.model_dump(mode="json"),
                }
            )
            row = conn.execute(
                "SELECT record_json FROM episode_jobs WHERE episode_id = ? AND dedupe_key = ?",
                (episode_id, key),
            ).fetchone()
            if row is not None:
                existing = EpisodeJob.model_validate_json(row["record_json"])
                if (
                    existing.message != message
                    or existing.parent_turn_id != parent_turn_id
                    or existing.source_event_id != source_event_id
                    or (turn_id is not None and existing.turn_id != turn_id)
                ):
                    raise IdempotencyConflictError("queued job payload changed")
                return existing
            if episode.status in _TERMINAL:
                raise ValueError("cannot enqueue work for a terminal episode")
            job = EpisodeJob(
                job_id=_identifier("job", episode_id, key),
                episode_id=episode_id,
                session_id=episode.session_id,
                turn_id=turn_id or _identifier("npc", episode_id, key),
                message=message,
                parent_turn_id=parent_turn_id,
                source_event_id=source_event_id,
                dedupe_key=key,
                epoch=episode.epoch,
            )
            conn.execute(
                """INSERT INTO episode_jobs
                (job_id, episode_id, session_id, turn_id, dedupe_key, status, parent_turn_id,
                 record_json, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    job.job_id,
                    episode_id,
                    job.session_id,
                    job.turn_id,
                    key,
                    job.status,
                    parent_turn_id,
                    job.model_dump_json(),
                    datetime_text(job.created_at),
                ),
            )
            return job

    @staticmethod
    def _save_job(connection: sqlite3.Connection, job: EpisodeJob) -> None:
        connection.execute(
            "UPDATE episode_jobs SET status = ?, claimed_by = ?, lease_until = ?, record_json = ? "
            "WHERE job_id = ?",
            (
                job.status,
                job.claimed_by,
                datetime_text(job.lease_until) if job.lease_until is not None else None,
                job.model_dump_json(),
                job.job_id,
            ),
        )

    def claim_job(
        self,
        *,
        session_id: str | None = None,
        episode_id: str | None = None,
        worker_id: str = "worker",
        lease_seconds: float = 60,
    ) -> EpisodeJob | None:
        if lease_seconds <= 0:
            raise ValueError("lease_seconds must be positive")
        now = utc_now()
        with self.transaction() as connection:
            rows = connection.execute(
                """SELECT record_json FROM episode_jobs
                WHERE (status = 'queued' OR (status = 'claimed' AND lease_until <= ?))
                  AND (? IS NULL OR session_id = ?) AND (? IS NULL OR episode_id = ?)
                ORDER BY created_at, job_id""",
                (datetime_text(now), session_id, session_id, episode_id, episode_id),
            ).fetchall()
            for row in rows:
                job = EpisodeJob.model_validate_json(row["record_json"])
                episode = self.get_in_connection(connection, job.episode_id)
                if episode.status in _TERMINAL or episode.epoch != job.epoch:
                    self._save_job(connection, job.model_copy(update={"status": "cancelled"}))
                    continue
                if job.parent_turn_id is not None:
                    completed = connection.execute(
                        "SELECT 1 FROM episode_completions WHERE session_id = ? AND turn_id = ?",
                        (job.session_id, job.parent_turn_id),
                    ).fetchone()
                    if completed is None:
                        continue
                active = connection.execute(
                    """SELECT 1 FROM episode_jobs WHERE session_id = ? AND job_id != ?
                    AND (status IN ('waiting', 'pending_approval')
                         OR (status = 'claimed' AND lease_until > ?)) LIMIT 1""",
                    (job.session_id, job.job_id, datetime_text(now)),
                ).fetchone()
                if active is not None:
                    continue
                claimed = job.model_copy(
                    update={
                        "status": "claimed",
                        "claimed_by": worker_id,
                        "lease_until": now + timedelta(seconds=lease_seconds),
                    }
                )
                self._save_job(connection, claimed)
                return claimed
        return None

    def update_job(
        self,
        job_id: str,
        status: str,
        *,
        worker_id: str | None = None,
    ) -> EpisodeJob:
        with self.transaction() as connection:
            row = connection.execute(
                "SELECT record_json FROM episode_jobs WHERE job_id = ?", (job_id,)
            ).fetchone()
            if row is None:
                raise RecordNotFoundError(f"Job {job_id!r} does not exist")
            job = EpisodeJob.model_validate_json(row["record_json"])
            if worker_id is not None and job.claimed_by != worker_id:
                raise OptimisticLockError("job belongs to a different worker")
            if job.status in {"completed", "cancelled", "failed"} and status != job.status:
                raise OptimisticLockError("terminal jobs cannot be reopened")
            updated = EpisodeJob.model_validate(
                {**job.model_dump(), "status": status, "lease_until": None}
            )
            self._save_job(connection, updated)
            return updated

    def list_jobs(self, episode_id: str) -> list[EpisodeJob]:
        with self.connection() as connection:
            rows = connection.execute(
                "SELECT record_json FROM episode_jobs WHERE episode_id = ? ORDER BY created_at",
                (episode_id,),
            ).fetchall()
        return [EpisodeJob.model_validate_json(row["record_json"]) for row in rows]

    def get_job(self, job_id: str) -> EpisodeJob | None:
        with self.connection() as connection:
            row = connection.execute(
                "SELECT record_json FROM episode_jobs WHERE job_id = ?", (job_id,)
            ).fetchone()
        return None if row is None else EpisodeJob.model_validate_json(row["record_json"])

    def finish_job(
        self, job_id: str, *, status: str = "completed", worker_id: str | None = None
    ) -> EpisodeJob:
        if status not in {"completed", "cancelled", "failed"}:
            raise ValueError("finish_job requires a terminal status")
        return self.update_job(job_id, status, worker_id=worker_id)

    def cancel_episode(
        self,
        episode_id: str,
        *,
        reason: str = "player_preempted",
        connection: sqlite3.Connection | None = None,
    ) -> EpisodeRecord:
        with (
            nullcontext(connection) if connection is not None else self.transaction() as connection
        ):
            episode = self.get_in_connection(connection, episode_id)
            if episode.status in _TERMINAL:
                return episode
            updated = self.save_in_connection(
                connection,
                episode.model_copy(
                    update={
                        "status": "cancelled",
                        "stop_reason": reason,
                        "epoch": episode.epoch + 1,
                    }
                ),
            )
            rows = connection.execute(
                "SELECT record_json FROM episode_jobs WHERE episode_id = ? "
                "AND status IN ('queued', 'claimed', 'pending_approval')",
                (episode_id,),
            ).fetchall()
            for row in rows:
                job = EpisodeJob.model_validate_json(row["record_json"])
                self._save_job(
                    connection, job.model_copy(update={"status": "cancelled", "lease_until": None})
                )
            return updated

    def record_dialogue(
        self,
        event: DialogueEvent,
        *,
        connection: sqlite3.Connection | None = None,
    ) -> bool:
        with self._write_connection(connection) as conn:
            row = conn.execute(
                "SELECT record_json FROM dialogue_events WHERE session_id = ? AND event_id = ?",
                (event.session_id, event.event_id),
            ).fetchone()
            if row is not None:
                previous = DialogueEvent.model_validate_json(row["record_json"])
                if previous.model_dump(exclude={"occurred_at"}) != event.model_dump(
                    exclude={"occurred_at"}
                ):
                    raise IdempotencyConflictError("dialogue event changed on replay")
                return False
            conn.execute(
                "INSERT INTO dialogue_events "
                "(session_id, event_id, turn_id, speaker_id, record_json, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (
                    event.session_id,
                    event.event_id,
                    event.turn_id,
                    event.speaker_id,
                    event.model_dump_json(),
                    datetime_text(event.occurred_at),
                ),
            )
            return True

    def save_dialogue_state(
        self,
        state: DialogueState,
        *,
        expected_version: int | None = None,
        connection: sqlite3.Connection | None = None,
    ) -> DialogueState:
        state = DialogueState.model_validate(state.model_dump())
        with self._write_connection(connection) as conn:
            row = conn.execute(
                "SELECT version FROM npc_dialogue_states WHERE session_id = ? AND npc_id = ?",
                (state.session_id, state.npc_id),
            ).fetchone()
            current = 0 if row is None else row["version"]
            expected = state.version if expected_version is None else expected_version
            if current != expected:
                raise OptimisticLockError("dialogue state version changed")
            updated = state.model_copy(update={"version": current + 1})
            conn.execute(
                "INSERT INTO npc_dialogue_states VALUES (?, ?, ?, ?) "
                "ON CONFLICT(session_id, npc_id) DO UPDATE "
                "SET version = excluded.version, record_json = excluded.record_json",
                (state.session_id, state.npc_id, updated.version, updated.model_dump_json()),
            )
            return updated

    def grant_knowledge(
        self,
        session_id: str,
        npc_id: str,
        claim: KnowledgeClaim,
        *,
        source_event_id: str,
        connection: sqlite3.Connection | None = None,
    ) -> bool:
        _require_session(session_id)
        recorded = claim.model_copy(update={"source_event_id": source_event_id})
        with self._write_connection(connection) as conn:
            row = conn.execute(
                "SELECT record_json FROM npc_knowledge WHERE session_id = ? AND npc_id = ? "
                "AND content_id = ? AND source_event_id = ?",
                (session_id, npc_id, claim.content_id, source_event_id),
            ).fetchone()
            if row is not None:
                if KnowledgeClaim.model_validate_json(row["record_json"]) != recorded:
                    raise IdempotencyConflictError("knowledge source changed on replay")
                return False
            conn.execute(
                "INSERT INTO npc_knowledge VALUES (?, ?, ?, ?, ?)",
                (session_id, npc_id, claim.content_id, source_event_id, recorded.model_dump_json()),
            )
            return True

    def set_relationship(
        self,
        session_id: str,
        npc_id: str,
        target_actor_id: str,
        values: Mapping[str, int],
        *,
        expected_version: int | None = None,
        connection: sqlite3.Connection | None = None,
    ) -> dict[str, Any]:
        _require_session(session_id)
        with self._write_connection(connection) as conn:
            row = conn.execute(
                "SELECT version FROM npc_relationships "
                "WHERE session_id = ? AND npc_id = ? AND target_actor_id = ?",
                (session_id, npc_id, target_actor_id),
            ).fetchone()
            version = 0 if row is None else row["version"]
            if expected_version is not None and expected_version != version:
                raise OptimisticLockError("relationship version changed")
            record = {
                "npc_id": npc_id,
                "target_actor_id": target_actor_id,
                "values": dict(values),
                "version": version + 1,
            }
            conn.execute(
                "INSERT INTO npc_relationships VALUES (?, ?, ?, ?, ?) "
                "ON CONFLICT(session_id, npc_id, target_actor_id) DO UPDATE "
                "SET version = excluded.version, record_json = excluded.record_json",
                (session_id, npc_id, target_actor_id, version + 1, json_dumps(record)),
            )
            return record

    def get_context(self, session_id: str, npc_id: str, *, limit: int = 12) -> dict[str, Any]:
        _require_session(session_id)
        with self.connection() as connection:
            # Audience filtering happens before the limit, so another actor's
            # private exchange cannot displace this NPC's relevant history.
            rows = connection.execute(
                "SELECT record_json FROM dialogue_events "
                "WHERE session_id = ? ORDER BY sequence DESC",
                (session_id,),
            ).fetchall()
            blocked_turns = {
                row["turn_id"]
                for row in connection.execute(
                    "SELECT turn_id FROM turns WHERE session_id=? "
                    "AND json_extract(record_json,'$.proposal.plan.intent')='prompt_injection'",
                    (session_id,),
                ).fetchall()
            }
            events = []
            for row in rows:
                event = DialogueEvent.model_validate_json(row["record_json"])
                if event.status == "interrupted":
                    continue
                if event.origin == "player" and event.turn_id in blocked_turns:
                    continue
                if event.speaker_id == npc_id or npc_id in event.audience:
                    events.append(event)
                    if len(events) >= max(0, limit):
                        break
            if limit <= 0:
                events = []
            row = connection.execute(
                "SELECT record_json FROM npc_dialogue_states WHERE session_id = ? AND npc_id = ?",
                (session_id, npc_id),
            ).fetchone()
            state = (
                DialogueState(session_id=session_id, npc_id=npc_id)
                if row is None
                else DialogueState.model_validate_json(row["record_json"])
            )
            knowledge = connection.execute(
                "SELECT record_json FROM npc_knowledge WHERE session_id = ? AND npc_id = ? "
                "ORDER BY rowid",
                (session_id, npc_id),
            ).fetchall()
            relationships = connection.execute(
                "SELECT record_json FROM npc_relationships WHERE session_id = ? AND npc_id = ? "
                "ORDER BY target_actor_id",
                (session_id, npc_id),
            ).fetchall()
        ordered = list(reversed(events))
        active_knowledge = [
            KnowledgeClaim.model_validate_json(row["record_json"]) for row in knowledge
        ]
        active_knowledge = [
            claim
            for claim in active_knowledge
            if claim.expires_at is None or claim.expires_at > utc_now()
        ]
        return {
            "history": [f"{e.speaker_id}: {e.text}" for e in ordered],
            "dialogue_events": [e.model_dump(mode="json") for e in ordered],
            "dialogue_state": state.model_dump(mode="json"),
            "knowledge": [claim.model_dump(mode="json") for claim in active_knowledge],
            "relationships": [json_loads(row["record_json"]) for row in relationships],
        }

    def commit_completed(
        self,
        episode_id: str,
        turn_id: str,
        *,
        dialogue: DialogueEvent | None = None,
        dialogue_state: DialogueState | None = None,
        knowledge: Mapping[str, Sequence[KnowledgeClaim]] | None = None,
        next_messages: Sequence[NpcMessage] = (),
        event_id: str | None = None,
        idempotency_key: str | None = None,
        callback: Callable[[sqlite3.Connection], Any] | None = None,
        finish_episode: bool = False,
        waiting_status: str = "waiting_for_player",
    ) -> dict[str, Any]:
        """Atomically commit a real completion and its consequences.

        The trusted caller validates the engine receipt and frozen generation
        policy. callback participates in this transaction (domain, turn, content)
        and must perform no network/model calls or independent transactions.
        """
        source_event = event_id or _identifier("completed", episode_id, turn_id)
        if waiting_status not in {"waiting_for_player", "waiting_for_event"}:
            raise ValueError("invalid waiting status")
        payload = {
            "episode_id": episode_id,
            "turn_id": turn_id,
            "event_id": source_event,
            "idempotency_key": idempotency_key,
            "finish_episode": finish_episode,
            "waiting_status": waiting_status,
            "dialogue": None
            if dialogue is None
            else dialogue.model_dump(mode="json", exclude={"occurred_at"}),
            "dialogue_state": None
            if dialogue_state is None
            else dialogue_state.model_dump(mode="json"),
            "knowledge": {
                npc: [c.model_dump(mode="json") for c in claims]
                for npc, claims in (knowledge or {}).items()
            },
            "next_messages": [m.model_dump(mode="json") for m in next_messages],
        }
        fingerprint = _digest(payload)
        with self.transaction() as connection:
            episode = self.get_in_connection(connection, episode_id)
            existing = connection.execute(
                "SELECT episode_id, fingerprint, result_json FROM episode_completions "
                "WHERE session_id = ? AND turn_id = ?",
                (episode.session_id, turn_id),
            ).fetchone()
            if existing is not None:
                if existing["episode_id"] != episode_id or existing["fingerprint"] != fingerprint:
                    raise IdempotencyConflictError("completed turn effects changed on replay")
                return {**json_loads(existing["result_json"]), "applied": False}
            if dialogue is not None and (
                dialogue.session_id != episode.session_id
                or dialogue.turn_id != turn_id
                or dialogue.status != "completed"
            ):
                raise ValueError("completion dialogue identity/status does not match")
            if dialogue_state is not None and dialogue_state.session_id != episode.session_id:
                raise ValueError("dialogue state belongs to a different session")
            callback_result = (
                to_jsonable_python(callback(connection)) if callback is not None else None
            )
            if dialogue is not None:
                self.record_dialogue(dialogue, connection=connection)
                # Being told something is evidence of a claim, not proof of truth.
                for audience_id in dialogue.audience:
                    if audience_id == "player" or audience_id == dialogue.speaker_id:
                        continue
                    for claim in dialogue.claims:
                        heard = claim.model_copy(
                            update={
                                "epistemic_status": "reported",
                                "source_npc_id": dialogue.speaker_id,
                            }
                        )
                        self.grant_knowledge(
                            episode.session_id,
                            audience_id,
                            heard,
                            source_event_id=source_event,
                            connection=connection,
                        )
            if dialogue_state is not None:
                self.save_dialogue_state(dialogue_state, connection=connection)
            for npc_id, claims in (knowledge or {}).items():
                for claim in claims:
                    self.grant_knowledge(
                        episode.session_id,
                        npc_id,
                        claim,
                        source_event_id=source_event,
                        connection=connection,
                    )
            result = {
                "applied": True,
                "episode_id": episode_id,
                "turn_id": turn_id,
                "callback_result": callback_result,
                "job_ids": [],
            }
            connection.execute(
                "INSERT INTO episode_completions VALUES (?, ?, ?, ?, ?, ?)",
                (
                    episode.session_id,
                    turn_id,
                    episode_id,
                    fingerprint,
                    json_dumps(result),
                    datetime_text(),
                ),
            )
            row = connection.execute(
                "SELECT record_json FROM episode_jobs WHERE turn_id = ?", (turn_id,)
            ).fetchone()
            if row is not None:
                job = EpisodeJob.model_validate_json(row["record_json"])
                if job.episode_id != episode_id:
                    raise ValueError("completed job belongs to a different episode")
                self._save_job(
                    connection, job.model_copy(update={"status": "completed", "lease_until": None})
                )
            # A preempted utterance can still finish physically; record that fact,
            # but it must not resurrect its cancelled episode or descendants.
            episode = self.get_in_connection(connection, episode_id)
            if episode.status not in _TERMINAL:
                for message in next_messages:
                    job = self.queue_job(
                        episode_id,
                        message,
                        parent_turn_id=turn_id,
                        source_event_id=source_event,
                        connection=connection,
                    )
                    result["job_ids"].append(job.job_id)
                status = (
                    "completed"
                    if finish_episode
                    else "running"
                    if next_messages
                    else waiting_status
                )
                self.save_in_connection(
                    connection,
                    episode.model_copy(
                        update={
                            "status": status,
                            "active_turn_id": None,
                        }
                    ),
                )
            connection.execute(
                "UPDATE episode_completions SET result_json = ? "
                "WHERE session_id = ? AND turn_id = ?",
                (json_dumps(result), episode.session_id, turn_id),
            )
            self.record_event(
                episode_id, source_event, "turn.completed", payload, connection=connection
            )
            return result

    async def aget_episode(self, episode_id: str) -> EpisodeRecord | None:
        return await asyncio.to_thread(self.get_episode, episode_id)

    async def acreate_episode(self, request: EpisodeRequest, **kwargs: Any) -> EpisodeRecord:
        return await asyncio.to_thread(self.create_episode, request, **kwargs)

    async def aget_context(
        self, session_id: str, npc_id: str, *, limit: int = 12
    ) -> dict[str, Any]:
        return await asyncio.to_thread(self.get_context, session_id, npc_id, limit=limit)

    async def aclaim_job(self, **kwargs: Any) -> EpisodeJob | None:
        return await asyncio.to_thread(self.claim_job, **kwargs)

    async def acommit_completed(
        self, episode_id: str, turn_id: str, **kwargs: Any
    ) -> dict[str, Any]:
        return await asyncio.to_thread(self.commit_completed, episode_id, turn_id, **kwargs)
