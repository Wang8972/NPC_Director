from __future__ import annotations

import asyncio
import json
import sqlite3
from pathlib import Path

from npc_director.context import HistoryKind, LongTermMemory
from npc_director.state._sqlite import SQLiteStore, datetime_text


class LongTermMemoryStore(SQLiteStore):
    def __init__(self, database: str | Path) -> None:
        super().__init__(database)

    def add(self, memory: LongTermMemory) -> bool:
        with self.transaction() as connection:
            cursor = connection.execute(
                """
                INSERT OR IGNORE INTO long_term_memories
                    (memory_id, npc_id, session_id, content, kinds_json,
                     source_turn_ids_json, importance, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    memory.memory_id,
                    memory.npc_id,
                    memory.source_session_id,
                    memory.content,
                    json.dumps([kind.value for kind in memory.kinds]),
                    json.dumps(list(memory.source_turn_ids)),
                    memory.importance,
                    datetime_text(),
                ),
            )
        return cursor.rowcount == 1

    def add_many(self, memories: list[LongTermMemory] | tuple[LongTermMemory, ...]) -> int:
        return sum(self.add(memory) for memory in memories)

    def list_for_npc(self, npc_id: str, *, limit: int = 20) -> list[LongTermMemory]:
        with self.connection() as connection:
            rows = connection.execute(
                """
                SELECT * FROM long_term_memories
                WHERE npc_id = ?
                ORDER BY importance DESC, created_at, memory_id
                LIMIT ?
                """,
                (npc_id, limit),
            ).fetchall()
        return [self._from_row(row) for row in rows]

    async def aadd_many(
        self,
        memories: list[LongTermMemory] | tuple[LongTermMemory, ...],
    ) -> int:
        return await asyncio.to_thread(self.add_many, memories)

    async def alist_for_npc(self, npc_id: str, *, limit: int = 20) -> list[LongTermMemory]:
        return await asyncio.to_thread(self.list_for_npc, npc_id, limit=limit)

    @staticmethod
    def _from_row(row: sqlite3.Row) -> LongTermMemory:
        return LongTermMemory(
            memory_id=row["memory_id"],
            npc_id=row["npc_id"],
            content=row["content"],
            kinds=tuple(HistoryKind(value) for value in json.loads(row["kinds_json"])),
            source_session_id=row["session_id"],
            source_turn_ids=tuple(json.loads(row["source_turn_ids_json"])),
            importance=float(row["importance"]),
        )
