from __future__ import annotations

import pytest

from npc_director.context import HistoryKind, LongTermMemory
from npc_director.contracts import NPCDomainState
from npc_director.contracts.episodes import DialogueEvent, DialogueState
from npc_director.orchestration.context_adapter import DefaultContextBuilder
from npc_director.state.episode_store import EpisodeStore
from npc_director.state.memory_store import LongTermMemoryStore
from tests.test_episode_service import request


def memory(identifier, content, *, session="game-a", npc="elder_maren", importance=0.8):
    return LongTermMemory(
        memory_id=identifier,
        npc_id=npc,
        content=content,
        kinds=(HistoryKind.COMMITMENT,),
        source_session_id=session,
        source_turn_ids=("earlier-turn",),
        importance=importance,
    )


def add_noise(store):
    for i in range(12):
        item = memory(f"clothing-{i}", f"玩家选择了第 {i} 件衣服。", importance=0.95)
        store.add(item, session_id="game-a")


@pytest.mark.asyncio
async def test_scoped_search_finds_older_relevant_memory_and_preserves_provenance(tmp_path):
    store = LongTermMemoryStore(tmp_path / "state.db")
    relevant = memory("wrench", "我答应把旧矿井的扳手放进工具箱。")
    store.add(relevant, session_id="game-a")
    add_noise(store)
    other_instance = memory("wrench", "扳手在另一个世界的密室。", session="game-b", importance=1)
    other_npc = memory(
        "private-wrench", "扳手在守卫的秘密夹层。", npc="village_guard", importance=1
    )
    store.add(other_instance, session_id="game-b")
    store.add(other_npc, session_id="game-a")
    assert relevant not in store.list_for_npc("elder_maren", session_id="game-a", limit=12)

    found = await store.asearch_for_npc("elder_maren", "旧矿井 扳手", session_id="game-a")
    assert found == [relevant]
    assert found[0].kinds == (HistoryKind.COMMITMENT,)
    assert found[0].source_turn_ids == ("earlier-turn",)
    assert store.search_for_npc("elder_maren", "扳手", session_id="missing-instance") == []
    assert store.search_for_npc("unknown-npc", "扳手", session_id="game-a") == []
    assert store.search_for_npc("elder_maren", "独角鲸", session_id="game-a") == []


@pytest.mark.parametrize("memory_has_speaker", [False, True])
@pytest.mark.asyncio
async def test_context_queries_topic_keeps_raw_history_and_deduplicates_memories(
    tmp_path, memory_has_speaker
):
    database = tmp_path / "state.db"
    store = LongTermMemoryStore(database)
    episodes = EpisodeStore(database)
    relevant = memory("wrench", "我答应把旧矿井的扳手放进工具箱。")
    store.add(relevant, session_id="game-a")
    add_noise(store)
    recent_text = "我答应检查旧矿井的扳手。"
    duplicate = memory(
        "recent-wrench",
        f"village_guard: {recent_text}" if memory_has_speaker else recent_text,
        importance=1,
    )
    store.add(duplicate, session_id="game-a")
    for i in range(15):
        episodes.record_dialogue(
            DialogueEvent(
                event_id=f"visible-{i}",
                session_id="game-a",
                turn_id=f"turn-{i}",
                speaker_id="village_guard",
                audience=["elder_maren"],
                text=recent_text if i == 14 else f"visible text {i}",
            )
        )
    for i in range(15):
        episodes.record_dialogue(
            DialogueEvent(
                event_id=f"private-{i}",
                session_id="game-a",
                turn_id=f"private-turn-{i}",
                speaker_id="herbalist_iona",
                audience=["village_guard"],
                text=f"private text {i}",
            )
        )
    episodes.save_dialogue_state(
        DialogueState(session_id="game-a", npc_id="elder_maren", topic="旧矿井 扳手")
    )
    builder = DefaultContextBuilder(memory_reader=store, conversation_reader=episodes)
    built = await builder.build(
        request(session="game-a", text="那东西到底在哪？"), NPCDomainState(npc_id="elder_maren")
    )
    actor = built.snapshot["director"]["actor_context"]
    expected_history = [f"village_guard: visible text {i}" for i in range(3, 14)]
    expected_history.append(f"village_guard: {recent_text}")
    assert actor["recent_dialogue"] == expected_history
    assert all(isinstance(line, str) for line in actor["recent_dialogue"])
    assert actor["long_term_memories"] == [
        {
            "memory_id": relevant.memory_id,
            "npc_id": relevant.npc_id,
            "content": relevant.content,
            "kinds": ["commitment"],
            "source_session_id": "game-a",
            "source_turn_ids": ["earlier-turn"],
            "importance": 0.8,
        }
    ]
    assert built.snapshot["memory_refs"] == [relevant.memory_id]
    assert relevant.content not in built.director_input.history_summary


@pytest.mark.asyncio
async def test_scoped_context_limits_relevant_memory_injection(tmp_path):
    database = tmp_path / "state.db"
    store = LongTermMemoryStore(database)
    for i in range(6):
        store.add(memory(f"wrench-{i}", f"扳手线索 {i}。"), session_id="game-a")
    builder = DefaultContextBuilder(memory_reader=store, conversation_reader=EpisodeStore(database))
    built = await builder.build(
        request(session="game-a", text="扳手在哪？"), NPCDomainState(npc_id="elder_maren")
    )
    assert len(built.director_input.actor_context["long_term_memories"]) == 4
    assert len(built.snapshot["memory_refs"]) == 4


@pytest.mark.parametrize("scoped", [False, True])
@pytest.mark.asyncio
async def test_list_only_memory_reader_remains_compatible(tmp_path, scoped):
    relevant = memory("old-promise", "我答应归还旧矿井的扳手。")

    class ListOnlyReader:
        def __init__(self):
            self.calls = []

        async def alist_for_npc(self, npc_id, *, limit=20, session_id=None):
            self.calls.append((npc_id, limit, session_id))
            return [relevant]

    reader = ListOnlyReader()
    builder = DefaultContextBuilder(
        memory_reader=reader,
        conversation_reader=EpisodeStore(tmp_path / "state.db") if scoped else None,
    )
    built = await builder.build(
        request(session="game-a", text="扳手在哪？"), NPCDomainState(npc_id="elder_maren")
    )
    assert reader.calls == [("elder_maren", 12, "game-a" if scoped else None)]
    assert built.snapshot["memory_refs"] == [relevant.memory_id]
    if scoped:
        recalled = built.director_input.actor_context["long_term_memories"]
        assert recalled[0]["content"] == relevant.content
        assert relevant.content not in built.director_input.history_summary
    else:
        assert relevant.content in built.director_input.history_summary
        assert "long_term_memories" not in built.director_input.actor_context
