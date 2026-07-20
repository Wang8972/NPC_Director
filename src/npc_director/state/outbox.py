from __future__ import annotations

import asyncio
import sqlite3
from datetime import datetime
from functools import partial
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter

from npc_director.state._sqlite import (
    SQLiteStore,
    as_utc,
    datetime_text,
    json_dumps,
    json_loads,
    parse_datetime,
    utc_now,
)
from npc_director.state.errors import IdempotencyConflictError, RecordNotFoundError

_ANY_ADAPTER = TypeAdapter(Any)


class OutboxMessage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    message_id: int = Field(gt=0)
    idempotency_key: str = Field(min_length=1, max_length=256)
    topic: str = Field(min_length=1, max_length=120)
    payload: Any
    status: Literal["pending", "sent", "dead"]
    attempts: int = Field(ge=0)
    available_at: datetime
    created_at: datetime
    updated_at: datetime
    sent_at: datetime | None = None
    last_error: str | None = None


def _jsonable(value: Any) -> Any:
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    return _ANY_ADAPTER.dump_python(value, mode="json")


class OutboxStore(SQLiteStore):
    """Transactional-style durable queue for retrying external side effects."""

    def __init__(self, database: str | Path) -> None:
        super().__init__(database)

    def enqueue(
        self,
        idempotency_key: str,
        payload: Any,
        *,
        topic: str = "performance.plan",
        available_at: datetime | None = None,
    ) -> OutboxMessage:
        resolved_payload = _jsonable(payload)
        serialized = json_dumps(resolved_payload)
        now = utc_now()
        due_at = as_utc(available_at)
        try:
            with self.transaction() as connection:
                cursor = connection.execute(
                    """
                    INSERT INTO outbox
                        (idempotency_key, topic, payload_json, status, attempts,
                         available_at, created_at, updated_at)
                    VALUES (?, ?, ?, 'pending', 0, ?, ?, ?)
                    """,
                    (
                        idempotency_key,
                        topic,
                        serialized,
                        datetime_text(due_at),
                        datetime_text(now),
                        datetime_text(now),
                    ),
                )
                message_id = cursor.lastrowid
        except sqlite3.IntegrityError as error:
            existing = self.get_by_idempotency_key(idempotency_key)
            if existing is None:
                raise
            if existing.topic != topic or json_dumps(existing.payload) != serialized:
                raise IdempotencyConflictError(
                    f"Outbox key {idempotency_key!r} was reused with different data"
                ) from error
            return existing

        assert message_id is not None
        return OutboxMessage(
            message_id=message_id,
            idempotency_key=idempotency_key,
            topic=topic,
            payload=resolved_payload,
            status="pending",
            attempts=0,
            available_at=due_at,
            created_at=now,
            updated_at=now,
        )

    def get(self, message_id: int) -> OutboxMessage | None:
        with self.connection() as connection:
            row = connection.execute(
                "SELECT * FROM outbox WHERE message_id = ?",
                (message_id,),
            ).fetchone()
        return None if row is None else self._message_from_row(row)

    def get_by_idempotency_key(self, idempotency_key: str) -> OutboxMessage | None:
        with self.connection() as connection:
            row = connection.execute(
                "SELECT * FROM outbox WHERE idempotency_key = ?",
                (idempotency_key,),
            ).fetchone()
        return None if row is None else self._message_from_row(row)

    def due(
        self,
        *,
        now: datetime | None = None,
        limit: int = 100,
    ) -> list[OutboxMessage]:
        if limit < 1:
            return []
        resolved_now = as_utc(now)
        with self.connection() as connection:
            rows = connection.execute(
                """
                SELECT * FROM outbox
                WHERE status = 'pending' AND available_at <= ?
                ORDER BY available_at, message_id
                LIMIT ?
                """,
                (datetime_text(resolved_now), limit),
            ).fetchall()
        return [self._message_from_row(row) for row in rows]

    list_due = due

    def mark_sent(
        self,
        message_id: int,
        *,
        sent_at: datetime | None = None,
    ) -> OutboxMessage:
        resolved_sent_at = as_utc(sent_at)
        with self.transaction() as connection:
            row = connection.execute(
                "SELECT * FROM outbox WHERE message_id = ?",
                (message_id,),
            ).fetchone()
            if row is None:
                raise RecordNotFoundError(f"Outbox message {message_id} does not exist")
            current = self._message_from_row(row)
            if current.status == "sent":
                return current
            connection.execute(
                """
                UPDATE outbox
                SET status = 'sent', sent_at = ?, updated_at = ?, last_error = NULL
                WHERE message_id = ?
                """,
                (
                    datetime_text(resolved_sent_at),
                    datetime_text(resolved_sent_at),
                    message_id,
                ),
            )
        updated = self.get(message_id)
        assert updated is not None
        return updated

    def mark_failed(
        self,
        message_id: int,
        error: str,
        *,
        retry_at: datetime | None = None,
        max_attempts: int | None = None,
    ) -> OutboxMessage:
        if max_attempts is not None and max_attempts < 1:
            raise ValueError("max_attempts must be positive")
        now = utc_now()
        next_attempt = as_utc(retry_at)
        with self.transaction() as connection:
            row = connection.execute(
                "SELECT * FROM outbox WHERE message_id = ?",
                (message_id,),
            ).fetchone()
            if row is None:
                raise RecordNotFoundError(f"Outbox message {message_id} does not exist")
            current = self._message_from_row(row)
            if current.status == "sent":
                raise IdempotencyConflictError(f"Outbox message {message_id} was already sent")
            attempts = current.attempts + 1
            status = "dead" if max_attempts is not None and attempts >= max_attempts else "pending"
            connection.execute(
                """
                UPDATE outbox
                SET status = ?, attempts = ?, available_at = ?, updated_at = ?,
                    last_error = ?
                WHERE message_id = ?
                """,
                (
                    status,
                    attempts,
                    datetime_text(next_attempt),
                    datetime_text(now),
                    error[:2_000],
                    message_id,
                ),
            )
        updated = self.get(message_id)
        assert updated is not None
        return updated

    @staticmethod
    def _message_from_row(row: sqlite3.Row) -> OutboxMessage:
        return OutboxMessage(
            message_id=row["message_id"],
            idempotency_key=row["idempotency_key"],
            topic=row["topic"],
            payload=json_loads(row["payload_json"]),
            status=row["status"],
            attempts=row["attempts"],
            available_at=parse_datetime(row["available_at"]),
            created_at=parse_datetime(row["created_at"]),
            updated_at=parse_datetime(row["updated_at"]),
            sent_at=None if row["sent_at"] is None else parse_datetime(row["sent_at"]),
            last_error=row["last_error"],
        )

    async def aenqueue(
        self,
        idempotency_key: str,
        payload: Any,
        *,
        topic: str = "performance.plan",
        available_at: datetime | None = None,
    ) -> OutboxMessage:
        operation = partial(
            self.enqueue,
            idempotency_key,
            payload,
            topic=topic,
            available_at=available_at,
        )
        return await asyncio.to_thread(operation)

    async def adue(
        self,
        *,
        now: datetime | None = None,
        limit: int = 100,
    ) -> list[OutboxMessage]:
        operation = partial(self.due, now=now, limit=limit)
        return await asyncio.to_thread(operation)

    async def amark_sent(self, message_id: int) -> OutboxMessage:
        return await asyncio.to_thread(self.mark_sent, message_id)

    async def amark_failed(
        self,
        message_id: int,
        error: str,
        *,
        retry_at: datetime | None = None,
        max_attempts: int | None = None,
    ) -> OutboxMessage:
        operation = partial(
            self.mark_failed,
            message_id,
            error,
            retry_at=retry_at,
            max_attempts=max_attempts,
        )
        return await asyncio.to_thread(operation)
