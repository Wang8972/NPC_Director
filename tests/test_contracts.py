from __future__ import annotations

import pytest
from pydantic import ValidationError

from npc_director.contracts import (
    PerformanceDirective,
    TurnProposal,
    TurnRequest,
    extract_state_change_paths,
)
from npc_director.governance.finalizer import finalize_baseline_proposal


def valid_proposal_payload() -> dict:
    return {
        "plan": {
            "goal": "回应玩家道歉",
            "intent": "reconciliation",
            "required_specialists": ["baseline"],
            "constraints": ["不能立即完全原谅玩家"],
            "proposed_state_changes": {
                "relationship": {"trust_delta": 2},
                "flags": [{"name": "reunion_started", "value": True}],
            },
        },
        "performance": {
            "dialogue": {"text": "你终于回来了。", "voice_style": "soft_restrained"},
            "emotion": {"coarse": "joy", "primary": "relieved"},
            "face_cues": [{"preset": "relieved_smile"}],
            "body_cues": [{"action": "step_forward"}],
            "confidence": 0.84,
        },
    }


def valid_request() -> TurnRequest:
    return TurnRequest.model_validate(
        {
            "session_id": "session-17",
            "turn_id": "session-17:42",
            "npc_id": "elder_maren",
            "player_input": "对不起，我离开了这么久。",
            "scene": {"location": "village_gate"},
            "character_core": "克制但重视承诺的村庄长老。",
        }
    )


def test_contract_accepts_valid_proposal_and_extracts_state_paths() -> None:
    proposal = TurnProposal.model_validate(valid_proposal_payload())

    assert extract_state_change_paths(proposal.plan.proposed_state_changes) == {
        "relationship.trust_delta",
        "flags.reunion_started",
    }


def test_contract_rejects_unknown_action() -> None:
    payload = valid_proposal_payload()
    payload["performance"]["body_cues"][0]["action"] = "execute_shell_command"

    with pytest.raises(ValidationError):
        TurnProposal.model_validate(payload)


def test_contract_sorts_unordered_cues_at_parse_time() -> None:
    payload = valid_proposal_payload()
    payload["performance"]["face_cues"] = [
        {"preset": "relieved_smile", "start_ms": 800},
        {"preset": "happy", "start_ms": 0},
    ]
    payload["performance"]["body_cues"] = [
        {"action": "step_forward", "start_ms": 500},
        {"action": "small_nod", "start_ms": 0},
        {"action": "open_palms", "start_ms": 500},
    ]

    proposal = TurnProposal.model_validate(payload)

    assert [cue.start_ms for cue in proposal.performance.face_cues] == [0, 800]
    assert [cue.start_ms for cue in proposal.performance.body_cues] == [0, 500, 500]
    # Stable sort keeps the original relative order of equal start_ms cues.
    assert [cue.action.value for cue in proposal.performance.body_cues] == [
        "small_nod",
        "step_forward",
        "open_palms",
    ]


def test_contract_rejects_model_authored_runtime_meta() -> None:
    payload = valid_proposal_payload()
    payload["performance"]["runtime_meta"] = {"specialists_called": ["baseline"]}

    with pytest.raises(ValidationError):
        TurnProposal.model_validate(payload)


def test_finalizer_adds_trusted_runtime_meta() -> None:
    proposal = TurnProposal.model_validate(valid_proposal_payload())
    directive = finalize_baseline_proposal(
        valid_request(),
        proposal,
        prompt_version="baseline-v1",
        model="test-model",
        trace_id="trace-1",
        response_id="response-1",
    )

    assert isinstance(directive, PerformanceDirective)
    assert directive.turn_id == "session-17:42"
    assert directive.runtime_meta.specialists_called == ["baseline"]
    assert directive.runtime_meta.trace_id == "trace-1"
    assert directive.runtime_meta.response_id == "response-1"
