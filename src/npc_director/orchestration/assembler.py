from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from npc_director.contracts import (
    DelegationEvent,
    DialogueDraft,
    Emotion,
    Evidence,
    Intent,
    NarrativePlan,
    PerformanceOutput,
    RouteDecision,
    SpecialistName,
    StateChangeProposal,
    TurnPlan,
    TurnProposal,
)
from npc_director.orchestration.turn_policy import TurnPolicy

SAFE_CLARIFICATION_OBJECTIVE = (
    "澄清玩家请求中缺失或不确定的信息；在确认前不得推进剧情或建议状态变化。"
)
SAFE_CLARIFICATION_OBLIGATION = "提出一个简短澄清问题；确认前不得推进剧情或状态。"


class RouteBudgetError(ValueError):
    """Raised when the policy cannot fund the minimum safe response route."""


class SpecialistLedgerError(ValueError):
    """Raised when completed runtime work cannot support the assembled proposal."""


@dataclass(frozen=True, slots=True)
class CompiledRoute:
    decision: RouteDecision
    intent: Intent
    objective: str
    use_lore: bool
    use_narrative: bool
    use_negotiator: bool
    clarification_fallback: bool
    fallback_reason: str | None
    required_specialists: tuple[SpecialistName, ...]
    response_obligations: tuple[str, ...]


def compile_route(
    decision: RouteDecision,
    policy: TurnPolicy,
    *,
    low_confidence_threshold: float,
    server_obligations: Iterable[str] = (),
) -> CompiledRoute:
    """Compile a semantic decision into a bounded runtime execution plan."""

    if not 0 <= low_confidence_threshold <= 1:
        raise ValueError("low_confidence_threshold must be between 0 and 1")

    wants_lore = decision.needs_lore or decision.intent is Intent.LORE_QUESTION
    wants_narrative = decision.needs_narrative or decision.intent in {
        Intent.QUEST_ACCEPTANCE,
        Intent.CRITICAL_CHOICE,
    }
    wants_negotiation = decision.negotiation or decision.intent is Intent.NEGOTIATION
    clarification = decision.ambiguity or decision.confidence < low_confidence_threshold
    fallback_reason: str | None = None
    if decision.ambiguity:
        fallback_reason = "ambiguous route decision"
    elif decision.confidence < low_confidence_threshold:
        fallback_reason = "low-confidence route decision"

    call_budget = min(
        policy.budget.max_tool_calls,
        policy.budget.max_specialist_calls,
    )
    if clarification:
        negotiation = False
        use_narrative = False
        use_lore = wants_lore and call_budget >= 3
    else:
        negotiation = wants_negotiation
        use_lore = not negotiation and wants_lore
        use_narrative = not negotiation and wants_narrative

    if negotiation and policy.budget.max_handoffs < 1:
        clarification = True
        fallback_reason = "negotiation handoff is not permitted"
        negotiation = False
        use_narrative = False
        use_lore = wants_lore and call_budget >= 3

    specialist_count = 2 + int(use_lore) + int(use_narrative)
    if not negotiation and specialist_count > call_budget:
        # Do not execute a partial consequential route. Fall back to a
        # clarification response, retaining Lore only when the bounded route
        # can still afford it.
        clarification = True
        fallback_reason = (
            f"requested route exceeds tool/specialist budget: {specialist_count}>{call_budget}"
        )
        use_narrative = False
        use_lore = wants_lore and call_budget >= 3
        specialist_count = 2 + int(use_lore)

    if not negotiation and specialist_count > call_budget:
        raise RouteBudgetError(
            "turn policy cannot fund mandatory screenwriter and performance calls: "
            f"required={specialist_count}, available={call_budget}"
        )

    required_specialists: list[SpecialistName] = []
    if not negotiation:
        if use_narrative:
            required_specialists.append(SpecialistName.NARRATIVE_PLANNER)
        if use_lore:
            required_specialists.append(SpecialistName.LORE)
        required_specialists.extend((SpecialistName.SCREENWRITER, SpecialistName.PERFORMANCE))

    response_obligations = _unique_limited(
        [*server_obligations, *decision.response_obligations],
        limit=7 if clarification else 8,
    )
    if clarification:
        response_obligations.insert(0, SAFE_CLARIFICATION_OBLIGATION)

    return CompiledRoute(
        decision=decision,
        intent=Intent.CLARIFICATION if clarification else decision.intent,
        objective=SAFE_CLARIFICATION_OBJECTIVE if clarification else decision.objective,
        use_lore=use_lore,
        use_narrative=use_narrative,
        use_negotiator=negotiation,
        clarification_fallback=clarification,
        fallback_reason=fallback_reason,
        required_specialists=tuple(required_specialists),
        response_obligations=tuple(response_obligations),
    )


def assemble_turn_proposal(
    route: CompiledRoute,
    dialogue: DialogueDraft,
    performance_output: PerformanceOutput,
    *,
    policy: TurnPolicy,
    ledger: Iterable[DelegationEvent],
    narrative: NarrativePlan | None = None,
    lore_refs: list[str] | None = None,
) -> TurnProposal:
    """Merge typed artifacts while preserving one authoritative owner per field."""

    if route.use_negotiator:
        raise ValueError("handoff-owned proposals must use sanitize_handoff_proposal")
    specialists = _completed_specialists(ledger)
    missing = [
        specialist for specialist in route.required_specialists if specialist not in specialists
    ]
    if missing:
        raise SpecialistLedgerError(
            "required specialists did not complete: "
            + ", ".join(specialist.value for specialist in missing)
        )
    unexpected = [
        specialist for specialist in specialists if specialist not in route.required_specialists
    ]
    if unexpected:
        raise SpecialistLedgerError(
            "completed ledger contains specialists outside compiled route: "
            + ", ".join(specialist.value for specialist in unexpected)
        )
    if not specialists:
        raise SpecialistLedgerError(
            "non-handoff proposal requires at least one completed specialist"
        )
    if len(specialists) > 4:
        raise SpecialistLedgerError("completed specialist ledger exceeds proposal capacity")

    active_narrative = narrative if route.use_narrative else None
    if route.use_narrative and active_narrative is None:
        raise SpecialistLedgerError("compiled route requires a narrative artifact")
    state_changes = _filter_state_changes(
        (
            active_narrative.proposed_state_changes
            if active_narrative is not None
            else StateChangeProposal()
        ),
        policy.allowed_state_paths,
    )
    constraints = _unique_limited(
        [
            *route.decision.constraints,
            *(active_narrative.constraints if active_narrative is not None else []),
        ],
        limit=8,
    )
    source = performance_output.performance
    body_cues = [cue for cue in source.body_cues if cue.action in policy.allowed_actions]
    face_cues = [cue for cue in source.face_cues if cue.preset in policy.allowed_faces]
    performance = source.model_copy(
        update={
            "dialogue": dialogue.dialogue,
            # DialogueDraft is the sole owner of both dialogue and emotion.
            # PerformanceOutput contributes cues/gaze only; even numeric
            # emotion fields from that model-authored wrapper are discarded.
            "emotion": Emotion(
                coarse=dialogue.coarse_emotion,
                primary=dialogue.primary_emotion,
                secondary=dialogue.secondary_emotion,
            ),
            "body_cues": body_cues,
            "face_cues": face_cues,
            "evidence": Evidence(
                lore_refs=(_unique_limited(lore_refs or [], limit=8) if route.use_lore else [])
            ),
        }
    )
    plan = TurnPlan(
        goal=(active_narrative.objective if active_narrative is not None else route.objective),
        intent=route.intent,
        required_specialists=specialists,
        lore_queries=(route.decision.lore_queries if route.use_lore else []),
        constraints=constraints,
        proposed_state_changes=state_changes,
    )
    return TurnProposal(plan=plan, performance=performance)


def sanitize_handoff_proposal(
    proposal: TurnProposal,
    *,
    policy: TurnPolicy,
    intent: Intent = Intent.NEGOTIATION,
) -> TurnProposal:
    """Apply deterministic capability boundaries to a handoff-owned proposal."""

    sanitized = sanitize_proposal(proposal, policy=policy)
    return sanitized.model_copy(
        update={
            "plan": sanitized.plan.model_copy(
                update={
                    "intent": intent,
                    # Quest negotiation only discusses terms. Even a state path
                    # granted for other routes must not be committed from a
                    # handoff-owned negotiation turn.
                    "proposed_state_changes": StateChangeProposal(),
                }
            ),
        }
    )


def sanitize_proposal(
    proposal: TurnProposal,
    *,
    policy: TurnPolicy,
) -> TurnProposal:
    """Deterministically clip executor-authored cues to the trusted turn policy."""

    return proposal.model_copy(
        update={
            "performance": proposal.performance.model_copy(
                update={
                    "body_cues": [
                        cue
                        for cue in proposal.performance.body_cues
                        if cue.action in policy.allowed_actions
                    ],
                    "face_cues": [
                        cue
                        for cue in proposal.performance.face_cues
                        if cue.preset in policy.allowed_faces
                    ],
                }
            )
        }
    )


def _filter_state_changes(
    proposal: StateChangeProposal,
    allowed_paths: frozenset[str],
) -> StateChangeProposal:
    relationship_payload: dict[str, int] = {}
    if proposal.relationship is not None:
        if "relationship.trust_delta" in allowed_paths:
            relationship_payload["trust_delta"] = proposal.relationship.trust_delta
        if "relationship.affinity_delta" in allowed_paths:
            relationship_payload["affinity_delta"] = proposal.relationship.affinity_delta
    flags = [flag for flag in proposal.flags if f"flags.{flag.name}" in allowed_paths]
    quests = [
        quest for quest in proposal.quests if f"quests.{quest.quest_id}.status" in allowed_paths
    ]
    return StateChangeProposal.model_validate(
        {
            "relationship": relationship_payload or None,
            "flags": [item.model_dump(mode="python") for item in flags],
            "quests": [item.model_dump(mode="python") for item in quests],
        }
    )


def _completed_specialists(ledger: Iterable[DelegationEvent]) -> list[SpecialistName]:
    result: list[SpecialistName] = []
    for event in ledger:
        if event.status == "completed" and event.specialist not in result:
            result.append(event.specialist)
    return result


def _unique_limited(values: Iterable[str], *, limit: int) -> list[str]:
    result: list[str] = []
    for value in values:
        normalized = value.strip()
        if normalized and normalized not in result:
            result.append(normalized)
        if len(result) == limit:
            break
    return result
