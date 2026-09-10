from __future__ import annotations

import pytest

from npc_director.contracts import Intent, RelationshipPatch, TurnStatus
from npc_director.contracts.episodes import KnowledgeClaim
from npc_director.contracts.planning import (
    CollaborationRequest,
    DialogueStateDelta,
    ExecutionTrace,
    OperationRequest,
    QualityVerdict,
    TurnAnalysis,
)
from npc_director.orchestration.assembler import compile_execution_plan
from tests.test_episode_service import Adapter, complete, make_service, request


def test_consultation_dependent_decisions_wait_for_delivery_and_reply():
    analysis = TurnAnalysis(
        intent="negotiation",
        objective="先收集条件，再整理方案",
        collaboration_requests=[
            CollaborationRequest(target_npc_id="village_guard", purpose="确认条件", text="条件呢？")
        ],
        operations=[
            OperationRequest(id="ask", kind="consult_npc"),
            OperationRequest(id="terms", kind="negotiate", depends_on=["ask"]),
            OperationRequest(id="story", kind="narrative", depends_on=["terms"]),
        ],
    )
    plan = compile_execution_plan(analysis)
    assert [node.id for node in plan.deferred_nodes] == ["terms", "story"]
    assert [node.kind for node in plan.nodes] == [
        "consult_npc",
        "screenwriter",
        "performance",
        "quality",
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "root_asks_both,repeat_question", [(True, False), (True, True), (False, True)]
)
async def test_coalesced_questions_are_delivered_and_caller_receives_both_replies(
    tmp_path, root_asks_both, repeat_question
):
    service, fixture = make_service(tmp_path)
    seen = []

    class Conversation:
        async def generate(self, source, *, repair_feedback=None):
            seen.append(source)
            result = await fixture.generate(source)
            targets = []
            if len(seen) == 1:
                text, targets = (
                    "艾伦，请说明记录。伊奥娜，请说明条件。",
                    ["village_guard", *(["herbalist_iona"] if root_asks_both else [])],
                )
            elif source.npc_id == "village_guard":
                text, targets = (
                    "记录确认旧路可通行。",
                    (["herbalist_iona"] if repeat_question else []),
                )
            elif source.npc_id == "herbalist_iona":
                text = "路况已收到。我需要玩家陪同，并备好草药袋。"
            else:
                text = "双方的条件已齐，可以由你决定。"
            result.proposal.performance.dialogue.text = text
            result.collaboration_messages = [
                CollaborationRequest(target_npc_id=target, purpose="说明条件", text=text)
                for target in targets
            ]
            result.dialogue_state_delta = DialogueStateDelta(
                reply_outcome="resolved",
                used_fact_refs=["route"] if source.npc_id == "village_guard" else [],
            )
            return result

    service.executor = Conversation()
    service.episodes.store.grant_knowledge(
        "session-v2",
        "village_guard",
        KnowledgeClaim(
            content_id="route",
            text="记录确认旧路可通行",
            epistemic_status="verified",
            shareable=True,
        ),
        source_event_id="setup",
    )
    adapter = Adapter()
    await service.run_turn(request(), adapter=adapter)
    for index in range(4):
        assert len(adapter.directives) == index + 1
        await complete(service, adapter.directives[index])
    assert [source.npc_id for source in seen] == [
        "elder_maren",
        "village_guard",
        "herbalist_iona",
        "elder_maren",
    ]
    assert "记录确认旧路可通行" in str(seen[2].actor_context["recent_dialogue"])
    assert "草药袋" in str(seen[3].actor_context["recent_dialogue"])
    knowledge = service.episodes.store.get_context("session-v2", "herbalist_iona")["knowledge"]
    assert (
        next(item for item in knowledge if item["content_id"] == "route")["epistemic_status"]
        == "reported"
    )
    assert len(adapter.directives) == 4


@pytest.mark.asyncio
async def test_pending_investigation_does_not_regenerate_caller_without_new_information(tmp_path):
    service, fixture = make_service(tmp_path, cooperate=True)

    class Waiting:
        async def generate(self, source, *, repair_feedback=None):
            result = await fixture.generate(source)
            result.dialogue_state_delta.reply_outcome = "pending"
            return result

    service.executor = Waiting()
    adapter = Adapter()
    await service.run_turn(request(), adapter=adapter)
    await complete(service, adapter.directives[0])
    await complete(service, adapter.directives[1])
    assert len(fixture.inputs) == len(adapter.directives) == 2
    assert (
        service.episodes.episode_for_turn(adapter.directives[0].turn_id).status
        == "waiting_for_event"
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("stateful", [False, True])
async def test_quality_review_clears_coarse_story_label_only_for_authorized_presentation(
    tmp_path, stateful
):
    service, fixture = make_service(tmp_path)

    class ReviewedChoice:
        async def generate(self, source, *, repair_feedback=None):
            result = await fixture.generate(source)
            result.proposal.plan.intent = Intent.CRITICAL_CHOICE
            if stateful:
                result.proposal.plan.proposed_state_changes.relationship = RelationshipPatch(
                    trust_delta=1
                )
            result.execution_trace = ExecutionTrace(
                quality=QualityVerdict(
                    passed=True, naturalness=4, persona_consistency=4, response_coverage=4
                )
            )
            return result

    service.executor = ReviewedChoice()
    result = await service.run_turn(request(), adapter=Adapter())
    assert result.status is TurnStatus.READY_TO_EMIT


@pytest.mark.asyncio
async def test_scoped_memory_distillation_keeps_real_source_turn_ids(tmp_path):
    service, _ = make_service(tmp_path)
    adapter = Adapter()
    incoming = request(text="我承诺等你核对记录。")
    await service.run_turn(incoming, adapter=adapter)
    await complete(service, adapter.directives[0])
    memories = service.memory_store.list_for_npc("elder_maren", session_id="session-v2")
    assert memories
    assert all(memory.source_turn_ids == (incoming.turn_id,) for memory in memories)


def test_shared_objective_version_is_independent_of_each_npc_domain_clock(tmp_path):
    from npc_director.contracts import NPCDomainState
    from npc_director.contracts.content import ObjectiveRef
    from tests.test_bounded_executor import director_input

    service, _ = make_service(tmp_path)
    for npc, version in (("elder_maren", 8), ("village_guard", 0)):
        service.domain_store.create(
            NPCDomainState(npc_id=npc, version=version, quests={"herbalist_escort": "offered"}),
            session_id="session-v2",
        )
    first = service.episodes.content_policy(request(), director_input())
    assert first.objective_refs[0].version == 0
    definition = ObjectiveRef(
        objective_id="herbalist_escort", quest_id="herbalist_escort", version=2
    )
    service.episodes.content_store.register_objective("session-v2", definition)
    second = service.episodes.content_policy(request(npc="village_guard"), director_input())
    assert second.objective_refs[0] == definition
