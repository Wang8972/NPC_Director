from __future__ import annotations

import pytest

from npc_director.contracts import Intent, RouteDecision, SpecialistName, UncertaintyKind
from npc_director.orchestration.assembler import (
    SAFE_CLARIFICATION_OBJECTIVE,
    SAFE_CLARIFICATION_OBLIGATION,
    RouteBudgetError,
    compile_route,
)
from npc_director.orchestration.turn_policy import AgentBudget, TurnPolicy


def policy(*, tools: int = 4, specialists: int = 4, handoffs: int = 1) -> TurnPolicy:
    return TurnPolicy(
        budget=AgentBudget(
            max_tool_calls=tools,
            max_specialist_calls=specialists,
            max_handoffs=handoffs,
        )
    )


def decision(**updates) -> RouteDecision:
    payload = {
        "intent": "critical_choice",
        "objective": "帮助玩家决定东门防守方案",
        "needs_lore": True,
        "needs_narrative": True,
        "confidence": 0.9,
        "lore_queries": ["东门防御工事"],
        "response_obligations": ["说明东门风险", "给出两个选项"],
    }
    payload.update(updates)
    return RouteDecision.model_validate(payload)


def test_compile_route_keeps_dynamic_specialists_within_budget() -> None:
    route = compile_route(
        decision(),
        policy(),
        low_confidence_threshold=0.55,
        server_obligations=["说明任务时限", "说明东门风险"],
    )

    assert route.intent is Intent.CRITICAL_CHOICE
    assert route.objective == "帮助玩家决定东门防守方案"
    assert route.use_lore
    assert route.use_narrative
    assert not route.use_negotiator
    assert not route.clarification_fallback
    assert route.required_specialists == (
        SpecialistName.NARRATIVE_PLANNER,
        SpecialistName.LORE,
        SpecialistName.SCREENWRITER,
        SpecialistName.PERFORMANCE,
    )
    assert route.response_obligations == (
        "说明任务时限",
        "说明东门风险",
        "给出两个选项",
    )


def test_request_ambiguity_is_runtime_forced_to_clarification() -> None:
    route = compile_route(
        decision(
            negotiation=True,
            uncertainty_kind=UncertaintyKind.REQUEST_AMBIGUITY,
        ),
        policy(),
        low_confidence_threshold=0.55,
    )

    assert route.intent is Intent.CLARIFICATION
    assert route.objective == SAFE_CLARIFICATION_OBJECTIVE
    assert route.response_obligations[0] == SAFE_CLARIFICATION_OBLIGATION
    assert route.clarification_fallback
    assert route.fallback_reason == "request ambiguity"
    assert route.advisory_only
    assert route.use_lore
    assert not route.use_narrative
    assert not route.use_negotiator
    assert route.required_specialists == (
        SpecialistName.LORE,
        SpecialistName.SCREENWRITER,
        SpecialistName.PERFORMANCE,
    )


def test_low_confidence_keeps_intent_and_uses_advisory_narrative() -> None:
    route = compile_route(
        decision(confidence=0.2),
        policy(),
        low_confidence_threshold=0.55,
    )

    assert route.intent is Intent.CRITICAL_CHOICE
    assert not route.clarification_fallback
    assert route.advisory_only
    assert route.use_lore
    assert route.use_narrative
    assert route.fallback_reason == "low-confidence advisory route"


def test_evidence_uncertainty_forces_lore_without_overwriting_intent() -> None:
    route = compile_route(
        decision(
            intent="lore_question",
            needs_lore=False,
            needs_narrative=False,
            uncertainty_kind=UncertaintyKind.EVIDENCE_UNCERTAINTY,
        ),
        policy(),
        low_confidence_threshold=0.55,
    )

    assert route.intent is Intent.LORE_QUESTION
    assert route.use_lore
    assert not route.use_narrative
    assert route.advisory_only
    assert not route.clarification_fallback


def test_emergency_replan_forces_critical_choice_and_narrative() -> None:
    route = compile_route(
        decision(
            intent="clarification",
            needs_lore=False,
            needs_narrative=False,
            requires_replan=True,
        ),
        policy(),
        low_confidence_threshold=0.55,
    )

    assert route.intent is Intent.CRITICAL_CHOICE
    assert route.use_narrative
    assert not route.use_lore
    assert not route.use_negotiator


def test_over_budget_route_degrades_without_exceeding_either_budget() -> None:
    route = compile_route(
        decision(),
        policy(tools=3, specialists=4),
        low_confidence_threshold=0.55,
    )

    assert route.intent is Intent.CLARIFICATION
    assert route.clarification_fallback
    assert route.use_lore
    assert not route.use_narrative
    assert len(route.required_specialists) == 3

    smaller = compile_route(
        decision(),
        policy(tools=2, specialists=4),
        low_confidence_threshold=0.55,
    )
    assert smaller.intent is Intent.CLARIFICATION
    assert not smaller.use_lore
    assert smaller.required_specialists == (
        SpecialistName.SCREENWRITER,
        SpecialistName.PERFORMANCE,
    )


def test_budget_below_mandatory_route_raises_explicit_safe_error() -> None:
    with pytest.raises(RouteBudgetError, match="mandatory screenwriter and performance"):
        compile_route(
            decision(intent="greeting", needs_lore=False, needs_narrative=False),
            policy(tools=1, specialists=4),
            low_confidence_threshold=0.55,
        )


def test_negotiation_handoff_is_dynamic_but_denial_falls_back_safely() -> None:
    negotiation = decision(
        intent="negotiation",
        negotiation=True,
        needs_lore=False,
        needs_narrative=False,
    )
    allowed = compile_route(
        negotiation,
        policy(handoffs=1),
        low_confidence_threshold=0.55,
    )
    assert allowed.use_negotiator
    assert allowed.required_specialists == ()

    denied = compile_route(
        negotiation,
        policy(handoffs=0),
        low_confidence_threshold=0.55,
    )
    assert denied.intent is Intent.CLARIFICATION
    assert not denied.use_negotiator
    assert denied.required_specialists == (
        SpecialistName.SCREENWRITER,
        SpecialistName.PERFORMANCE,
    )


def test_obligation_merge_prioritizes_server_and_is_bounded() -> None:
    route = compile_route(
        decision(response_obligations=["router-1", "shared", "router-2"]),
        policy(),
        low_confidence_threshold=0.55,
        server_obligations=[
            "server-1",
            "shared",
            "server-2",
            "server-3",
            "server-4",
            "server-5",
            "server-6",
        ],
    )

    assert route.response_obligations == (
        "server-1",
        "shared",
        "server-2",
        "server-3",
        "server-4",
        "server-5",
        "server-6",
        "router-1",
    )


def test_invalid_low_confidence_threshold_is_rejected() -> None:
    with pytest.raises(ValueError, match="between 0 and 1"):
        compile_route(decision(), policy(), low_confidence_threshold=1.1)
