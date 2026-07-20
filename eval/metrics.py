from __future__ import annotations

import math
import unicodedata
from collections import Counter, defaultdict
from collections.abc import Iterable, Sequence

from eval.models import (
    Architecture,
    CandidateResult,
    CaseResult,
    CheckResult,
    CostSummary,
    EvalCase,
    EvalReport,
    LatencySummary,
    QualitySummary,
    RateSummary,
    RunMode,
    SchemaSummary,
    SystemSummary,
    TokenSummary,
)
from npc_director.contracts import GenerationMetrics, extract_state_change_paths


def _rate(passed: int, total: int) -> float:
    return round(passed / total, 6) if total else 0.0


def _normalize_text(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value).casefold()
    return " ".join(normalized.split())


def _semantic_checks(
    case: EvalCase,
    candidate: CandidateResult,
    architecture: Architecture,
) -> list[CheckResult]:
    if candidate.proposal is None:
        raise ValueError("semantic checks require a parsed proposal")
    proposal = candidate.proposal
    expectation = case.expect
    plan = proposal.plan
    performance = proposal.performance

    checks = [
        CheckResult(
            name="intent",
            passed=plan.intent == expectation.intent,
            expected=expectation.intent.value,
            actual=plan.intent.value,
        )
    ]

    expected_emotion = expectation.emotion.model_dump(mode="json")
    actual_emotion = {
        "coarse": performance.emotion.coarse.value,
        "primary": performance.emotion.primary.value,
        "secondary": (
            performance.emotion.secondary.value if performance.emotion.secondary else None
        ),
    }
    checks.append(
        CheckResult(
            name="emotion",
            passed=(
                performance.emotion.coarse in expectation.emotion.coarse
                and performance.emotion.primary in expectation.emotion.primary
                and (
                    not expectation.emotion.secondary
                    or performance.emotion.secondary in expectation.emotion.secondary
                )
            ),
            expected=expected_emotion,
            actual=actual_emotion,
        )
    )

    allowed_actions = set(expectation.allowed_actions)
    actual_actions = [cue.action for cue in performance.body_cues]
    disallowed_actions = sorted(
        action.value for action in actual_actions if action not in allowed_actions
    )
    checks.append(
        CheckResult(
            name="action_allowlist",
            passed=not disallowed_actions,
            expected=sorted(action.value for action in allowed_actions),
            actual=[action.value for action in actual_actions],
            detail=(
                f"disallowed actions: {', '.join(disallowed_actions)}"
                if disallowed_actions
                else None
            ),
        )
    )

    allowed_paths = set(expectation.state_patch_allowlist)
    actual_paths = extract_state_change_paths(plan.proposed_state_changes)
    disallowed_paths = sorted(actual_paths - allowed_paths)
    checks.append(
        CheckResult(
            name="state_patch_allowlist",
            passed=not disallowed_paths,
            expected=sorted(allowed_paths),
            actual=sorted(actual_paths),
            detail=(
                f"disallowed state paths: {', '.join(disallowed_paths)}"
                if disallowed_paths
                else None
            ),
        )
    )

    dialogue = _normalize_text(performance.dialogue.text)
    missing_text = [
        fragment
        for fragment in expectation.required_text
        if _normalize_text(fragment) not in dialogue
    ]
    checks.append(
        CheckResult(
            name="required_text",
            passed=not missing_text,
            expected=expectation.required_text,
            actual=missing_text,
            detail=(f"missing text: {', '.join(missing_text)}" if missing_text else None),
        )
    )

    present_forbidden_text = [
        fragment for fragment in expectation.forbidden_text if _normalize_text(fragment) in dialogue
    ]
    checks.append(
        CheckResult(
            name="forbidden_text",
            passed=not present_forbidden_text,
            expected=expectation.forbidden_text,
            actual=present_forbidden_text,
            detail=(
                f"forbidden text present: {', '.join(present_forbidden_text)}"
                if present_forbidden_text
                else None
            ),
        )
    )

    actual_specialists = set(candidate.specialists_called or [])
    routing_expected = {
        "required": sorted(item.value for item in expectation.required_specialists),
        "optional": sorted(item.value for item in expectation.optional_specialists),
        "forbidden": sorted(item.value for item in expectation.forbidden_specialists),
    }
    if architecture == "single_agent":
        checks.append(
            CheckResult(
                name="specialist_routing",
                passed=True,
                applicable=False,
                expected=routing_expected,
                actual=sorted(item.value for item in actual_specialists),
                detail="future specialist routing is not scored for single_agent",
            )
        )
        checks.append(
            CheckResult(
                name="handoff_routing",
                passed=True,
                applicable=False,
                expected=expectation.required_handoff,
                actual=candidate.handoffs or [],
                detail="handoff routing is not scored for single_agent",
            )
        )
    else:
        required = set(expectation.required_specialists)
        optional = set(expectation.optional_specialists)
        forbidden = set(expectation.forbidden_specialists)
        missing_trace = candidate.specialists_called is None
        missing = sorted(item.value for item in required - actual_specialists)
        forbidden_called = sorted(item.value for item in forbidden & actual_specialists)
        unexpected = sorted(
            item.value for item in actual_specialists - required - optional - forbidden
        )
        routing_passed = (
            not missing_trace and not missing and not forbidden_called and not unexpected
        )
        details = []
        if missing_trace:
            details.append("actual specialist trace is missing")
        if missing:
            details.append(f"missing: {', '.join(missing)}")
        if forbidden_called:
            details.append(f"forbidden: {', '.join(forbidden_called)}")
        if unexpected:
            details.append(f"unexpected: {', '.join(unexpected)}")
        checks.append(
            CheckResult(
                name="specialist_routing",
                passed=routing_passed,
                expected=routing_expected,
                actual=sorted(item.value for item in actual_specialists),
                detail="; ".join(details) or None,
            )
        )

        actual_handoffs = candidate.handoffs or []
        required_handoff = expectation.required_handoff
        missing_handoff_trace = candidate.handoffs is None
        missing_handoff = required_handoff is not None and required_handoff not in actual_handoffs
        unexpected_handoffs = sorted(
            handoff for handoff in actual_handoffs if handoff != required_handoff
        )
        handoff_details = []
        if missing_handoff_trace:
            handoff_details.append("actual handoff trace is missing")
        if missing_handoff:
            handoff_details.append(f"missing: {required_handoff}")
        if unexpected_handoffs:
            handoff_details.append(f"unexpected: {', '.join(unexpected_handoffs)}")
        checks.append(
            CheckResult(
                name="handoff_routing",
                passed=(
                    not missing_handoff_trace and not missing_handoff and not unexpected_handoffs
                ),
                expected=required_handoff,
                actual=actual_handoffs,
                detail="; ".join(handoff_details) or None,
            )
        )

    return checks


def evaluate_candidate(
    case: EvalCase,
    candidate: CandidateResult | None,
    architecture: Architecture,
) -> CaseResult:
    schema_error = "missing result" if candidate is None else candidate.schema_error
    proposal = None if candidate is None else candidate.proposal
    metrics = None if candidate is None else candidate.metrics
    schema_passed = proposal is not None and metrics is not None and schema_error is None
    if schema_error is None and proposal is not None and metrics is None:
        schema_error = "missing GenerationMetrics"
    checks = [
        CheckResult(
            name="schema",
            passed=schema_passed,
            expected="valid TurnProposal and GenerationMetrics",
            actual="valid" if schema_passed else schema_error or "missing TurnProposal",
        )
    ]
    if proposal is not None:
        checks.extend(_semantic_checks(case, candidate, architecture))
    passed = all(check.passed for check in checks if check.applicable)
    return CaseResult(id=case.id, passed=passed, checks=checks)


def _nearest_rank(values: Sequence[float], percentile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = max(0, math.ceil(percentile * len(ordered)) - 1)
    return ordered[index]


def _system_summary(metrics: Iterable[GenerationMetrics]) -> SystemSummary:
    rows = list(metrics)
    latencies = [row.latency_ms for row in rows]
    costs = [row.estimated_cost_usd for row in rows if row.estimated_cost_usd is not None]
    model_counts = Counter(row.model or "unknown" for row in rows)

    average_latency = sum(latencies) / len(latencies) if latencies else None
    input_total = sum(row.input_tokens for row in rows)
    output_total = sum(row.output_tokens for row in rows)
    token_total = sum(row.total_tokens for row in rows)
    average_tokens = token_total / len(rows) if rows else None
    cost_total = sum(costs) if costs else None
    average_cost = cost_total / len(costs) if cost_total is not None else None

    return SystemSummary(
        latency=LatencySummary(
            count=len(latencies),
            average_ms=round(average_latency, 3) if average_latency is not None else None,
            p50_ms=_nearest_rank(latencies, 0.50),
            p95_ms=_nearest_rank(latencies, 0.95),
            max_ms=max(latencies) if latencies else None,
        ),
        tokens=TokenSummary(
            count=len(rows),
            input_total=input_total,
            output_total=output_total,
            total=token_total,
            average_total=round(average_tokens, 3) if average_tokens is not None else None,
        ),
        cost=CostSummary(
            available_count=len(costs),
            total_usd=round(cost_total, 8) if cost_total is not None else None,
            average_usd=round(average_cost, 8) if average_cost is not None else None,
        ),
        models=dict(sorted(model_counts.items())),
    )


def _quality_summary(case_results: Sequence[CaseResult]) -> QualitySummary:
    checks = [
        check
        for result in case_results
        for check in result.checks
        if check.applicable and check.name != "schema"
    ]
    grouped: dict[str, list[CheckResult]] = defaultdict(list)
    for check in checks:
        grouped[check.name].append(check)

    by_check = {}
    for name, items in sorted(grouped.items()):
        passed = sum(item.passed for item in items)
        by_check[name] = RateSummary(
            total=len(items),
            passed=passed,
            failed=len(items) - passed,
            pass_rate=_rate(passed, len(items)),
        )

    passed_checks = sum(check.passed for check in checks)
    passed_cases = sum(result.passed for result in case_results)
    return QualitySummary(
        total_checks=len(checks),
        passed_checks=passed_checks,
        failed_checks=len(checks) - passed_checks,
        pass_rate=_rate(passed_checks, len(checks)),
        passed_cases=passed_cases,
        failed_cases=len(case_results) - passed_cases,
        case_pass_rate=_rate(passed_cases, len(case_results)),
        by_check=by_check,
    )


def evaluate_suite(
    cases: Sequence[EvalCase],
    candidates: Sequence[CandidateResult],
    *,
    mode: RunMode,
    architecture: Architecture = "single_agent",
    dataset_errors: Sequence[str] = (),
) -> EvalReport:
    candidates_by_id = {candidate.id: candidate for candidate in candidates}
    expected_ids = {case.id for case in cases}
    unexpected_ids = sorted(set(candidates_by_id) - expected_ids)
    all_dataset_errors = list(dataset_errors)
    all_dataset_errors.extend(f"unexpected result id: {case_id}" for case_id in unexpected_ids)

    case_results = [
        evaluate_candidate(case, candidates_by_id.get(case.id), architecture) for case in cases
    ]
    schema_checks = [result.checks[0] for result in case_results]
    valid_schemas = sum(check.passed for check in schema_checks)
    schema_errors = [
        f"{result.id}: {result.checks[0].actual}"
        for result in case_results
        if not result.checks[0].passed
    ]
    schema_errors.extend(all_dataset_errors)

    quality = _quality_summary(case_results)
    failed_cases = [result.id for result in case_results if not result.passed]
    regressions = [
        f"{result.id}:{check.name}"
        for result in case_results
        for check in result.checks
        if check.applicable and not check.passed
    ]
    regressions.extend(f"dataset:{error}" for error in all_dataset_errors)

    report_metrics = [
        candidate.metrics
        for candidate in candidates
        if candidate.id in expected_ids and candidate.metrics is not None
    ]
    return EvalReport(
        mode=mode,
        architecture=architecture,
        passed=not failed_cases and not all_dataset_errors,
        total_cases=len(cases),
        passed_cases=len(cases) - len(failed_cases),
        failed_cases=failed_cases,
        regressions=regressions,
        schema_summary=SchemaSummary(
            total=len(schema_checks),
            passed=valid_schemas,
            failed=len(schema_checks) - valid_schemas,
            pass_rate=_rate(valid_schemas, len(schema_checks)),
            errors=schema_errors,
        ),
        quality=quality,
        system=_system_summary(report_metrics),
        dataset_errors=all_dataset_errors,
        cases=case_results,
    )
