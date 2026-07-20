from __future__ import annotations

import argparse
import json
from pathlib import Path

from pydantic import BaseModel, ConfigDict

from eval.metrics import evaluate_suite
from eval.models import Architecture
from eval.runner import load_cases, load_recorded_baseline


class AblationModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class VariantSpec(AblationModel):
    name: str
    baseline_path: Path
    architecture: Architecture = "single_agent"


class VariantSummary(AblationModel):
    name: str
    passed: bool
    case_pass_rate: float
    quality_pass_rate: float
    schema_pass_rate: float
    specialist_routing_pass_rate: float | None
    handoff_routing_pass_rate: float | None
    routing_failure_rate: float | None
    average_latency_ms: float | None
    p95_latency_ms: float | None
    average_tokens: float | None
    average_cost_usd: float | None
    regressions: list[str]


class AblationReport(AblationModel):
    cases: int
    variants: list[VariantSummary]


def run_ablation_suite(cases_path: Path, variants: list[VariantSpec]) -> AblationReport:
    cases = load_cases(cases_path)
    summaries = []
    for variant in variants:
        candidates, dataset_errors = load_recorded_baseline(variant.baseline_path)
        report = evaluate_suite(
            cases,
            candidates,
            mode="recorded",
            architecture=variant.architecture,
            dataset_errors=dataset_errors,
        )
        specialist_routing = report.quality.by_check.get("specialist_routing")
        handoff_routing = report.quality.by_check.get("handoff_routing")
        routing_total = sum(
            summary.total
            for summary in (specialist_routing, handoff_routing)
            if summary is not None
        )
        routing_failures = sum(
            summary.failed
            for summary in (specialist_routing, handoff_routing)
            if summary is not None
        )
        summaries.append(
            VariantSummary(
                name=variant.name,
                passed=report.passed,
                case_pass_rate=report.quality.case_pass_rate,
                quality_pass_rate=report.quality.pass_rate,
                schema_pass_rate=report.schema_summary.pass_rate,
                specialist_routing_pass_rate=(
                    specialist_routing.pass_rate if specialist_routing is not None else None
                ),
                handoff_routing_pass_rate=(
                    handoff_routing.pass_rate if handoff_routing is not None else None
                ),
                routing_failure_rate=(
                    round(routing_failures / routing_total, 6) if routing_total else None
                ),
                average_latency_ms=report.system.latency.average_ms,
                p95_latency_ms=report.system.latency.p95_ms,
                average_tokens=report.system.tokens.average_total,
                average_cost_usd=report.system.cost.average_usd,
                regressions=report.regressions,
            )
        )
    return AblationReport(cases=len(cases), variants=summaries)


def _variant(value: str) -> VariantSpec:
    try:
        name, architecture, path = value.split("=", maxsplit=2)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("variant must be NAME=ARCHITECTURE=PATH") from exc
    if architecture not in {"single_agent", "main_sub"}:
        raise argparse.ArgumentTypeError("architecture must be single_agent or main_sub")
    return VariantSpec(name=name, architecture=architecture, baseline_path=Path(path))


def main() -> int:
    parser = argparse.ArgumentParser(description="Compare recorded NPC Director variants")
    parser.add_argument("--cases", type=Path, required=True)
    parser.add_argument("--variant", type=_variant, action="append", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = run_ablation_suite(args.cases, args.variant)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report.model_dump(mode="json"), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
