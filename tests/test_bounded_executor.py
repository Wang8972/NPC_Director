from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

import npc_director.orchestration.bounded_executor as bounded_module
from npc_director.config import Settings
from npc_director.contracts import (
    DialogueDraft,
    DirectorInput,
    NarrativePlan,
    PerformanceOutput,
    RouteDecision,
    SpecialistName,
    StateChangeProposal,
    TurnProposal,
)
from npc_director.orchestration.bounded_executor import (
    BoundedDirectorExecutor,
    TypedModelCall,
)
from npc_director.orchestration.executor import (
    OpenAIDirectorExecutor,
    ResilientDirectorExecutor,
)
from npc_director.rag.retriever import LoreRetrievalResult, RetrievedLoreItem

ROUTER = object()
NARRATIVE = object()
WRITER = object()
PERFORMANCE = object()
NEGOTIATOR = object()


class FakeRunResult:
    def __init__(self, output, response_id: str):
        self.final_output = output
        self.last_response_id = response_id
        self.context_wrapper = SimpleNamespace(
            usage=SimpleNamespace(input_tokens=10, output_tokens=5, total_tokens=15)
        )

    def final_output_as(self, output_type, raise_if_incorrect_type=False):
        if raise_if_incorrect_type and not isinstance(self.final_output, output_type):
            raise TypeError(f"output is not {output_type.__name__}")
        return self.final_output


class RecordingRetriever:
    def __init__(self) -> None:
        self.calls: list[tuple[object, dict]] = []

    def retrieve(self, queries, **kwargs):
        self.calls.append((queries, kwargs))
        return LoreRetrievalResult(
            items=(
                RetrievedLoreItem(
                    ref="lore:ash-war",
                    excerpt="灰烬战争在二十年前结束。",
                    scope="public",
                    score=0.9,
                    queries=("灰烬战争结束时间",),
                ),
            ),
            unanswered_queries=(),
            used_tokens=12,
            used_chars=20,
        )


def director_input(
    *,
    allowed_state_paths: list[str] | None = None,
) -> DirectorInput:
    return DirectorInput.model_validate(
        {
            "session_id": "bounded-session",
            "turn_id": "bounded-turn",
            "npc_id": "elder_maren",
            "player_input": "你好，长老。",
            "scene_summary": "村门口。",
            "character_core": "玛伦是克制的长老。",
            "history_summary": "玩家刚抵达灰港。",
            "lore_scopes": ["public"],
            "allowed_actions": ["idle"],
            "allowed_faces": ["neutral"],
            "allowed_state_paths": allowed_state_paths or [],
            "response_obligations": ["直接回应玩家"],
        }
    )


def dialogue(text: str = "欢迎来到灰港。") -> DialogueDraft:
    return DialogueDraft.model_validate(
        {
            "dialogue": {"text": text},
            "coarse_emotion": "joy",
            "primary_emotion": "warm",
        }
    )


def performance() -> PerformanceOutput:
    return PerformanceOutput.model_validate(
        {
            "performance": {
                "dialogue": {"text": "Performance 不得覆盖这句。"},
                "emotion": {"coarse": "anger", "primary": "stern"},
                "body_cues": [{"action": "step_forward"}, {"action": "idle"}],
                "face_cues": [{"preset": "angry"}, {"preset": "neutral"}],
                "confidence": 0.9,
            }
        }
    )


def narrative() -> NarrativePlan:
    return NarrativePlan.model_validate(
        {
            "objective": "说明战争记录并做出克制选择",
            "beats": [{"order": 1, "description": "引用公开记录"}],
            "proposed_state_changes": {
                "flags": [
                    {"name": "allowed_choice", "value": True},
                    {"name": "forged_choice", "value": True},
                ]
            },
        }
    )


def negotiation_proposal() -> TurnProposal:
    return TurnProposal.model_validate(
        {
            "plan": {
                "goal": "协商任务报酬",
                "intent": "negotiation",
                "required_specialists": ["baseline"],
                "proposed_state_changes": {"flags": [{"name": "forged_choice", "value": True}]},
            },
            "performance": {
                "dialogue": {"text": "最多二十枚银币。"},
                "emotion": {"coarse": "neutral", "primary": "calm"},
                "body_cues": [{"action": "step_forward"}, {"action": "idle"}],
                "face_cues": [{"preset": "angry"}, {"preset": "neutral"}],
            },
        }
    )


def build_executor(
    *,
    lore_retriever=None,
) -> BoundedDirectorExecutor:
    return BoundedDirectorExecutor(
        Settings(model="test-model"),
        lore_retriever=lore_retriever,
        router_factory=lambda _settings: ROUTER,
        narrative_factory=lambda _settings: NARRATIVE,
        screenwriter_factory=lambda _settings: WRITER,
        performance_factory=lambda _settings: PERFORMANCE,
        negotiator_factory=lambda _settings: NEGOTIATOR,
    )


def install_fake_runner(monkeypatch, outputs: dict[object, object]):
    calls: list[tuple[object, str, dict]] = []

    async def fake_run(agent, run_input, **kwargs):
        calls.append((agent, run_input, kwargs))
        return FakeRunResult(outputs[agent], f"response-{len(calls)}")

    monkeypatch.setattr(bounded_module.Runner, "run", staticmethod(fake_run))
    return calls


def test_resilient_executor_defaults_to_bounded_and_keeps_react_ablation() -> None:
    bounded = ResilientDirectorExecutor(Settings())
    react = ResilientDirectorExecutor(Settings(orchestration_mode="react"))

    assert isinstance(bounded.primary, BoundedDirectorExecutor)
    assert isinstance(react.primary, OpenAIDirectorExecutor)


@pytest.mark.asyncio
async def test_bounded_executor_supports_provider_neutral_typed_runner() -> None:
    outputs = {
        ROUTER: RouteDecision.model_validate(
            {
                "intent": "greeting",
                "objective": "回应问候",
                "confidence": 1.0,
            }
        ),
        WRITER: dialogue(),
        PERFORMANCE: performance(),
    }
    calls: list[object] = []

    async def typed_runner(agent, _run_input, _output_type):
        calls.append(agent)
        return TypedModelCall(
            output=outputs[agent],
            input_tokens=7,
            output_tokens=3,
            total_tokens=10,
            last_response_id=f"typed-{len(calls)}",
        )

    executor = BoundedDirectorExecutor(
        Settings(model="test-model"),
        router_factory=lambda _settings: ROUTER,
        narrative_factory=lambda _settings: NARRATIVE,
        screenwriter_factory=lambda _settings: WRITER,
        performance_factory=lambda _settings: PERFORMANCE,
        negotiator_factory=lambda _settings: NEGOTIATOR,
        typed_runner=typed_runner,
    )

    result = await executor.generate(director_input())

    assert calls == [ROUTER, WRITER, PERFORMANCE]
    assert result.metrics.input_tokens == 21
    assert result.metrics.output_tokens == 9
    assert result.metrics.total_tokens == 30
    assert result.response_id == "typed-3"


def test_orchestration_mode_rejects_unknown_value() -> None:
    with pytest.raises(ValueError, match="ORCHESTRATION_MODE"):
        Settings(orchestration_mode="freeform").validate()


@pytest.mark.asyncio
async def test_tampered_trusted_policy_digest_fails_closed(monkeypatch) -> None:
    calls = install_fake_runner(monkeypatch, {})
    tampered = director_input().model_copy(update={"policy_digest": "0" * 64})

    with pytest.raises(ValueError, match="policy digest"):
        await build_executor().generate(tampered)

    assert calls == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("max_tool_calls", "max_specialist_calls"),
    [(0, 4), (4, 1)],
)
async def test_insufficient_policy_budget_returns_capability_free_fallback_without_agents(
    monkeypatch,
    max_tool_calls: int,
    max_specialist_calls: int,
) -> None:
    calls = install_fake_runner(monkeypatch, {})
    constrained = director_input(allowed_state_paths=["flags.allowed_choice"]).model_copy(
        update={
            "allowed_actions": ["idle"],
            "allowed_faces": ["neutral"],
            "max_tool_calls": max_tool_calls,
            "max_specialist_calls": max_specialist_calls,
        }
    )

    result = await build_executor().generate(constrained)

    assert calls == []
    assert result.metrics.model == "safe-fallback"
    assert result.proposal.plan.intent.value == "clarification"
    assert result.proposal.plan.proposed_state_changes.model_dump() == {
        "relationship": None,
        "flags": [],
        "quests": [],
    }
    assert result.proposal.performance.body_cues == []
    assert result.proposal.performance.face_cues == []
    assert result.proposal.performance.evidence.lore_refs == []
    assert result.proposal.performance.confidence == 0
    assert result.delegations == []
    assert result.handoffs == []
    assert result.lore_refs_accessed == []
    assert result.trace_id == "budget-fallback:bounded-turn"


@pytest.mark.asyncio
async def test_greeting_runs_bounded_typed_chain_and_assembles_authoritative_fields(
    monkeypatch,
) -> None:
    calls = install_fake_runner(
        monkeypatch,
        {
            ROUTER: RouteDecision(
                intent="greeting",
                objective="欢迎玩家",
                confidence=0.95,
            ),
            WRITER: dialogue(),
            PERFORMANCE: performance(),
        },
    )

    result = await build_executor().generate(director_input())

    assert [call[0] for call in calls] == [ROUTER, WRITER, PERFORMANCE]
    assert [event.specialist for event in result.delegations] == [
        SpecialistName.SCREENWRITER,
        SpecialistName.PERFORMANCE,
    ]
    assert all(event.status == "completed" for event in result.delegations)
    assert result.proposal.performance.dialogue.text == "欢迎来到灰港。"
    assert result.proposal.performance.emotion.coarse.value == "joy"
    assert [cue.action.value for cue in result.proposal.performance.body_cues] == ["idle"]
    assert [cue.preset.value for cue in result.proposal.performance.face_cues] == ["neutral"]
    assert result.proposal.plan.required_specialists == [
        SpecialistName.SCREENWRITER,
        SpecialistName.PERFORMANCE,
    ]
    assert result.metrics.total_tokens == 45
    assert result.response_id == "response-3"


@pytest.mark.asyncio
async def test_complex_route_runs_narrative_and_runtime_lore_with_truthful_trace(
    monkeypatch,
) -> None:
    retriever = RecordingRetriever()
    route = RouteDecision(
        intent="critical_choice",
        objective="核验记录后选择",
        needs_lore=True,
        needs_narrative=True,
        confidence=0.9,
        lore_queries=["灰烬战争结束时间"],
        response_obligations=["说明二十年前"],
    )
    calls = install_fake_runner(
        monkeypatch,
        {
            ROUTER: route,
            NARRATIVE: narrative(),
            WRITER: dialogue("战争在二十年前结束。"),
            PERFORMANCE: performance(),
        },
    )

    result = await build_executor(lore_retriever=retriever).generate(
        director_input(allowed_state_paths=["flags.allowed_choice"])
    )

    assert [call[0] for call in calls] == [ROUTER, NARRATIVE, WRITER, PERFORMANCE]
    assert [event.specialist for event in result.delegations] == [
        SpecialistName.NARRATIVE_PLANNER,
        SpecialistName.LORE,
        SpecialistName.SCREENWRITER,
        SpecialistName.PERFORMANCE,
    ]
    assert retriever.calls[0][0] == ["灰烬战争结束时间"]
    assert retriever.calls[0][1]["allowed_scopes"] == ["public"]
    assert result.lore_refs_accessed == ["lore:ash-war"]
    assert [flag.name for flag in result.proposal.plan.proposed_state_changes.flags] == [
        "allowed_choice"
    ]
    writer_input = next(run_input for agent, run_input, _ in calls if agent is WRITER)
    assert "灰烬战争在二十年前结束" in writer_input
    assert "说明二十年前" in writer_input


@pytest.mark.asyncio
async def test_optional_node_failure_cancels_and_joins_sibling(monkeypatch) -> None:
    route = RouteDecision(
        intent="critical_choice",
        objective="核验记录后选择",
        needs_lore=True,
        needs_narrative=True,
        confidence=0.9,
        lore_queries=["灰烬战争结束时间"],
    )
    lore_started = asyncio.Event()
    lore_cancelled = asyncio.Event()
    never_finishes = asyncio.Event()

    async def fake_run(agent, run_input, **kwargs):
        if agent is ROUTER:
            return FakeRunResult(route, "response-router")
        if agent is NARRATIVE:
            await lore_started.wait()
            raise RuntimeError("narrative node failed")
        raise AssertionError("downstream nodes must not run")

    async def blocking_lore(*args, **kwargs):
        lore_started.set()
        try:
            await never_finishes.wait()
        finally:
            lore_cancelled.set()

    executor = build_executor()
    monkeypatch.setattr(bounded_module.Runner, "run", staticmethod(fake_run))
    monkeypatch.setattr(executor, "_run_lore_node", blocking_lore)

    with pytest.raises(RuntimeError, match="narrative node failed"):
        await executor.generate(director_input())

    assert lore_cancelled.is_set()


@pytest.mark.asyncio
async def test_safe_dialogue_repair_reuses_router_narrative_and_lore(monkeypatch) -> None:
    retriever = RecordingRetriever()
    route = RouteDecision(
        intent="critical_choice",
        objective="核验记录后选择",
        needs_lore=True,
        needs_narrative=True,
        confidence=0.9,
        lore_queries=["灰烬战争结束时间"],
    )
    calls: list[object] = []
    writer_calls = 0

    async def fake_run(agent, run_input, **kwargs):
        nonlocal writer_calls
        calls.append(agent)
        if agent is ROUTER:
            output = route
        elif agent is NARRATIVE:
            output = narrative()
        elif agent is WRITER:
            writer_calls += 1
            output = dialogue("作为AI，我不能回答。" if writer_calls == 1 else "二十年前。")
        elif agent is PERFORMANCE:
            output = performance()
        else:  # pragma: no cover - protects the closed test graph
            raise AssertionError("unexpected agent")
        return FakeRunResult(output, f"response-{len(calls)}")

    monkeypatch.setattr(bounded_module.Runner, "run", staticmethod(fake_run))
    executor = build_executor(lore_retriever=retriever)
    turn_input = director_input(allowed_state_paths=["flags.allowed_choice"])

    await executor.generate(turn_input)
    repaired = await executor.generate(
        turn_input,
        repair_feedback="persona: Rewrite only as the NPC.",
    )

    assert calls == [
        ROUTER,
        NARRATIVE,
        WRITER,
        PERFORMANCE,
        WRITER,
        PERFORMANCE,
    ]
    assert len(retriever.calls) == 1
    assert repaired.proposal.performance.dialogue.text == "二十年前。"
    assert [event.specialist for event in repaired.delegations] == [
        SpecialistName.NARRATIVE_PLANNER,
        SpecialistName.LORE,
        SpecialistName.SCREENWRITER,
        SpecialistName.PERFORMANCE,
    ]
    # Reused prefix work is not charged again on the repair invocation.
    assert repaired.metrics.total_tokens == 30


@pytest.mark.asyncio
async def test_negotiation_is_terminal_handoff_and_is_sanitized(monkeypatch) -> None:
    calls = install_fake_runner(
        monkeypatch,
        {
            ROUTER: RouteDecision(
                intent="negotiation",
                objective="协商报酬",
                negotiation=True,
                confidence=0.95,
            ),
            NEGOTIATOR: negotiation_proposal(),
        },
    )

    result = await build_executor().generate(director_input())

    assert [call[0] for call in calls] == [ROUTER, NEGOTIATOR]
    assert result.delegations == []
    assert result.handoffs == ["Quest Negotiator"]
    assert result.proposal.plan.intent.value == "negotiation"
    assert result.proposal.plan.proposed_state_changes.flags == []
    assert [cue.action.value for cue in result.proposal.performance.body_cues] == ["idle"]
    assert [cue.preset.value for cue in result.proposal.performance.face_cues] == ["neutral"]


@pytest.mark.asyncio
async def test_negotiation_repair_reuses_route_and_only_reruns_handoff(monkeypatch) -> None:
    calls = install_fake_runner(
        monkeypatch,
        {
            ROUTER: RouteDecision(
                intent="negotiation",
                objective="协商报酬",
                negotiation=True,
                confidence=0.95,
            ),
            NEGOTIATOR: negotiation_proposal(),
        },
    )
    executor = build_executor()
    turn_input = director_input()

    await executor.generate(turn_input)
    repaired = await executor.generate(
        turn_input,
        repair_feedback="persona: Rewrite only as the NPC.",
    )

    assert [call[0] for call in calls] == [ROUTER, NEGOTIATOR, NEGOTIATOR]
    assert repaired.delegations == []
    assert repaired.handoffs == ["Quest Negotiator"]
    assert repaired.metrics.total_tokens == 15


@pytest.mark.asyncio
async def test_low_confidence_route_runs_advisory_narrative(monkeypatch) -> None:
    calls = install_fake_runner(
        monkeypatch,
        {
            ROUTER: RouteDecision(
                intent="critical_choice",
                objective="推进不可逆选择",
                needs_narrative=True,
                confidence=0.2,
            ),
            NARRATIVE: narrative(),
            WRITER: dialogue("证据不足，先核验再决定。"),
            PERFORMANCE: performance(),
        },
    )

    result = await build_executor().generate(director_input())

    assert [call[0] for call in calls] == [ROUTER, NARRATIVE, WRITER, PERFORMANCE]
    assert result.proposal.plan.intent.value == "critical_choice"
    assert result.proposal.plan.proposed_state_changes == StateChangeProposal()
    assert result.routing_trace is not None
    assert result.routing_trace.advisory_only
