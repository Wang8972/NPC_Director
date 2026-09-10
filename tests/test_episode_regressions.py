from __future__ import annotations

import pytest

from npc_director.contracts import EngineEmitReceipt, TurnStatus
from npc_director.contracts.planning import (
    ExecutionTrace,
    QualityIssue,
    QualityVerdict,
    TurnAnalysis,
)
from npc_director.unity_adapter.base import build_idempotency_key
from tests.test_bounded_executor import RecordingRetriever, dialogue, director_input
from tests.test_content_review import reviewed
from tests.test_dynamic_planning import QUALITY, WRITER, make_executor, successful_outputs
from tests.test_episode_service import Adapter, make_service, request


@pytest.mark.asyncio
async def test_cancelled_queued_delivery_is_never_replayed(tmp_path):
    service, _ = make_service(tmp_path)

    class QueuedAdapter(Adapter):
        async def emit(self, directive):
            self.directives.append(directive)
            return EngineEmitReceipt(
                turn_id=directive.turn_id,
                idempotency_key=build_idempotency_key(directive),
                status="queued",
            )

    queued = QueuedAdapter()
    result = await service.run_turn(request(), adapter=queued)
    episode = service.episodes.episode_for_turn(result.turn_id)
    await service.cancel_episode(episode.id)
    connected = Adapter()
    assert await service.dispatch_outbox(connected, session_id="session-v2") == 0
    assert connected.directives == []
    assert service.turn_store.get(result.turn_id).status is TurnStatus.INTERRUPTED
    next_result = await service.run_turn(request(turn="next"), adapter=connected)
    assert next_result.status is TurnStatus.READY_TO_EMIT


@pytest.mark.asyncio
async def test_preemption_releases_pending_content_and_same_goal_can_be_proposed_again(tmp_path):
    service, fixture = make_service(tmp_path)
    adapter = Adapter()
    saved = []

    class PendingContent:
        async def generate(self, source, *, repair_feedback=None):
            content = reviewed()
            content.policy = content.policy.model_copy(
                update={
                    "session_id": source.session_id,
                    "npc_id": source.npc_id,
                }
            )
            service.episodes.content_store.stage_reviewed(
                source.session_id,
                source.episode_id,
                source.turn_id,
                source.npc_id,
                content,
            )
            saved.append(content)
            result = await fixture.generate(source)
            result.proposal.performance.confidence = 0.1
            return result

    service.executor = PendingContent()
    old = await service.run_turn(request(turn="old-content"), adapter=adapter)
    assert old.status is TurnStatus.PENDING_APPROVAL
    service.executor = fixture
    new = await service.run_turn(request(turn="new-content"), adapter=adapter)
    store = service.episodes.content_store
    assert store.get_staged_for_turn("session-v2", old.turn_id) == []
    new_episode = service.episodes.episode_for_turn(new.turn_id)
    staged = store.stage_reviewed(
        "session-v2", new_episode.id, new.turn_id, "elder_maren", saved[0]
    )
    assert staged.status == "staged"


@pytest.mark.asyncio
async def test_unused_search_hits_are_not_automatically_cited():
    analysis = TurnAnalysis(
        intent="lore_question",
        objective="承认今日记录未知",
        needs_lore=True,
        lore_queries=["今日值守"],
    )
    outputs = successful_outputs(analysis)
    outputs[WRITER] = dialogue("没有今日的记录，我得先去核实。")
    executor, _ = make_executor(outputs, retriever=RecordingRetriever())
    result = await executor.generate(director_input())
    assert result.execution_trace.stop_reason == "completed"
    assert result.lore_refs_accessed
    assert result.proposal.performance.evidence.lore_refs == []
    assert result.proposal.plan.lore_queries == []


@pytest.mark.asyncio
async def test_nonblocking_style_feedback_does_not_replace_valid_dialogue():
    outputs = successful_outputs(TurnAnalysis(intent="greeting", objective="回应问候"))
    outputs[QUALITY] = QualityVerdict(
        passed=False,
        naturalness=3,
        persona_consistency=4,
        response_coverage=5,
        issues=[
            QualityIssue(
                target="dialogue",
                code="style_preference",
                explanation="可以稍短，但内容准确且符合角色。",
                blocking=False,
            )
        ],
    )
    executor, _ = make_executor(outputs)
    result = await executor.generate(director_input())
    assert result.execution_trace.stop_reason == "completed"
    assert result.proposal.performance.dialogue.text == outputs[WRITER].dialogue.text


@pytest.mark.asyncio
async def test_reviewed_readonly_uncertainty_can_be_spoken_without_approval(tmp_path):
    service, fixture = make_service(tmp_path)

    class ReviewedUnknown:
        async def generate(self, source, *, repair_feedback=None):
            result = await fixture.generate(source)
            result.proposal.performance.confidence = 0.1
            result.execution_trace = ExecutionTrace(
                quality=QualityVerdict(
                    passed=True, naturalness=4, persona_consistency=4, response_coverage=4
                )
            )
            return result

    service.executor = ReviewedUnknown()
    result = await service.run_turn(request(text="你知道吗？"), adapter=Adapter())
    assert result.status is TurnStatus.READY_TO_EMIT
    assert result.approval_id is None
