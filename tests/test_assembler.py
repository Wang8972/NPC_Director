from __future__ import annotations

import pytest

from npc_director.contracts import (
    BodyAction,
    DelegationEvent,
    DialogueDraft,
    FacePreset,
    NarrativePlan,
    PerformanceOutput,
    RouteDecision,
    SpecialistName,
    TurnProposal,
)
from npc_director.orchestration.assembler import (
    SpecialistLedgerError,
    assemble_turn_proposal,
    compile_route,
    sanitize_handoff_proposal,
    sanitize_proposal,
)
from npc_director.orchestration.turn_policy import StateCapabilities, TurnPolicy


def make_decision(**updates) -> RouteDecision:
    payload = {
        "intent": "critical_choice",
        "objective": "决定东门防守方案",
        "needs_lore": True,
        "needs_narrative": True,
        "confidence": 0.9,
        "lore_queries": ["东门防御工事"],
        "constraints": ["不得替玩家做决定"],
    }
    payload.update(updates)
    return RouteDecision.model_validate(payload)


def make_dialogue() -> DialogueDraft:
    return DialogueDraft.model_validate(
        {
            "dialogue": {
                "text": "东门城墙已有裂缝。守门，还是先撤村民？你来决定。",
                "voice_style": "firm",
            },
            "coarse_emotion": "fear",
            "primary_emotion": "wary",
            "secondary_emotion": "stern",
        }
    )


def make_performance() -> PerformanceOutput:
    return PerformanceOutput.model_validate(
        {
            "performance": {
                "dialogue": {
                    "text": "我替你决定：立刻冲锋。",
                    "voice_style": "excited",
                },
                "emotion": {
                    "coarse": "joy",
                    "primary": "hopeful",
                    "intensity": 1,
                    "valence": 1,
                    "arousal": 1,
                },
                "body_cues": [
                    {"action": "step_forward", "start_ms": 0},
                    {"action": "nod", "start_ms": 200},
                ],
                "face_cues": [
                    {"preset": "angry", "start_ms": 0},
                    {"preset": "concerned", "start_ms": 200},
                ],
                "confidence": 0.9,
            }
        }
    )


def make_narrative() -> NarrativePlan:
    return NarrativePlan.model_validate(
        {
            "objective": "列出守门与撤离的代价，让玩家决定",
            "beats": [{"order": 1, "description": "说明两种选择"}],
            "constraints": ["不得推进未选择的分支"],
            "proposed_state_changes": {
                "relationship": {"trust_delta": 2, "affinity_delta": -2},
                "flags": [
                    {"name": "east_gate_warned", "value": True},
                    {"name": "invented_flag", "value": True},
                ],
                "quests": [
                    {"quest_id": "defend_east_gate", "status": "active"},
                    {"quest_id": "invented_quest", "status": "active"},
                ],
            },
        }
    )


def event(specialist: SpecialistName, status: str = "completed") -> DelegationEvent:
    return DelegationEvent(
        specialist=specialist,
        tool_name=f"{specialist.value}_tool",
        status=status,
    )


def make_policy() -> TurnPolicy:
    return TurnPolicy(
        allowed_actions=(BodyAction.NOD,),
        allowed_faces=(FacePreset.CONCERNED,),
        state=StateCapabilities(
            allowed_paths=frozenset(
                {
                    "relationship.trust_delta",
                    "flags.east_gate_warned",
                    "quests.defend_east_gate.status",
                }
            )
        ),
    )


def completed_ledger() -> list[DelegationEvent]:
    return [
        event(SpecialistName.SCREENWRITER),
        event(SpecialistName.LORE, "started"),
        event(SpecialistName.NARRATIVE_PLANNER),
        event(SpecialistName.LORE),
        event(SpecialistName.SCREENWRITER),
        event(SpecialistName.PERFORMANCE),
    ]


def test_assembler_preserves_field_ownership_and_exact_capabilities() -> None:
    route = compile_route(
        make_decision(),
        make_policy(),
        low_confidence_threshold=0.55,
    )

    proposal = assemble_turn_proposal(
        route,
        make_dialogue(),
        make_performance(),
        policy=make_policy(),
        ledger=completed_ledger(),
        narrative=make_narrative(),
        lore_refs=["lore:east-gate", "lore:east-gate", "lore:wall"],
    )

    assert proposal.performance.dialogue == make_dialogue().dialogue
    assert proposal.performance.emotion.coarse == make_dialogue().coarse_emotion
    assert proposal.performance.emotion.primary == make_dialogue().primary_emotion
    assert proposal.performance.emotion.secondary == make_dialogue().secondary_emotion
    assert proposal.performance.emotion.intensity == 0.5
    assert proposal.performance.emotion.valence == 0
    assert proposal.performance.emotion.arousal == 0.4
    assert [cue.action for cue in proposal.performance.body_cues] == [BodyAction.NOD]
    assert [cue.preset for cue in proposal.performance.face_cues] == [FacePreset.CONCERNED]
    assert proposal.performance.evidence.lore_refs == ["lore:east-gate", "lore:wall"]

    state = proposal.plan.proposed_state_changes
    assert state.relationship is not None
    assert state.relationship.trust_delta == 2
    assert state.relationship.affinity_delta == 0
    assert [flag.name for flag in state.flags] == ["east_gate_warned"]
    assert [quest.quest_id for quest in state.quests] == ["defend_east_gate"]
    assert proposal.plan.required_specialists == [
        SpecialistName.SCREENWRITER,
        SpecialistName.NARRATIVE_PLANNER,
        SpecialistName.LORE,
        SpecialistName.PERFORMANCE,
    ]


def test_required_specialists_come_only_from_completed_ledger() -> None:
    route = compile_route(
        make_decision(),
        make_policy(),
        low_confidence_threshold=0.55,
    )
    incomplete = [
        event(SpecialistName.NARRATIVE_PLANNER),
        event(SpecialistName.LORE, "failed"),
        event(SpecialistName.SCREENWRITER),
        event(SpecialistName.PERFORMANCE),
    ]

    with pytest.raises(SpecialistLedgerError, match="lore"):
        assemble_turn_proposal(
            route,
            make_dialogue(),
            make_performance(),
            policy=make_policy(),
            ledger=incomplete,
            narrative=make_narrative(),
        )

    unexpected = [
        event(SpecialistName.NARRATIVE_PLANNER),
        event(SpecialistName.LORE),
        event(SpecialistName.SCREENWRITER),
        event(SpecialistName.PERFORMANCE),
        event(SpecialistName.BASELINE),
    ]
    with pytest.raises(SpecialistLedgerError, match="outside compiled route: baseline"):
        assemble_turn_proposal(
            route,
            make_dialogue(),
            make_performance(),
            policy=make_policy(),
            ledger=unexpected,
            narrative=make_narrative(),
        )


def test_unrouted_narrative_and_lore_artifacts_cannot_add_state_or_evidence() -> None:
    route = compile_route(
        make_decision(
            intent="greeting",
            needs_lore=False,
            needs_narrative=False,
            lore_queries=[],
        ),
        make_policy(),
        low_confidence_threshold=0.55,
    )
    proposal = assemble_turn_proposal(
        route,
        make_dialogue(),
        make_performance(),
        policy=make_policy(),
        ledger=[
            event(SpecialistName.SCREENWRITER),
            event(SpecialistName.PERFORMANCE),
        ],
        narrative=make_narrative(),
        lore_refs=["unrouted:lore"],
    )

    assert proposal.plan.proposed_state_changes.relationship is None
    assert proposal.plan.proposed_state_changes.flags == []
    assert proposal.plan.proposed_state_changes.quests == []
    assert proposal.performance.evidence.lore_refs == []


def test_empty_policy_catalogs_clip_all_performance_cues() -> None:
    route = compile_route(
        make_decision(
            intent="greeting",
            needs_lore=False,
            needs_narrative=False,
            lore_queries=[],
        ),
        TurnPolicy(allowed_actions=(), allowed_faces=()),
        low_confidence_threshold=0.55,
    )
    proposal = assemble_turn_proposal(
        route,
        make_dialogue(),
        make_performance(),
        policy=TurnPolicy(allowed_actions=(), allowed_faces=()),
        ledger=[
            event(SpecialistName.SCREENWRITER),
            event(SpecialistName.PERFORMANCE),
        ],
    )

    assert proposal.performance.body_cues == []
    assert proposal.performance.face_cues == []


def test_handoff_sanitizer_clips_cues_and_forces_empty_state() -> None:
    proposal = TurnProposal.model_validate(
        {
            "plan": {
                "goal": "协商报酬",
                "intent": "negotiation",
                "required_specialists": ["screenwriter"],
                "proposed_state_changes": make_narrative().proposed_state_changes.model_dump(
                    mode="python"
                ),
            },
            "performance": make_performance().performance.model_dump(mode="python"),
        }
    )

    sanitized = sanitize_handoff_proposal(proposal, policy=make_policy())

    assert [cue.action for cue in sanitized.performance.body_cues] == [BodyAction.NOD]
    assert [cue.preset for cue in sanitized.performance.face_cues] == [FacePreset.CONCERNED]
    state = sanitized.plan.proposed_state_changes
    assert state.relationship is None
    assert state.flags == []
    assert state.quests == []


def test_generic_sanitizer_clips_cues_without_changing_state() -> None:
    proposal = TurnProposal.model_validate(
        {
            "plan": {
                "goal": "记录玩家选择",
                "intent": "critical_choice",
                "required_specialists": ["screenwriter"],
                "proposed_state_changes": make_narrative().proposed_state_changes.model_dump(
                    mode="python"
                ),
            },
            "performance": make_performance().performance.model_dump(mode="python"),
        }
    )

    sanitized = sanitize_proposal(proposal, policy=make_policy())

    assert [cue.action for cue in sanitized.performance.body_cues] == [BodyAction.NOD]
    assert [cue.preset for cue in sanitized.performance.face_cues] == [FacePreset.CONCERNED]
    assert sanitized.plan.proposed_state_changes == proposal.plan.proposed_state_changes
