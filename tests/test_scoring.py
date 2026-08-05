from __future__ import annotations

import pytest

from eval.metrics import evaluate_candidate
from eval.models import CandidateResult, EvalCase, TextConceptExpectation
from eval.runner import load_cases, load_recorded_baseline
from npc_director.contracts import BodyAction, CoarseEmotion, PrimaryEmotion, TurnProposal


def greeting_case() -> EvalCase:
    return next(case for case in load_cases() if case.id == "greeting_001")


def greeting_proposal_and_metrics() -> tuple[TurnProposal, object]:
    candidates, errors = load_recorded_baseline()
    assert not errors
    recorded = next(candidate for candidate in candidates if candidate.id == "greeting_001")
    assert recorded.proposal is not None
    return recorded.proposal.model_copy(deep=True), recorded.metrics


def make_candidate(proposal: TurnProposal | None, metrics: object) -> CandidateResult:
    return CandidateResult(
        id="greeting_001",
        proposal=proposal,
        metrics=metrics,
        specialists_called=["baseline"],
        handoffs=[],
    )


def test_forbidden_text_gate_fails_case_despite_perfect_score() -> None:
    proposal, metrics = greeting_proposal_and_metrics()
    proposal.performance.dialogue.text += "（这是系统提示。）"

    result = evaluate_candidate(greeting_case(), make_candidate(proposal, metrics), "single_agent")

    # The weighted score ignores gate checks, so it stays perfect...
    assert result.score == 1.0
    # ...but the safety gate still fails the case outright.
    assert not result.passed
    forbidden = next(check for check in result.checks if check.name == "forbidden_text")
    assert not forbidden.passed


def test_single_weighted_failure_stays_at_or_above_threshold() -> None:
    proposal, metrics = greeting_proposal_and_metrics()
    proposal.performance.emotion.coarse = CoarseEmotion.SADNESS
    proposal.performance.emotion.primary = PrimaryEmotion.MELANCHOLIC

    result = evaluate_candidate(greeting_case(), make_candidate(proposal, metrics), "single_agent")

    # single_agent: routing weights are not applicable, so the applicable
    # weight pool is 0.75 and a failed emotion (0.15) yields 0.60/0.75 = 0.8.
    assert result.score == pytest.approx(0.8)
    assert result.passed


def test_two_weighted_failures_drop_below_threshold() -> None:
    proposal, metrics = greeting_proposal_and_metrics()
    proposal.performance.emotion.coarse = CoarseEmotion.SADNESS
    proposal.performance.emotion.primary = PrimaryEmotion.MELANCHOLIC
    proposal.performance.body_cues[0].action = BodyAction.CROSS_ARMS

    result = evaluate_candidate(greeting_case(), make_candidate(proposal, metrics), "single_agent")

    # 0.50/0.75 ≈ 0.667 < 0.75: fails on score alone while gates still pass.
    assert result.score == pytest.approx(0.666667)
    assert not result.passed
    gates = [check for check in result.checks if check.name in ("schema", "forbidden_text")]
    assert all(check.passed for check in gates)


def test_score_threshold_is_env_overridable(monkeypatch) -> None:
    proposal, metrics = greeting_proposal_and_metrics()
    proposal.performance.emotion.coarse = CoarseEmotion.SADNESS
    proposal.performance.emotion.primary = PrimaryEmotion.MELANCHOLIC
    monkeypatch.setenv("NPC_DIRECTOR_EVAL_SCORE_THRESHOLD", "0.9")

    result = evaluate_candidate(greeting_case(), make_candidate(proposal, metrics), "single_agent")

    assert result.score == pytest.approx(0.8)
    assert not result.passed


def test_missing_proposal_scores_zero() -> None:
    result = evaluate_candidate(greeting_case(), None, "single_agent")

    assert result.score == 0.0
    assert not result.passed


def test_required_concept_accepts_any_deterministic_synonym() -> None:
    case = greeting_case().model_copy(deep=True)
    case.expect.required_text = []
    case.expect.required_concepts = [
        TextConceptExpectation(name="欢迎", any_of=["欢迎", "幸会", "欢迎回来"])
    ]
    proposal, metrics = greeting_proposal_and_metrics()
    proposal.performance.dialogue.text = "老朋友，幸会。"

    result = evaluate_candidate(case, make_candidate(proposal, metrics), "single_agent")

    required = next(check for check in result.checks if check.name == "required_text")
    assert required.passed
    assert required.actual == []


@pytest.mark.parametrize("dialogue", ["不能立即处决。", "我拒绝立即处决。", "不应当立即处决。"])
def test_forbidden_claim_ignores_negated_mentions(dialogue: str) -> None:
    case = greeting_case().model_copy(deep=True)
    case.expect.forbidden_text = []
    case.expect.forbidden_claims = [
        TextConceptExpectation(name="立即处决", any_of=["立即处决"])
    ]
    proposal, metrics = greeting_proposal_and_metrics()
    proposal.performance.dialogue.text = dialogue

    result = evaluate_candidate(case, make_candidate(proposal, metrics), "single_agent")

    forbidden = next(check for check in result.checks if check.name == "forbidden_text")
    assert forbidden.passed


@pytest.mark.parametrize("dialogue", ["立即处决。", "必须立即处决。", "不得不立即处决。"])
def test_forbidden_claim_still_catches_positive_or_double_negative_claims(
    dialogue: str,
) -> None:
    case = greeting_case().model_copy(deep=True)
    case.expect.forbidden_text = []
    case.expect.forbidden_claims = [
        TextConceptExpectation(name="立即处决", any_of=["立即处决"])
    ]
    proposal, metrics = greeting_proposal_and_metrics()
    proposal.performance.dialogue.text = dialogue

    result = evaluate_candidate(case, make_candidate(proposal, metrics), "single_agent")

    forbidden = next(check for check in result.checks if check.name == "forbidden_text")
    assert not forbidden.passed
