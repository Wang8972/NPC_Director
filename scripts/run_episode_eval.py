"""Evaluate production NPC episodes without a Unity or prototype process.

Run from the repository root: python -m scripts.run_episode_eval --mode recorded
Recorded scripts exercise orchestration only. Live mode uses a separate whole-
episode judge and keeps failed/fallback runs in the denominator.
"""

from __future__ import annotations

import argparse
import asyncio
import dataclasses
import json
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from eval.episode_runner import (
    DEFAULT_EPISODE_CASES,
    REPO_ROOT,
    configured_codex_model,
    load_episode_cases,
    run_episode_suite,
)
from npc_director.config import Settings


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument("--cognition", action="store_true")
    result.add_argument("--mode", choices=("recorded", "live"), default="recorded")
    result.add_argument("--transport", choices=("codex", "sdk"), default="sdk")
    result.add_argument("--cases", type=Path, default=DEFAULT_EPISODE_CASES)
    result.add_argument("--case", action="append", dest="case_ids", default=[])
    result.add_argument("--repeats", type=int, default=3)
    result.add_argument("--concurrency", type=int, default=1)
    result.add_argument("--model", help="Defaults to Settings, then current Codex config.")
    result.add_argument("--judge-model", help="Independent judge model; defaults to judge profile.")
    result.add_argument("--call-timeout", type=float, help="Per-model-call timeout in seconds.")
    result.add_argument("--output", type=Path, help="New report path; existing files are rejected.")
    return result


def report_path(mode: str, *, prefix: str = "episodes") -> Path:
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    return REPO_ROOT / "artifacts/director-v2" / f"{prefix}-{mode}-{stamp}-{uuid4().hex[:6]}.json"


def eval_settings(args: argparse.Namespace) -> Settings:
    settings = Settings.from_env()
    updates = {"cognition_enabled": args.cognition or settings.cognition_enabled}
    if args.model:
        updates["model"] = args.model
    elif args.mode == "live" and not settings.model:
        updates["model"] = configured_codex_model()
    if args.judge_model:
        updates["judge_model"] = args.judge_model
    if args.call_timeout is not None:
        if args.call_timeout <= 0:
            raise ValueError("--call-timeout must be positive")
        updates["timeout_seconds"] = args.call_timeout
    settings = dataclasses.replace(settings, **updates)
    settings.validate()
    return settings


async def execute(args: argparse.Namespace) -> tuple[dict, Path]:
    cases = load_episode_cases(args.cases)
    if args.case_ids:
        known = {case.id for case in cases}
        unknown = set(args.case_ids) - known
        if unknown:
            raise ValueError(f"unknown case IDs: {sorted(unknown)}")
        cases = [case for case in cases if case.id in args.case_ids]
    output = args.output or report_path(args.mode)

    def progress(result: dict) -> None:
        print(
            json.dumps(
                {
                    "case": result["case_id"],
                    "repeat": result["repeat"],
                    "structural_passed": result["structural_passed"],
                    "goal_passed": result["goal_passed"],
                    "fallback_count": result["fallback_count"],
                },
                ensure_ascii=False,
            ),
            flush=True,
        )

    report = await run_episode_suite(
        cases,
        repeats=args.repeats,
        mode=args.mode,
        settings=eval_settings(args),
        transport=args.transport,
        judge_model=args.judge_model,
        output_path=output,
        progress=progress,
        concurrency=args.concurrency,
    )
    print(
        json.dumps(
            {"report": str(output), "summary": report["summary"]}, ensure_ascii=False, indent=2
        ),
        flush=True,
    )
    return report, output


def main() -> int:
    args = parser().parse_args()
    report, _ = asyncio.run(execute(args))
    summary = report["summary"]
    passed = (
        summary["meets_live_acceptance"]
        if args.mode == "live"
        else summary["structural_passes"] == summary["runs"]
    )
    return 0 if passed and not report.get("budget_exhausted") else 1


if __name__ == "__main__":
    raise SystemExit(main())
