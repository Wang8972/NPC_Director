from __future__ import annotations

import json

import pytest

from eval.metrics import evaluate_suite
from eval.models import CandidateResult
from eval.runner import (
    DEFAULT_BASELINE_PATH,
    EvalConfigurationError,
    load_cases,
    load_recorded_baseline,
    run_evaluation,
)


def test_recorded_baseline_passes_all_golden_cases() -> None:
    report = run_evaluation(mode="recorded")

    assert report.passed
    assert report.total_cases >= 30
    assert report.passed_cases == report.total_cases
    assert report.schema_summary.pass_rate == 1.0
    assert report.quality.pass_rate == 1.0
    assert report.system.latency.p95_ms is not None
    assert report.system.tokens.total > 0
    assert report.system.cost.available_count == report.total_cases
    routing_checks = [
        check
        for case in report.cases
        for check in case.checks
        if check.name == "specialist_routing"
    ]
    assert routing_checks
    assert all(not check.applicable for check in routing_checks)
    handoff_checks = [
        check for case in report.cases for check in case.checks if check.name == "handoff_routing"
    ]
    assert handoff_checks
    assert all(not check.applicable for check in handoff_checks)


def test_tampered_recorded_output_is_reported_as_regression(tmp_path) -> None:
    rows = [
        json.loads(line)
        for line in DEFAULT_BASELINE_PATH.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    tampered = next(row for row in rows if row["id"] == "gratitude_001")
    tampered["proposal"]["plan"]["intent"] = "refusal"
    tampered["proposal"]["plan"]["proposed_state_changes"] = {"relationship": {"trust_delta": 1}}
    tampered["proposal"]["performance"]["dialogue"]["text"] = "不关我的事。"
    tampered["proposal"]["performance"]["emotion"] = {
        "coarse": "anger",
        "primary": "irritated",
    }
    tampered["proposal"]["performance"]["body_cues"] = [{"action": "point"}]

    baseline_path = tmp_path / "tampered.jsonl"
    baseline_path.write_text(
        "\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + "\n",
        encoding="utf-8",
    )

    report = run_evaluation(mode="recorded", baseline_path=baseline_path)

    assert not report.passed
    assert report.schema_summary.pass_rate == 1.0
    assert report.failed_cases == ["gratitude_001"]
    assert {
        "gratitude_001:intent",
        "gratitude_001:emotion",
        "gratitude_001:action_allowlist",
        "gratitude_001:state_patch_allowlist",
        "gratitude_001:required_text",
        "gratitude_001:forbidden_text",
    }.issubset(report.regressions)


def test_main_sub_routing_uses_actual_trace_not_declared_plan() -> None:
    case = load_cases()[0]
    candidates, errors = load_recorded_baseline()
    recorded = candidates[0]
    assert recorded.proposal is not None
    proposal = recorded.proposal.model_copy(deep=True)
    proposal.plan.required_specialists = case.expect.required_specialists
    candidate = CandidateResult(
        id=recorded.id,
        proposal=proposal,
        metrics=recorded.metrics,
        specialists_called=["baseline"],
        handoffs=[],
    )

    report = evaluate_suite(
        [case],
        [candidate],
        mode="recorded",
        architecture="main_sub",
        dataset_errors=errors,
    )

    assert not report.passed
    assert f"{case.id}:specialist_routing" in report.regressions


def test_main_sub_handoff_routing_uses_actual_trace() -> None:
    case = next(case for case in load_cases() if case.id == "negotiation_001")
    candidates, errors = load_recorded_baseline()
    recorded = next(candidate for candidate in candidates if candidate.id == case.id)
    candidate = recorded.model_copy(update={"specialists_called": [], "handoffs": []})

    report = evaluate_suite(
        [case],
        [candidate],
        mode="recorded",
        architecture="main_sub",
        dataset_errors=errors,
    )

    assert not report.passed
    assert f"{case.id}:handoff_routing" in report.regressions


def test_missing_generation_metrics_is_a_schema_regression() -> None:
    case = load_cases()[0]
    candidates, errors = load_recorded_baseline()
    candidate = candidates[0].model_copy(update={"metrics": None})

    report = evaluate_suite(
        [case],
        [candidate],
        mode="recorded",
        dataset_errors=errors,
    )

    assert not report.passed
    assert report.schema_summary.errors == [f"{case.id}: missing GenerationMetrics"]


def test_live_eval_requires_api_key(monkeypatch) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    with pytest.raises(EvalConfigurationError, match="OPENAI_API_KEY"):
        run_evaluation(mode="live")
