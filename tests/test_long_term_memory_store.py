from pathlib import Path

import pytest

from npc_director.context import HistoryKind, LongTermMemory
from npc_director.state import LongTermMemoryStore


@pytest.mark.asyncio
async def test_long_term_memory_store_is_durable_and_idempotent(tmp_path: Path) -> None:
    database = tmp_path / "state.db"
    memory = LongTermMemory(
        memory_id="memory:promise",
        npc_id="elder_maren",
        content="玩家承诺会护送药师去北岭。",
        kinds=(HistoryKind.COMMITMENT, HistoryKind.PLAYER_CHOICE),
        source_session_id="s1",
        source_turn_ids=("s1:1",),
        importance=0.9,
    )
    store = LongTermMemoryStore(database)

    assert await store.aadd_many([memory]) == 1
    assert await store.aadd_many([memory]) == 0
    reopened = LongTermMemoryStore(database)
    loaded = await reopened.alist_for_npc("elder_maren")

    assert loaded == [memory]
