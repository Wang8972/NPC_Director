from __future__ import annotations

import asyncio
import hashlib
import sqlite3
from datetime import datetime
from functools import partial
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from npc_director.contracts import EngineEvent, EngineEventType
from npc_director.state._sqlite import (
    SQLiteStore,
    as_utc,
    datetime_text,
    json_dumps,
    json_loads,
    parse_datetime,
    utc_now,
)
from npc_director.state.errors import IdempotencyConflictError


class EventLogEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sequence: int = Field(gt=0)
    event_key: str
    session_id: str
    turn_id: str
    idempotency_key: str
    event_type: str
    payload: dict[str, Any]
    occurred_at: datetime
    recorded_at: datetime
    appended: bool = True


def _engine_event_key(event: EngineEvent) -> str:
    event_type = EngineEventType(event.event_type).value
    identity = "\x1f".join(
        (
            event.session_id,
            event.turn_id,
            event.idempotency_key,
            event_type,
        )
    )
    return hashlib.sha256(identity.encode()).hexdigest()


class EventLog(SQLiteStore):
    """Append-only event journal with logical-event deduplication."""

    def __init__(self, database: str | Path) -> None:
        super().__init__(database)

    def append(self, event: EngineEvent, *, event_key: str | None = None) -> EventLogEntry:
        event_type = EngineEventType(event.event_type).value
        return self.append_data(
            session_id=event.session_id,
            turn_id=event.turn_id,
            idempotency_key=event.idempotency_key,
            event_type=event_type,
            payload=event.model_dump(mode="json", warnings=False),
            occurred_at=event.occurred_at,
            event_key=event_key or _engine_event_key(event),
            allow_duplicate_payload=True,
        )

    def append_data(
        self,
        *,
        session_id: str,
        turn_id: str,
        idempotency_key: str,
        event_type: str,
        payload: dict[str, Any],
        occurred_at: datetime | None = None,
        event_key: str | None = None,
        allow_duplicate_payload: bool = False,
    ) -> EventLogEntry:
        resolved_occurred_at = as_utc(occurred_at)
        resolved_key = (
            event_key
            or hashlib.sha256(
                "\x1f".join((session_id, turn_id, idempotency_key, event_type)).encode()
            ).hexdigest()
        )
        serialized = json_dumps(payload)
        recorded_at = utc_now()
        try:
            with self.transaction() as connection:
                cursor = connection.execute(
                    """
                    INSERT INTO event_log
                        (event_key, session_id, turn_id, idempotency_key, event_type,
                         payload_json, occurred_at, recorded_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        resolved_key,
                        session_id,
                        turn_id,
                        idempotency_key,
                        event_type,
                        serialized,
                        datetime_text(resolved_occurred_at),
                        datetime_text(recorded_at),
                    ),
                )
                sequence = cursor.lastrowid
        except sqlite3.IntegrityError as error:
            existing = self.get_by_key(resolved_key)
            if existing is None:
                raise
            if (
                existing.session_id != session_id
                or existing.turn_id != turn_id
                or existing.idempotency_key != idempotency_key
                or existing.event_type != event_type
                or (not allow_duplicate_payload and json_dumps(existing.payload) != serialized)
            ):
                raise IdempotencyConflictError(
                    f"Event key {resolved_key!r} was reused with different data"
                ) from error
            return existing.model_copy(update={"appended": False})

        assert sequence is not None
        return EventLogEntry(
            sequence=sequence,
            event_key=resolved_key,
            session_id=session_id,
            turn_id=turn_id,
            idempotency_key=idempotency_key,
            event_type=event_type,
            payload=payload,
            occurred_at=resolved_occurred_at,
            recorded_at=recorded_at,
        )

    def get_by_key(self, event_key: str) -> EventLogEntry | None:
        with self.connection() as connection:
            row = connection.execute(
                "SELECT * FROM event_log WHERE event_key = ?",
                (event_key,),
            ).fetchone()
        return None if row is None else self._entry_from_row(row)

    def events_for_turn(self, turn_id: str) -> list[EventLogEntry]:
        with self.connection() as connection:
            rows = connection.execute(
                "SELECT * FROM event_log WHERE turn_id = ? ORDER BY sequence",
                (turn_id,),
            ).fetchall()
        return [self._entry_from_row(row) for row in rows]

    def all(self, *, after_sequence: int = 0, limit: int = 1_000) -> list[EventLogEntry]:
        if limit < 1:
            return []
        with self.connection() as connection:
            rows = connection.execute(
                """
                SELECT * FROM event_log
                WHERE sequence > ?
                ORDER BY sequence
                LIMIT ?
                """,
                (after_sequence, limit),
            ).fetchall()
        return [self._entry_from_row(row) for row in rows]

    def count(self, *, turn_id: str | None = None) -> int:
        with self.connection() as connection:
            if turn_id is None:
                row = connection.execute("SELECT COUNT(*) AS count FROM event_log").fetchone()
            else:
                row = connection.execute(
                    "SELECT COUNT(*) AS count FROM event_log WHERE turn_id = ?",
                    (turn_id,),
                ).fetchone()
        assert row is not None
        return row["count"]

    list_events = events_for_turn

    @staticmethod
    def _entry_from_row(row: sqlite3.Row) -> EventLogEntry:
        return EventLogEntry(
            sequence=row["sequence"],
            event_key=row["event_key"],
            session_id=row["session_id"],
            turn_id=row["turn_id"],
            idempotency_key=row["idempotency_key"],
            event_type=row["event_type"],
            payload=json_loads(row["payload_json"]),
            occurred_at=parse_datetime(row["occurred_at"]),
            recorded_at=parse_datetime(row["recorded_at"]),
        )

    async def aappend(
        self,
        event: EngineEvent,
        *,
        event_key: str | None = None,
    ) -> EventLogEntry:
        operation = partial(self.append, event, event_key=event_key)
        return await asyncio.to_thread(operation)

    async def aevents_for_turn(self, turn_id: str) -> list[EventLogEntry]:
        return await asyncio.to_thread(self.events_for_turn, turn_id)
