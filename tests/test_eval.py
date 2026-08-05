from __future__ import annotations

import json

import pytest

from eval.metrics import evaluate_suite
from eval.models import CandidateResult
from eval.runner import (
    DEFAULT_BASELINE_PATH,
    EvalConfigurationError,
    EvalQuotaStopped,
    _coerce_live_result,
    _completed_specialists,
    load_cases,
    load_recorded_baseline,
    main,
    partial_report_path,
    run_evaluation,
)
from npc_director.contracts import (
    DelegationEvent,
    DirectorRunResult,
    RouteDecision,
    RoutingTrace,
    SpecialistName,
)


def test_recorded_baseline_passes_all_golden_cases() -> None:
    report = run_evaluation(mode="recorded")

    assert report.passed
    assert report.report_version == 2
    assert report.run_status == "completed"
    assert report.requested_cases == report.total_cases
    assert report.completed_cases == report.total_cases
    assert report.stop_reason is None
    assert len(report.candidates) == report.total_cases
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

    # Routing misses alone stay at/above the weighted threshold, but the
    # failed check is still exposed as a regression and lowers the score.
    assert report.passed
    assert f"{case.id}:specialist_routing" in report.regressions
    assert report.cases[0].score == pytest.approx(0.85)


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

    assert report.passed
    assert f"{case.id}:handoff_routing" in report.regressions
    assert report.cases[0].score == pytest.approx(0.9)


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


def test_live_main_sub_trace_only_counts_completed_specialists() -> None:
    delegations = [
        DelegationEvent(
            specialist=SpecialistName.LORE,
            tool_name="lore_specialist",
            status="started",
        ),
        DelegationEvent(
            specialist=SpecialistName.NARRATIVE_PLANNER,
            tool_name="narrative_planner",
            status="failed",
            error="model failure",
        ),
        DelegationEvent(
            specialist=SpecialistName.SCREENWRITER,
            tool_name="screenwriter",
            status="completed",
        ),
        DelegationEvent(
            specialist=SpecialistName.PERFORMANCE,
            tool_name="performance_specialist",
            status="completed",
        ),
        DelegationEvent(
            specialist=SpecialistName.SCREENWRITER,
            tool_name="screenwriter",
            status="completed",
        ),
    ]

    assert _completed_specialists(delegations) == [
        SpecialistName.SCREENWRITER,
        SpecialistName.PERFORMANCE,
    ]


def test_live_director_result_preserves_routing_trace_in_raw_candidate() -> None:
    candidates, errors = load_recorded_baseline()
    assert not errors
    recorded = candidates[0]
    assert recorded.proposal is not None
    assert recorded.metrics is not None
    trace = RoutingTrace(
        decision=RouteDecision(
            intent="greeting",
            objective="回应问候",
            confidence=0.9,
        ),
        final_intent="greeting",
    )
    result = DirectorRunResult(
        proposal=recorded.proposal,
        metrics=recorded.metrics,
        routing_trace=trace,
    )

    _proposal, _metrics, _specialists, _handoffs, routing_trace = _coerce_live_result(
        result,
        1.0,
    )

    assert routing_trace == trace


def test_live_quota_stop_checkpoints_each_completed_case_and_keeps_partial(
    monkeypatch,
    tmp_path,
) -> None:
    cases = load_cases()[:3]
    cases_path = tmp_path / "cases.jsonl"
    cases_path.write_text(
        "\n".join(case.model_dump_json() for case in cases) + "\n",
        encoding="utf-8",
    )
    candidates, errors = load_recorded_baseline()
    assert not errors
    first_proposal = candidates[0].proposal
    assert first_proposal is not None
    calls = 0

    async def fake_run_turn(_request):
        nonlocal calls
        calls += 1
        if calls == 1:
            return first_proposal
        if calls == 2:
            raise ValueError("malformed model response")
        raise RuntimeError("MPE-429 Throttling.AllocationQuota")

    monkeypatch.setenv("OPENAI_API_KEY", "test-only")
    monkeypatch.setattr("eval.runner._load_live_runner", lambda: fake_run_turn)

    write_events: list[tuple[str, int]] = []
    from eval import runner

    original_write_report = runner.write_report

    def tracking_write_report(report, path):
        write_events.append((report.run_status, report.completed_cases))
        original_write_report(report, path)

    monkeypatch.setattr(runner, "write_report", tracking_write_report)
    output = tmp_path / "live.json"

    exit_code = main(
        [
            "--mode",
            "live",
            "--cases",
            str(cases_path),
            "--output",
            str(output),
        ]
    )

    partial = partial_report_path(output)
    assert exit_code == 75
    assert calls == 3
    assert write_events == [("running", 1), ("running", 2), ("stopped", 2)]
    assert not output.exists()
    payload = json.loads(partial.read_text(encoding="utf-8"))
    assert payload["run_status"] == "stopped"
    assert payload["requested_cases"] == 3
    assert payload["completed_cases"] == 2
    assert "Throttling.AllocationQuota" in payload["stop_reason"]
    assert len(payload["candidates"]) == 2
    assert payload["candidates"][0]["proposal"] is not None
    assert "malformed model response" in payload["candidates"][1]["schema_error"]


def test_run_evaluation_exposes_stopped_report_without_checkpoint(monkeypatch) -> None:
    async def quota_failure(_cases, *, checkpoint=None):
        del checkpoint
        raise EvalQuotaStopped(
            "greeting_001",
            [],
            RuntimeError("Throttling.AllocationQuota"),
        )

    monkeypatch.setenv("OPENAI_API_KEY", "test-only")
    monkeypatch.setattr("eval.runner._run_live_cases", quota_failure)

    with pytest.raises(EvalQuotaStopped) as stopped:
        run_evaluation(mode="live")

    assert stopped.value.report is not None
    assert stopped.value.report.run_status == "stopped"
    assert stopped.value.report.completed_cases == 0
    assert not stopped.value.report.passed


def test_successful_live_run_promotes_partial_to_final(monkeypatch, tmp_path) -> None:
    case = load_cases()[0]
    cases_path = tmp_path / "cases.jsonl"
    cases_path.write_text(case.model_dump_json() + "\n", encoding="utf-8")
    candidates, errors = load_recorded_baseline()
    assert not errors
    proposal = candidates[0].proposal
    assert proposal is not None

    async def fake_run_turn(_request):
        return proposal

    monkeypatch.setenv("OPENAI_API_KEY", "test-only")
    monkeypatch.setattr("eval.runner._load_live_runner", lambda: fake_run_turn)
    output = tmp_path / "live.json"

    exit_code = main(
        [
            "--mode",
            "live",
            "--cases",
            str(cases_path),
            "--output",
            str(output),
        ]
    )

    assert exit_code == 0
    assert output.exists()
    assert not partial_report_path(output).exists()
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["run_status"] == "completed"
    assert payload["completed_cases"] == payload["requested_cases"] == 1
