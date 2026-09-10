from __future__ import annotations

import json

import pytest

from npc_director.agents.router import build_semantic_router_agent
from npc_director.config import Settings
from npc_director.contracts.planning import (
    CollaborationRequest,
    KnowledgeNeed,
    NegotiationOutcome,
    OperationRequest,
    QualityIssue,
    QualityVerdict,
    SpeechAct,
    TurnAnalysis,
    TurnGoal,
)
from npc_director.orchestration.assembler import compile_execution_plan
from npc_director.orchestration.bounded_executor import BoundedDirectorExecutor, TypedModelCall
from tests.test_bounded_executor import (
    NARRATIVE,
    NEGOTIATOR,
    PERFORMANCE,
    ROUTER,
    WRITER,
    RecordingRetriever,
    dialogue,
    director_input,
    narrative,
    performance,
)

QUALITY = object()


def make_executor(outputs, *, retriever=None, provider=None):
    calls = []

    async def runner(agent, payload, output_type):
        calls.append((agent, payload, output_type))
        value = outputs[agent]
        if isinstance(value, list):
            value = value.pop(0)
        return TypedModelCall(output=value, input_tokens=10, output_tokens=5, total_tokens=15)

    executor = BoundedDirectorExecutor(
        Settings(model="test-model"),
        lore_retriever=retriever,
        router_factory=lambda _: ROUTER,
        narrative_factory=lambda _: NARRATIVE,
        screenwriter_factory=lambda _: WRITER,
        performance_factory=lambda _: PERFORMANCE,
        negotiator_factory=lambda _: NEGOTIATOR,
        quality_factory=lambda _: QUALITY,
        typed_runner=runner,
        budget_provider=provider,
    )
    return executor, calls


def successful_outputs(analysis):
    return {
        ROUTER: analysis,
        NARRATIVE: narrative(),
        WRITER: dialogue(),
        PERFORMANCE: performance(),
        QUALITY: QualityVerdict(passed=True),
    }


def test_default_router_emits_analysis_and_invalid_dependency_graph_is_rejected():
    assert build_semantic_router_agent(Settings()).output_type is TurnAnalysis
    analysis = TurnAnalysis(
        intent="other",
        objective="双目标",
        operations=[
            OperationRequest(id="a", kind="narrative", depends_on=["b"]),
            OperationRequest(id="b", kind="negotiate", depends_on=["a"]),
        ],
    )
    with pytest.raises(ValueError, match="cycle"):
        compile_execution_plan(analysis)


@pytest.mark.asyncio
async def test_compound_request_lore_precedes_planning_and_negotiation_returns():
    analysis = TurnAnalysis(
        intent="negotiation",
        objective="先核实战争日期，再协商护送报酬",
        confidence=1,
        needs_lore=True,
        needs_narrative=True,
        negotiation=True,
        lore_queries=["灰烬战争结束时间"],
        speech_acts=[
            SpeechAct(kind="question", meaning="哪年结束"),
            SpeechAct(kind="negotiate", meaning="护送要三十银币"),
        ],
        goals=[
            TurnGoal(id="date", description="核实时间"),
            TurnGoal(id="fee", description="协商报酬", depends_on=["date"]),
        ],
    )
    outputs = successful_outputs(analysis)
    outputs[NEGOTIATOR] = NegotiationOutcome(
        status="counteroffer",
        terms=["最多二十银币"],
        response_obligations=["解释预算"],
    )
    executor, calls = make_executor(outputs, retriever=RecordingRetriever())
    result = await executor.generate(director_input())
    assert result.execution_trace.stop_reason == "completed"
    assert result.handoffs == []
    assert NEGOTIATOR in [call[0] for call in calls]
    assert calls[-1][0] is QUALITY
    narrative_payload = next(payload for actor, payload, _ in calls if actor is NARRATIVE)
    assert "灰烬战争在二十年前结束" in narrative_payload
    assert "护送要三十银币" in narrative_payload
    assert "玩家刚抵达灰港" in narrative_payload
    writer_payload = next(payload for actor, payload, _ in calls if actor is WRITER)
    assert "最多二十银币" in writer_payload
    assert "引用公开记录" in writer_payload
    assert result.proposal.plan.proposed_state_changes.quests == []
    assert result.execution_trace.model_calls == len(calls)


@pytest.mark.asyncio
async def test_dialogue_quality_repair_reuses_all_source_artifacts():
    analysis = TurnAnalysis(
        intent="critical_choice",
        objective="根据证据选择",
        needs_lore=True,
        needs_narrative=True,
        lore_queries=["灰烬战争结束时间"],
    )
    outputs = successful_outputs(analysis)
    outputs[WRITER] = [dialogue("权限规定不允许。"), dialogue("这份记录还不够，我得再核实。")]
    outputs[QUALITY] = [
        QualityVerdict(
            passed=False,
            issues=[
                QualityIssue(
                    target="dialogue",
                    code="mechanical",
                    explanation="用角色语言解释具体缺口。",
                )
            ],
        ),
        QualityVerdict(passed=True),
    ]
    retriever = RecordingRetriever()
    executor, calls = make_executor(outputs, retriever=retriever)
    result = await executor.generate(director_input())
    actors = [call[0] for call in calls]
    assert actors.count(ROUTER) == actors.count(NARRATIVE) == len(retriever.calls) == 1
    assert actors.count(WRITER) == actors.count(PERFORMANCE) == actors.count(QUALITY) == 2
    assert result.execution_trace.repairs == 1
    assert result.proposal.performance.dialogue.text == "这份记录还不够，我得再核实。"


@pytest.mark.asyncio
async def test_cue_repair_does_not_rewrite_dialogue():
    outputs = successful_outputs(TurnAnalysis(intent="greeting", objective="回应问候"))
    outputs[QUALITY] = [
        QualityVerdict(
            passed=False,
            issues=[
                QualityIssue(
                    target="performance",
                    code="cue_mismatch",
                    explanation="动作与本句语气协调。",
                )
            ],
        ),
        QualityVerdict(passed=True),
    ]
    executor, calls = make_executor(outputs)
    result = await executor.generate(director_input())
    assert [call[0] for call in calls].count(WRITER) == 1
    assert [call[0] for call in calls].count(PERFORMANCE) == 2
    assert result.execution_trace.quality.passed


@pytest.mark.asyncio
async def test_failed_quality_stops_after_one_local_repair():
    outputs = successful_outputs(TurnAnalysis(intent="other", objective="回应"))
    outputs[QUALITY] = QualityVerdict(
        passed=False,
        naturalness=1,
        issues=[
            QualityIssue(
                target="dialogue",
                code="ooc",
                explanation="不能复述错误码。",
            )
        ],
    )
    executor, calls = make_executor(outputs)
    result = await executor.generate(director_input())
    assert result.execution_trace.stop_reason == "quality_failed"
    assert [call[0] for call in calls].count(WRITER) == 2
    assert result.proposal.plan.proposed_state_changes.flags == []


@pytest.mark.asyncio
async def test_unknown_fact_triggers_bounded_replan_without_false_clarification():
    first = TurnAnalysis(
        intent="lore_question",
        objective="查年代",
        needs_lore=True,
        knowledge_needs=[KnowledgeNeed(question="年代?", kind="fact_unknown")],
    )
    second = first.model_copy(update={"objective": "承认目前没有年代证据"})
    outputs = successful_outputs(first)
    outputs[ROUTER] = [first, second]
    executor, calls = make_executor(outputs)
    result = await executor.generate(director_input())
    assert [call[0] for call in calls].count(ROUTER) == 2
    assert result.execution_trace.revisions == 1
    assert result.proposal.plan.intent.value == "lore_question"
    assert result.routing_trace.advisory_only


@pytest.mark.asyncio
async def test_episode_budget_is_reserved_before_call_and_cannot_be_reset():
    class Provider:
        def __init__(self):
            self.remaining = 2
            self.roles = []

        async def reserve_model_call(self, episode_id, *, operation_id, role, **kwargs):
            if not self.remaining:
                return False
            self.remaining -= 1
            self.roles.append(role)
            return True

        async def record_model_usage(self, *args, **kwargs):
            pass

    provider = Provider()
    executor, calls = make_executor(
        successful_outputs(TurnAnalysis(intent="greeting", objective="欢迎")), provider=provider
    )
    source = director_input().model_copy(update={"episode_id": "episode"})
    result = await executor.generate(source)
    assert len(calls) == 2
    assert result.execution_trace.stop_reason == "budget_exhausted"
    assert result.execution_trace.model_calls == 2
    again = await executor.generate(source)
    assert len(calls) == 2
    assert again.execution_trace.model_calls == 0


@pytest.mark.asyncio
async def test_collaboration_requires_registered_actor_and_writer_receives_message():
    valid = CollaborationRequest(
        target_npc_id="lia", purpose="询问诊断", text="莉娅，查出故障了吗？"
    )
    invalid = CollaborationRequest(target_npc_id="invented", purpose="擅造角色", text="帮我开门。")
    analysis = TurnAnalysis(
        intent="other", objective="合作查故障", collaboration_requests=[valid, invalid]
    )
    executor, calls = make_executor(successful_outputs(analysis))
    source = director_input().model_copy(update={"actor_registry": [{"npc_id": "lia"}]})
    result = await executor.generate(source)
    assert result.collaboration_messages == [valid]
    assert result.execution_trace.stop_reason == "waiting_for_npc"
    payload = next(value for actor, value, _ in calls if actor is WRITER)
    assert "莉娅，查出故障了吗" in payload
    assert "pending_collaborations" in payload


@pytest.mark.asyncio
async def test_external_lore_repair_retrieves_again_but_dialogue_repair_does_not():
    analysis = TurnAnalysis(
        intent="lore_question",
        objective="答日期",
        needs_lore=True,
        lore_queries=["灰烬战争结束时间"],
    )
    retriever = RecordingRetriever()
    executor, calls = make_executor(successful_outputs(analysis), retriever=retriever)
    source = director_input()
    await executor.generate(source)
    await executor.generate(source, repair_feedback="persona: 更自然。")
    assert len(retriever.calls) == 1
    await executor.generate(source, repair_feedback="lore: 重新核实日期。")
    assert len(retriever.calls) == 2
    assert [call[0] for call in calls].count(ROUTER) == 1


def test_plan_retains_explicit_dependencies_and_adds_lore_dependency():
    analysis = TurnAnalysis(
        intent="other",
        objective="先问后谈",
        operations=[
            OperationRequest(id="facts", kind="lore"),
            OperationRequest(id="terms", kind="negotiate"),
            OperationRequest(id="story", kind="narrative", depends_on=["terms"]),
        ],
    )
    plan = compile_execution_plan(analysis)
    assert next(node for node in plan.nodes if node.id == "story").depends_on == ["terms", "facts"]
    assert next(node for node in plan.nodes if node.id == "terms").depends_on == ["facts"]
    assert json.loads(plan.model_dump_json())["nodes"][-1]["kind"] == "quality"


@pytest.mark.asyncio
async def test_existing_content_skips_author_entirely():
    from tests.test_content_review import candidate_bundle, policy

    need, _, _ = candidate_bundle()
    need = need.model_copy(update={"existing_content_sufficient": True})
    source = director_input()
    source = source.model_copy(
        update={
            "content_policy": policy()
            .model_copy(
                update={
                    "session_id": source.session_id,
                    "npc_id": source.npc_id,
                }
            )
            .model_dump(mode="json")
        }
    )
    analysis = TurnAnalysis(intent="other", objective="复用已有任务", content_need=need)
    executor, calls = make_executor(successful_outputs(analysis))
    result = await executor.generate(source)
    assert result.execution_trace.stop_reason == "completed"
    assert len(calls) == 4
    assert result.content_candidates == []


@pytest.mark.asyncio
async def test_reviewed_content_is_staged_before_writer_and_only_offered(tmp_path, monkeypatch):
    import npc_director.agents.content_author as author_module
    import npc_director.agents.content_reviewer as reviewer_module
    from npc_director.state.content_store import ContentStore
    from tests.test_content_review import candidate_bundle, policy

    author, reviewer = object(), object()
    monkeypatch.setattr(author_module, "build_content_author_agent", lambda _: author)
    monkeypatch.setattr(reviewer_module, "build_content_reviewer_agent", lambda _: reviewer)
    need, candidate, review = candidate_bundle()
    analysis = TurnAnalysis(
        intent="other", objective="提出独立遗物委托", content_need=need, confidence=1
    )
    outputs = successful_outputs(analysis)
    outputs.update({author: candidate, reviewer: review})
    executor, calls = make_executor(outputs)
    executor.content_store = ContentStore(tmp_path / "content.sqlite")
    original_runner = executor._typed_runner

    async def verify_frozen_before_writer(agent, payload, output_type):
        if agent is WRITER:
            with executor.content_store.connection() as connection:
                row = connection.execute(
                    "SELECT policy_frozen FROM narrative_content WHERE status='staged'"
                ).fetchone()
            assert row is not None and row["policy_frozen"] == 1
        return await original_runner(agent, payload, output_type)

    executor._typed_runner = verify_frozen_before_writer
    source = director_input()
    source = source.model_copy(
        update={
            "content_policy": policy()
            .model_copy(
                update={
                    "session_id": source.session_id,
                    "npc_id": source.npc_id,
                }
            )
            .model_dump(mode="json")
        }
    )
    result = await executor.generate(source)
    assert result.execution_trace.stop_reason == "completed"
    staged = result.content_candidates[0]
    assert staged["status"] == "staged"
    writer_input = next(payload for actor, payload, _ in calls if actor is WRITER)
    assert staged["quest_id"] in writer_input
    assert "reviewed_offer_pending_delivery" in writer_input
    assert result.proposal.plan.proposed_state_changes.quests[0].status == "offered"
    assert result.proposal.plan.proposed_state_changes.quests[0].quest_id == staged["quest_id"]
    assert executor.content_store.list_quests(source.session_id) == []


@pytest.mark.asyncio
async def test_content_revision_is_bounded_and_reviewers_are_separately_metered(monkeypatch):
    import npc_director.agents.content_author as author_module
    import npc_director.agents.content_reviewer as reviewer_module
    from tests.test_content_review import candidate_bundle, policy

    author, reviewer = object(), object()
    monkeypatch.setattr(author_module, "build_content_author_agent", lambda _: author)
    monkeypatch.setattr(reviewer_module, "build_content_reviewer_agent", lambda _: reviewer)
    need, candidate, review = candidate_bundle()
    outputs = successful_outputs(
        TurnAnalysis(intent="other", objective="修复候选", content_need=need)
    )
    outputs[author] = candidate
    outputs[reviewer] = review.model_copy(
        update={"action": "revise", "revision_instructions": "缩小范围"}
    )
    executor, calls = make_executor(outputs)
    source = director_input()
    source = source.model_copy(
        update={
            "content_policy": policy()
            .model_copy(
                update={
                    "session_id": source.session_id,
                    "npc_id": source.npc_id,
                }
            )
            .model_dump(mode="json")
        }
    )
    result = await executor.generate(source)
    assert [call[0] for call in calls].count(author) == 2
    assert [call[0] for call in calls].count(reviewer) == 2
    assert result.content_candidates == []
    assert result.execution_trace.model_calls == len(calls)
    roles = [node.role for node in result.execution_trace.nodes if node.entry_kind == "model_call"]
    assert roles.count("content_author") == roles.count("content_reviewer") == 2


@pytest.mark.asyncio
async def test_privileged_review_material_never_enters_author_repair_or_writer(
    tmp_path, monkeypatch
):
    import npc_director.agents.content_author as author_module
    import npc_director.agents.content_reviewer as reviewer_module
    from npc_director.state.content_store import ContentStore
    from tests.test_content_review import candidate_bundle, policy

    author, reviewer = object(), object()
    monkeypatch.setattr(author_module, "build_content_author_agent", lambda _: author)
    monkeypatch.setattr(reviewer_module, "build_content_reviewer_agent", lambda _: reviewer)
    need, candidate, review = candidate_bundle()
    outputs = successful_outputs(
        TurnAnalysis(intent="other", objective="提供委托", content_need=need)
    )
    outputs[author] = candidate
    outputs[reviewer] = [
        review.model_copy(
            update={"action": "revise", "revision_instructions": "SECRET_REVIEW_ONLY"}
        ),
        review,
    ]
    executor, calls = make_executor(outputs)
    executor.content_store = ContentStore(tmp_path / "content.sqlite")
    executor.review_context_provider = lambda _: {
        "canonical_facts": [{"fact_key": "hidden_truth", "statement": "SECRET_REVIEW_ONLY"}],
    }
    source = director_input()
    source = source.model_copy(
        update={
            "content_policy": policy()
            .model_copy(
                update={
                    "session_id": source.session_id,
                    "npc_id": source.npc_id,
                }
            )
            .model_dump(mode="json")
        }
    )
    result = await executor.generate(source)
    assert result.execution_trace.stop_reason == "completed"
    assert any("SECRET_REVIEW_ONLY" in text for actor, text, _ in calls if actor is reviewer)
    assert all(
        "SECRET_REVIEW_ONLY" not in text for actor, text, _ in calls if actor in {author, WRITER}
    )


@pytest.mark.asyncio
async def test_writer_owns_full_emotion_without_intent_overwrite():
    from npc_director.contracts import CoarseEmotion, PrimaryEmotion
    outputs = successful_outputs(TurnAnalysis(intent="greeting", objective="戒备地回应旧敌"))
    outputs[WRITER] = dialogue().model_copy(
        update={
            "coarse_emotion": CoarseEmotion.FEAR,
            "primary_emotion": PrimaryEmotion.WARY,
            "intensity": 0.8,
            "arousal": 0.75,
            "valence": -0.6,
        }
    )
    executor, calls = make_executor(outputs)
    result = await executor.generate(director_input())
    emotion = result.proposal.performance.emotion
    assert (
        emotion.coarse,
        emotion.primary,
        emotion.intensity,
        emotion.valence,
        emotion.arousal,
    ) == (
        "fear",
        "wary",
        0.8,
        -0.6,
        0.75,
    )
    assert '"intensity":0.8' in next(payload for actor, payload, _ in calls if actor is PERFORMANCE)
