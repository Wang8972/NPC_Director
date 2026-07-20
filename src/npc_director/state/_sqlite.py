from __future__ import annotations

import json
import sqlite3
import threading
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

SCHEMA = """
CREATE TABLE IF NOT EXISTS npc_domain_states (
    npc_id TEXT PRIMARY KEY,
    state_json TEXT NOT NULL,
    version INTEGER NOT NULL CHECK (version >= 0),
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS state_commits (
    turn_id TEXT PRIMARY KEY,
    npc_id TEXT NOT NULL,
    patch_hash TEXT NOT NULL,
    expected_version INTEGER NOT NULL,
    resulting_version INTEGER NOT NULL,
    state_json TEXT NOT NULL,
    committed_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_state_commits_npc
ON state_commits (npc_id, committed_at);

CREATE TABLE IF NOT EXISTS turns (
    turn_id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL,
    npc_id TEXT NOT NULL,
    status TEXT NOT NULL,
    record_json TEXT NOT NULL,
    revision INTEGER NOT NULL DEFAULT 0 CHECK (revision >= 0),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_turns_session
ON turns (session_id, created_at);

CREATE INDEX IF NOT EXISTS idx_turns_status
ON turns (status, updated_at);

CREATE TABLE IF NOT EXISTS event_log (
    sequence INTEGER PRIMARY KEY AUTOINCREMENT,
    event_key TEXT NOT NULL UNIQUE,
    session_id TEXT NOT NULL,
    turn_id TEXT NOT NULL,
    idempotency_key TEXT NOT NULL,
    event_type TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    occurred_at TEXT NOT NULL,
    recorded_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_event_log_turn
ON event_log (turn_id, sequence);

CREATE TABLE IF NOT EXISTS approvals (
    approval_id TEXT PRIMARY KEY,
    turn_id TEXT NOT NULL,
    status TEXT NOT NULL,
    record_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    resolved_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_approvals_turn
ON approvals (turn_id, created_at);

CREATE INDEX IF NOT EXISTS idx_approvals_status
ON approvals (status, created_at);

CREATE TABLE IF NOT EXISTS outbox (
    message_id INTEGER PRIMARY KEY AUTOINCREMENT,
    idempotency_key TEXT NOT NULL UNIQUE,
    topic TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    status TEXT NOT NULL,
    attempts INTEGER NOT NULL DEFAULT 0 CHECK (attempts >= 0),
    available_at TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    sent_at TEXT,
    last_error TEXT
);

CREATE INDEX IF NOT EXISTS idx_outbox_due
ON outbox (status, available_at, message_id);

CREATE TABLE IF NOT EXISTS long_term_memories (
    memory_id TEXT PRIMARY KEY,
    npc_id TEXT NOT NULL,
    session_id TEXT NOT NULL,
    content TEXT NOT NULL,
    kinds_json TEXT NOT NULL,
    source_turn_ids_json TEXT NOT NULL,
    importance REAL NOT NULL,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_long_term_memories_npc
ON long_term_memories (npc_id, importance DESC, created_at);
"""

_SCHEMA_LOCKS: dict[str, threading.Lock] = {}
_SCHEMA_LOCKS_GUARD = threading.Lock()


def utc_now() -> datetime:
    return datetime.now(UTC)


def as_utc(value: datetime | None = None) -> datetime:
    resolved = value or utc_now()
    if resolved.tzinfo is None:
        return resolved.replace(tzinfo=UTC)
    return resolved.astimezone(UTC)


def datetime_text(value: datetime | None = None) -> str:
    return as_utc(value).isoformat()


def parse_datetime(value: str) -> datetime:
    return as_utc(datetime.fromisoformat(value))


def json_dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def json_loads(value: str) -> Any:
    return json.loads(value)


class SQLiteStore:
    """Small connection-per-operation SQLite base safe for worker threads."""

    def __init__(self, database: str | Path) -> None:
        raw_database = str(database)
        self._anchor: sqlite3.Connection | None = None
        if raw_database == ":memory:":
            token = uuid.uuid4().hex
            self.database = f"file:npc_director_{token}?mode=memory&cache=shared"
            self._uri = True
            self._anchor = self._new_connection()
        elif raw_database.startswith("file:"):
            self.database = raw_database
            self._uri = True
            if "mode=memory" in raw_database:
                self._anchor = self._new_connection()
        else:
            path = Path(raw_database).expanduser().resolve()
            path.parent.mkdir(parents=True, exist_ok=True)
            self.database = str(path)
            self._uri = False
        self._initialize_schema()

    def _new_connection(self) -> sqlite3.Connection:
        connection = sqlite3.connect(
            self.database,
            timeout=10,
            isolation_level=None,
            check_same_thread=False,
            uri=self._uri,
        )
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 10000")
        return connection

    def _initialize_schema(self) -> None:
        with _SCHEMA_LOCKS_GUARD:
            lock = _SCHEMA_LOCKS.setdefault(self.database, threading.Lock())
        with lock:
            connection = self._new_connection()
            try:
                connection.execute("PRAGMA journal_mode = WAL")
                connection.execute("PRAGMA synchronous = NORMAL")
                connection.executescript(SCHEMA)
            finally:
                connection.close()

    @contextmanager
    def connection(self) -> Iterator[sqlite3.Connection]:
        connection = self._new_connection()
        try:
            yield connection
        finally:
            connection.close()

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        connection = self._new_connection()
        try:
            connection.execute("BEGIN IMMEDIATE")
            yield connection
            connection.commit()
        except BaseException:
            connection.rollback()
            raise
        finally:
            connection.close()

    def close(self) -> None:
        if self._anchor is not None:
            self._anchor.close()
            self._anchor = None

    def __enter__(self) -> SQLiteStore:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()
