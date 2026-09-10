from __future__ import annotations

import asyncio
import json
import sqlite3
from pathlib import Path

from npc_director.context import HistoryKind, LongTermMemory
from npc_director.rag.index import LexicalLoreIndex, LoreDocument
from npc_director.state._sqlite import SQLiteStore, datetime_text

_SEARCH_CANDIDATE_LIMIT = 256


class LongTermMemoryStore(SQLiteStore):
    def __init__(self, database: str | Path) -> None:
        super().__init__(database)

    def add(self, memory: LongTermMemory, *, session_id: str | None = None) -> bool:
        if session_id is not None:
            if not session_id.strip() or memory.source_session_id != session_id:
                raise ValueError("scoped memory must belong to its source session")
            with self.transaction() as connection:
                cursor = connection.execute(
                    """
                    INSERT OR IGNORE INTO scoped_long_term_memories
                        (session_id, memory_id, npc_id, source_session_id, content, kinds_json,
                         source_turn_ids_json, importance, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        session_id,
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

    def add_many(
        self,
        memories: list[LongTermMemory] | tuple[LongTermMemory, ...],
        *,
        session_id: str | None = None,
    ) -> int:
        return sum(self.add(memory, session_id=session_id) for memory in memories)

    def list_for_npc(
        self,
        npc_id: str,
        *,
        limit: int = 20,
        session_id: str | None = None,
    ) -> list[LongTermMemory]:
        if limit < 1:
            return []
        if session_id is not None:
            if not session_id.strip():
                raise ValueError("session_id must not be blank")
            with self.connection() as connection:
                rows = connection.execute(
                    """SELECT * FROM scoped_long_term_memories
                    WHERE session_id = ? AND npc_id = ?
                    ORDER BY importance DESC, created_at DESC, memory_id LIMIT ?""",
                    (session_id, npc_id, limit),
                ).fetchall()
            return [self._from_row(row) for row in rows]
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
        *,
        session_id: str | None = None,
    ) -> int:
        return await asyncio.to_thread(self.add_many, memories, session_id=session_id)

    def search_for_npc(
        self,
        npc_id: str,
        query: str,
        *,
        limit: int = 12,
        session_id: str | None = None,
    ) -> list[LongTermMemory]:
        """Rank a bounded, already scoped memory pool by lexical relevance."""
        if limit < 1:
            return []
        candidates = self.list_for_npc(
            npc_id, limit=_SEARCH_CANDIDATE_LIMIT, session_id=session_id
        )
        if not candidates or not query.strip():
            return candidates[:limit]
        by_id = {memory.memory_id: memory for memory in candidates}
        positions = {memory.memory_id: index for index, memory in enumerate(candidates)}
        index = LexicalLoreIndex(
            LoreDocument(ref=memory.memory_id, text=memory.content)
            for memory in candidates
            if memory.content.strip()
        )
        hits = sorted(
            index.search(query, top_k=_SEARCH_CANDIDATE_LIMIT),
            key=lambda hit: (
                -hit.score,
                -by_id[hit.ref].importance,
                positions[hit.ref],
            ),
        )
        # Return the original records so turn/session provenance survives retrieval.
        return [by_id[hit.ref] for hit in hits[:limit]]

    async def asearch_for_npc(
        self,
        npc_id: str,
        query: str,
        *,
        limit: int = 12,
        session_id: str | None = None,
    ) -> list[LongTermMemory]:
        return await asyncio.to_thread(
            self.search_for_npc, npc_id, query, limit=limit, session_id=session_id
        )

    async def alist_for_npc(
        self,
        npc_id: str,
        *,
        limit: int = 20,
        session_id: str | None = None,
    ) -> list[LongTermMemory]:
        return await asyncio.to_thread(
            self.list_for_npc, npc_id, limit=limit, session_id=session_id
        )

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
