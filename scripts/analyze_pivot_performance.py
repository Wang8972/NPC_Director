from __future__ import annotations

import argparse
import json
import statistics
from pathlib import Path
from typing import Any


def distribution(values: list[float]) -> dict[str, float | int | None]:
    if not values:
        return {"count": 0, "min": None, "p50": None, "p95": None, "max": None, "mean": None}
    ordered = sorted(values)
    return {
        "count": len(ordered),
        "min": ordered[0],
        "p50": statistics.median(ordered),
        "p95": ordered[max(0, int(len(ordered) * 0.95) - 1)],
        "max": ordered[-1],
        "mean": statistics.fmean(ordered),
    }


def analyze(
    report: dict[str, Any],
    *,
    input_rate: float | None,
    cached_input_rate: float | None,
    output_rate: float | None,
) -> dict[str, Any]:
    results = report["results"]
    calls = [
        call for result in results for call in result.get("profile", {}).get("model_calls", [])
    ]
    stage_values: dict[str, list[float]] = {}
    for call in calls:
        stages = dict(call.get("stages_ms", {}))
        if "post_turn_process_exit" not in stages:
            stages["post_turn_process_exit"] = max(
                0.0, float(call["total_ms"]) - sum(float(v) for v in stages.values())
            )
        for name, value in stages.items():
            stage_values.setdefault(name, []).append(float(value))
    stage_distributions = {name: distribution(values) for name, values in stage_values.items()}
    mean_total = statistics.fmean(float(call["total_ms"]) for call in calls)
    ranked = sorted(
        (
            {
                "stage": name,
                "mean_ms": values["mean"],
                "p95_ms": values["p95"],
                "mean_share": (float(values["mean"]) / mean_total if mean_total else 0.0),
            }
            for name, values in stage_distributions.items()
            if values["mean"] is not None
        ),
        key=lambda item: float(item["mean_ms"]),
        reverse=True,
    )
    usage_keys = (
        "input_tokens",
        "cached_input_tokens",
        "cache_write_input_tokens",
        "output_tokens",
        "reasoning_output_tokens",
    )
    usage = {
        key: sum(int(call.get("usage", {}).get(key, 0)) for call in calls) for key in usage_keys
    }
    usage["uncached_input_tokens"] = max(0, usage["input_tokens"] - usage["cached_input_tokens"])
    usage["cache_hit_ratio"] = (
        usage["cached_input_tokens"] / usage["input_tokens"] if usage["input_tokens"] else 0.0
    )
    monetary_cost = None
    if input_rate is not None and cached_input_rate is not None and output_rate is not None:
        monetary_cost = (
            usage["uncached_input_tokens"] * input_rate
            + usage["cached_input_tokens"] * cached_input_rate
            + usage["output_tokens"] * output_rate
        ) / 1_000_000
    fallback_samples = [
        {"case_id": item["case_id"], "trial": item["trial"], "status": item.get("status")}
        for item in results
        if not item.get("profile", {}).get("model_calls")
        and item.get("status") != "input_guard_blocked"
    ]
    return {
        "source_status": report["status"],
        "model": report["model"],
        "sample_count": len(results),
        "successful_model_call_count": len(calls),
        "input_guard_no_model_count": sum(
            item.get("status") == "input_guard_blocked" for item in results
        ),
        "fallback_or_failed_generation_samples": fallback_samples,
        "total_latency_distribution_ms": distribution([float(call["total_ms"]) for call in calls]),
        "stage_distributions_ms": stage_distributions,
        "bottleneck_ranking": ranked,
        "usage": usage,
        "usage_per_successful_model_call": {
            key: value / len(calls) if calls else None
            for key, value in usage.items()
            if key != "cache_hit_ratio"
        },
        "usage_per_eval_sample": {
            key: value / len(results) if results else None
            for key, value in usage.items()
            if key != "cache_hit_ratio"
        },
        "pricing": {
            "input_per_million": input_rate,
            "cached_input_per_million": cached_input_rate,
            "output_per_million": output_rate,
            "estimated_total_cost": monetary_cost,
            "status": "estimated" if monetary_cost is not None else "price_metadata_unavailable",
            "formula": (
                "(uncached_input*input_rate + cached_input*cached_rate + "
                "output*output_rate)/1e6"
            ),
        },
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Analyze Pivot latency and token/cost telemetry")
    parser.add_argument("input", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--input-rate", type=float, default=None)
    parser.add_argument("--cached-input-rate", type=float, default=None)
    parser.add_argument("--output-rate", type=float, default=None)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    report = json.loads(args.input.read_text(encoding="utf-8"))
    analysis = analyze(
        report,
        input_rate=args.input_rate,
        cached_input_rate=args.cached_input_rate,
        output_rate=args.output_rate,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(analysis, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(analysis["bottleneck_ranking"], ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
