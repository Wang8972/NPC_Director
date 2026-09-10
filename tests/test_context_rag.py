from __future__ import annotations

from pathlib import Path

import pytest

from npc_director.context import (
    ContextAudience,
    DeterministicHistoryCompactor,
    DirectorContextBuilder,
    HistoryKind,
    HistoryRecord,
    MemoryDistillationRequest,
    MemoryDistillationService,
)
from npc_director.contracts import (
    BodyAction,
    CoarseEmotion,
    Dialogue,
    FacePreset,
    Intent,
    LoreEvidenceItem,
    PrimaryEmotion,
    TurnRequest,
)
from npc_director.rag import (
    CachedLoreRetriever,
    LexicalLoreIndex,
    LexicalLoreRetriever,
    LoreRetriever,
)

LORE_ROOT = Path(__file__).parents[1] / "data" / "world" / "lore"


def make_retriever() -> LexicalLoreRetriever:
    return LexicalLoreRetriever(LexicalLoreIndex.from_directory(LORE_ROOT))


def test_local_lexical_retrieval_has_stable_citations() -> None:
    first = make_retriever().retrieve("灰烬战争 北方瞭望塔", top_k=2)
    second = make_retriever().retrieve("灰烬战争 北方瞭望塔", top_k=2)

    assert isinstance(make_retriever(), LoreRetriever)
    assert first.items
    assert first.items[0].ref == "lore:war_of_ash.public_record"
    assert [item.ref for item in first.items] == [item.ref for item in second.items]
    assert first.to_contract().items[0].ref == first.items[0].ref


def test_scope_permissions_filter_before_retrieval() -> None:
    retriever = make_retriever()

    public_result = retriever.retrieve("黑钥匙 密封证词", allowed_scopes=("public",))
    secret_result = retriever.retrieve(
        "黑钥匙 密封证词",
        allowed_scopes=("public", "secret:elder_maren"),
    )

    assert public_result.items == ()
    assert public_result.unanswered_queries == ("黑钥匙 密封证词",)
    assert [item.ref for item in secret_result.items] == ["lore:war_of_ash.sealed_testimony"]
    assert secret_result.items[0].scope == "secret:elder_maren"


def test_secret_lore_cannot_redeclare_another_scope(tmp_path: Path) -> None:
    secret_root = tmp_path / "secret" / "elder_maren"
    secret_root.mkdir(parents=True)
    (secret_root / "mis_scoped.json").write_text(
        '{"id":"secret","scope":"secret:other","text":"hidden"}',
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="stay within its path scope"):
        LexicalLoreIndex.from_directory(tmp_path)


def test_jit_retrieval_honors_character_and_token_budgets() -> None:
    result = make_retriever().retrieve(
        "灰烬战争",
        top_k=3,
        char_budget=90,
        token_budget=45,
    )

    assert result.items
    assert result.used_chars == len(result.render()) <= 90
    assert result.used_tokens <= 45
    assert result.truncated is True
    assert result.render().startswith("[lore:")


def test_ttl_cache_hits_then_expires() -> None:
    now = [100.0]
    cached = CachedLoreRetriever(
        make_retriever(),
        ttl_seconds=10,
        clock=lambda: now[0],
    )

    first = cached.retrieve("村庄 承诺")
    second = cached.retrieve("村庄 承诺")
    now[0] += 11
    third = cached.retrieve("村庄 承诺")

    assert first.cache_hit is False
    assert second.cache_hit is True
    assert third.cache_hit is False
    assert cached.stats.hits == 1
    assert cached.stats.misses == 2


def test_compaction_preserves_durable_facts_before_recent_chatter() -> None:
    history = [
        "天气很好。",
        HistoryRecord("玛伦承诺会在初霜日前打开档案。", "t2", (HistoryKind.COMMITMENT,)),
        HistoryRecord("玩家威胁守卫，双方发生冲突。", "t3", (HistoryKind.CONFLICT,)),
        HistoryRecord(
            "玩家兑现白石约定，玛伦的信任增加。",
            "t4",
            (HistoryKind.RELATIONSHIP_CHANGE,),
        ),
        HistoryRecord("玩家选择保护医师。", "t5", (HistoryKind.PLAYER_CHOICE,)),
        "玩家问现在几点。",
    ]

    compacted = DeterministicHistoryCompactor().compact(
        history,
        recent_limit=1,
        max_chars=800,
    )

    assert "玛伦承诺" in compacted.summary
    assert "发生冲突" in compacted.summary
    assert "信任增加" in compacted.summary
    assert "玩家选择" in compacted.summary
    assert "现在几点" in compacted.summary
    assert "天气很好" not in compacted.summary


def test_memory_distillation_falls_back_deterministically() -> None:
    class FailingDistiller:
        def distill(self, request: MemoryDistillationRequest):
            raise RuntimeError("model unavailable")

    history = [
        HistoryRecord("玩家承诺归还黑钥匙。", "t1", (HistoryKind.COMMITMENT,)),
        HistoryRecord("玩家选择保护医师。", "t2", (HistoryKind.PLAYER_CHOICE,)),
        "无关寒暄。",
    ]
    request = MemoryDistillationRequest(session_id="s1", npc_id="elder_maren", history=history)
    service = MemoryDistillationService(primary=FailingDistiller())

    first = service.distill(request)
    second = service.distill(request)

    assert first.fallback_used is True
    assert first.fallback_reason == "RuntimeError"
    assert len(first.memories) == 2
    assert [memory.memory_id for memory in first.memories] == [
        memory.memory_id for memory in second.memories
    ]
    assert all("寒暄" not in memory.content for memory in first.memories)


def test_context_builder_slices_specialist_fields_and_records_snapshots() -> None:
    request = TurnRequest.model_validate(
        {
            "session_id": "s1",
            "turn_id": "s1:7",
            "npc_id": "elder_maren",
            "player_input": "告诉我灰烬战争的真相。",
            "scene": {"location": "village_gate", "nearby_entities": ["guard"]},
            "character_core": "谨慎且重视承诺的长老。",
            "recent_history": ["玩家放下了白石。"],
            "world_state_summary": "灰烬战争真相仍受保护。",
        }
    )
    builder = DirectorContextBuilder()
    director = builder.build_director(
        request,
        character_style="简短、沉稳。",
        relationship_summary="信任较低。",
    )
    narrative = builder.build_narrative(
        player_intent=Intent.LORE_QUESTION,
        scene_summary="村门",
        current_quest_summary="无进行中任务",
        turn_id=request.turn_id,
    )
    lore = builder.build_lore(
        queries=("灰烬战争",),
        allowed_scopes=("public",),
        turn_id=request.turn_id,
    )
    screenwriter = builder.build_screenwriter(
        character_core=request.character_core,
        character_style="简短、沉稳。",
        narrative_objective="只说明公开记录。",
        lore_evidence=(
            LoreEvidenceItem(
                ref="lore:war_of_ash.public_record",
                excerpt="北方瞭望塔在首夜失火。",
                scope="public",
                score=0.9,
            ),
        ),
        recent_history=request.recent_history,
        player_input=request.player_input,
        turn_id=request.turn_id,
    )
    performance = builder.build_performance(
        dialogue=Dialogue(text="公开记录只写到瞭望塔失火。"),
        coarse_emotion=CoarseEmotion.NEUTRAL,
        primary_emotion=PrimaryEmotion.GUARDED,
        scene_summary="村门",
        allowed_actions=(BodyAction.IDLE,),
        allowed_faces=(FacePreset.SUSPICIOUS,),
        turn_id=request.turn_id,
    )

    assert "player_input" in director.model_fields_set
    # Legacy callers supply no text; dynamic planning passes this context explicitly.
    assert narrative.player_input == ""
    assert narrative.history_summary == ""
    assert "character_core" not in lore.model_dump()
    assert "allowed_scopes" not in screenwriter.model_dump()
    assert "player_input" not in performance.model_dump()
    assert "lore_evidence" not in performance.model_dump()
    assert [snapshot.audience for snapshot in builder.snapshots] == [
        ContextAudience.DIRECTOR,
        ContextAudience.NARRATIVE_PLANNER,
        ContextAudience.LORE,
        ContextAudience.SCREENWRITER,
        ContextAudience.PERFORMANCE,
    ]
    assert builder.snapshots[-1].payload == performance.model_dump(mode="json")
