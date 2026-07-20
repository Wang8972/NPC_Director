from __future__ import annotations

import asyncio
import sqlite3
from dataclasses import dataclass
from functools import partial
from pathlib import Path
from typing import Any

from npc_director.contracts import TurnRequest, TurnStateRecord, TurnStatus
from npc_director.contracts.workflow import utc_now
from npc_director.state._sqlite import SQLiteStore, datetime_text
from npc_director.state.errors import (
    IdempotencyConflictError,
    OptimisticLockError,
    RecordNotFoundError,
)


@dataclass(frozen=True, slots=True)
class StoredTurn:
    record: TurnStateRecord
    revision: int


class TurnStore(SQLiteStore):
    """Durable snapshots for resumable turn workflow state."""

    def __init__(self, database: str | Path) -> None:
        super().__init__(database)

    def start_turn(self, request: TurnRequest) -> TurnStateRecord:
        record = TurnStateRecord(
            turn_id=request.turn_id,
            session_id=request.session_id,
            npc_id=request.npc_id,
            request=request,
        )
        try:
            return self.create(record)
        except IdempotencyConflictError:
            existing = self.get(request.turn_id)
            if existing is not None and existing.request == request:
                return existing
            raise

    def create(self, record: TurnStateRecord) -> TurnStateRecord:
        try:
            with self.transaction() as connection:
                connection.execute(
                    """
                    INSERT INTO turns
                        (turn_id, session_id, npc_id, status, record_json, revision,
                         created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, 0, ?, ?)
                    """,
                    (
                        record.turn_id,
                        record.session_id,
                        record.npc_id,
                        record.status.value,
                        record.model_dump_json(),
                        datetime_text(record.created_at),
                        datetime_text(record.updated_at),
                    ),
                )
        except sqlite3.IntegrityError as error:
            existing = self.get(record.turn_id)
            if existing == record:
                return existing
            raise IdempotencyConflictError(
                f"Turn {record.turn_id!r} already exists with different data"
            ) from error
        return record

    def get(self, turn_id: str) -> TurnStateRecord | None:
        stored = self.get_with_revision(turn_id)
        return None if stored is None else stored.record

    def require(self, turn_id: str) -> TurnStateRecord:
        record = self.get(turn_id)
        if record is None:
            raise RecordNotFoundError(f"Turn {turn_id!r} does not exist")
        return record

    def get_with_revision(self, turn_id: str) -> StoredTurn | None:
        with self.connection() as connection:
            row = connection.execute(
                "SELECT record_json, revision FROM turns WHERE turn_id = ?",
                (turn_id,),
            ).fetchone()
        if row is None:
            return None
        return StoredTurn(
            record=TurnStateRecord.model_validate_json(row["record_json"]),
            revision=row["revision"],
        )

    def save(
        self,
        record: TurnStateRecord,
        *,
        expected_revision: int | None = None,
    ) -> TurnStateRecord:
        updated = record.model_copy(update={"updated_at": utc_now()}, deep=True)
        with self.transaction() as connection:
            row = connection.execute(
                "SELECT revision FROM turns WHERE turn_id = ?",
                (record.turn_id,),
            ).fetchone()
            if row is None:
                raise RecordNotFoundError(f"Turn {record.turn_id!r} does not exist")
            expected = row["revision"] if expected_revision is None else expected_revision
            cursor = connection.execute(
                """
                UPDATE turns
                SET session_id = ?, npc_id = ?, status = ?, record_json = ?,
                    revision = revision + 1, updated_at = ?
                WHERE turn_id = ? AND revision = ?
                """,
                (
                    updated.session_id,
                    updated.npc_id,
                    updated.status.value,
                    updated.model_dump_json(),
                    datetime_text(updated.updated_at),
                    updated.turn_id,
                    expected,
                ),
            )
            if cursor.rowcount != 1:
                actual = connection.execute(
                    "SELECT revision FROM turns WHERE turn_id = ?",
                    (record.turn_id,),
                ).fetchone()
                actual_revision = None if actual is None else actual["revision"]
                raise OptimisticLockError(
                    f"Turn {record.turn_id!r} expected revision {expected}, found {actual_revision}"
                )
        return updated

    def update(
        self,
        turn_id: str,
        *,
        expected_revision: int | None = None,
        **changes: Any,
    ) -> TurnStateRecord:
        stored = self.get_with_revision(turn_id)
        if stored is None:
            raise RecordNotFoundError(f"Turn {turn_id!r} does not exist")
        payload = stored.record.model_dump()
        payload.update(changes)
        updated = TurnStateRecord.model_validate(payload)
        expected = stored.revision if expected_revision is None else expected_revision
        return self.save(updated, expected_revision=expected)

    def update_status(
        self,
        turn_id: str,
        status: TurnStatus | str,
        *,
        expected_revision: int | None = None,
        **changes: Any,
    ) -> TurnStateRecord:
        return self.update(
            turn_id,
            expected_revision=expected_revision,
            status=TurnStatus(status),
            **changes,
        )

    def list_by_status(
        self,
        status: TurnStatus | str,
        *,
        limit: int = 100,
    ) -> list[TurnStateRecord]:
        if limit < 1:
            return []
        with self.connection() as connection:
            rows = connection.execute(
                """
                SELECT record_json FROM turns
                WHERE status = ?
                ORDER BY updated_at, turn_id
                LIMIT ?
                """,
                (TurnStatus(status).value, limit),
            ).fetchall()
        return [TurnStateRecord.model_validate_json(row["record_json"]) for row in rows]

    load = get

    async def astart_turn(self, request: TurnRequest) -> TurnStateRecord:
        return await asyncio.to_thread(self.start_turn, request)

    async def aget(self, turn_id: str) -> TurnStateRecord | None:
        return await asyncio.to_thread(self.get, turn_id)

    async def asave(
        self,
        record: TurnStateRecord,
        *,
        expected_revision: int | None = None,
    ) -> TurnStateRecord:
        operation = partial(self.save, record, expected_revision=expected_revision)
        return await asyncio.to_thread(operation)

    async def aupdate_status(
        self,
        turn_id: str,
        status: TurnStatus | str,
        *,
        expected_revision: int | None = None,
        **changes: Any,
    ) -> TurnStateRecord:
        operation = partial(
            self.update_status,
            turn_id,
            status,
            expected_revision=expected_revision,
            **changes,
        )
        return await asyncio.to_thread(operation)
