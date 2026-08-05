from __future__ import annotations

import argparse
import asyncio
import dataclasses
import inspect
import json
import os
import sys
import tempfile
import time
from collections.abc import Awaitable, Callable, Sequence
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from eval.metrics import evaluate_suite
from eval.models import (
    Architecture,
    CandidateResult,
    EvalCase,
    EvalReport,
    RecordedBaseline,
    RunMode,
)
from npc_director.contracts import (
    CheckStatus,
    DirectorRunResult,
    GenerationMetrics,
    NPCDomainState,
    PerformanceDraft,
    RoutingTrace,
    SpecialistName,
    TurnProposal,
    TurnRequest,
    TurnRunResult,
)
from npc_director.governance import (
    INPUT_GUARD_VERSION,
    build_safe_input_proposal,
    check_input,
)
from npc_director.model_profile import get_active_profile, is_allocation_quota_error

EVAL_DIR = Path(__file__).resolve().parent
DEFAULT_CASES_PATH = EVAL_DIR / "cases" / "golden.jsonl"
DEFAULT_BASELINE_PATH = EVAL_DIR / "baselines" / "recorded.jsonl"
DEFAULT_REPORT_PATH = EVAL_DIR / "reports" / "latest.json"


class EvalConfigurationError(RuntimeError):
    """Raised when an evaluation source or runtime is unavailable."""


class EvalQuotaStopped(RuntimeError):
    """Stops a live suite without turning unattempted cases into failures."""

    def __init__(
        self,
        case_id: str,
        candidates: Sequence[CandidateResult],
        cause: BaseException,
    ) -> None:
        self.case_id = case_id
        self.candidates = list(candidates)
        self.stop_reason = (
            f"allocation quota exhausted before {case_id}: "
            f"{type(cause).__name__}: {cause}"
        )
        self.report: EvalReport | None = None
        super().__init__(self.stop_reason)


class EvalCheckpointError(RuntimeError):
    """Raised when durable live-eval progress cannot be written."""


CandidateCheckpoint = Callable[[Sequence[CandidateResult]], None]


def _read_jsonl(path: Path) -> list[tuple[int, Any]]:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        raise EvalConfigurationError(f"cannot read JSONL file {path}: {exc}") from exc

    rows = []
    for line_number, line in enumerate(lines, start=1):
        if not line.strip():
            continue
        try:
            rows.append((line_number, json.loads(line)))
        except json.JSONDecodeError as exc:
            raise EvalConfigurationError(
                f"invalid JSON in {path}:{line_number}: {exc.msg}"
            ) from exc
    return rows


def load_cases(path: Path = DEFAULT_CASES_PATH) -> list[EvalCase]:
    cases = []
    seen_ids: set[str] = set()
    for line_number, payload in _read_jsonl(path):
        try:
            case = EvalCase.model_validate(payload)
        except ValidationError as exc:
            raise EvalConfigurationError(
                f"invalid golden case in {path}:{line_number}: {exc}"
            ) from exc
        if case.id in seen_ids:
            raise EvalConfigurationError(f"duplicate golden case id {case.id!r} in {path}")
        seen_ids.add(case.id)
        cases.append(case)
    if not cases:
        raise EvalConfigurationError(f"no golden cases found in {path}")
    return cases


def load_recorded_baseline(
    path: Path = DEFAULT_BASELINE_PATH,
) -> tuple[list[CandidateResult], list[str]]:
    candidates = []
    errors = []
    seen_ids: set[str] = set()
    for line_number, payload in _read_jsonl(path):
        if not isinstance(payload, dict):
            errors.append(f"{path}:{line_number}: baseline row must be an object")
            continue
        case_id = payload.get("id")
        if not isinstance(case_id, str) or not case_id:
            errors.append(f"{path}:{line_number}: missing non-empty id")
            continue
        if case_id in seen_ids:
            errors.append(f"{path}:{line_number}: duplicate baseline id {case_id!r}")
            continue
        seen_ids.add(case_id)

        try:
            baseline = RecordedBaseline.model_validate(payload)
        except ValidationError as exc:
            proposal = None
            metrics = None
            proposal_error = None
            metrics_error = None
            try:
                proposal = TurnProposal.model_validate(payload.get("proposal"))
            except ValidationError as proposal_exc:
                proposal_error = f"TurnProposal: {proposal_exc.errors(include_url=False)}"
            try:
                metrics = GenerationMetrics.model_validate(payload.get("metrics"))
            except ValidationError as metrics_exc:
                metrics_error = f"GenerationMetrics: {metrics_exc.errors(include_url=False)}"
            details = "; ".join(item for item in (proposal_error, metrics_error) if item)
            candidates.append(
                CandidateResult(
                    id=case_id,
                    proposal=proposal,
                    metrics=metrics,
                    specialists_called=None,
                    handoffs=None,
                    schema_error=details or str(exc),
                )
            )
            continue

        candidates.append(
            CandidateResult(
                id=baseline.id,
                proposal=baseline.proposal,
                metrics=baseline.metrics,
                specialists_called=baseline.specialists_called,
                handoffs=baseline.handoffs,
            )
        )
    return candidates, errors


def _proposal_from_run_result(result: TurnRunResult) -> TurnProposal:
    performance_payload = result.directive.model_dump(
        include=set(PerformanceDraft.model_fields),
        mode="python",
    )
    return TurnProposal(
        plan=result.plan,
        performance=PerformanceDraft.model_validate(performance_payload),
    )


def _coerce_live_result(
    result: Any,
    elapsed_ms: float,
) -> tuple[
    TurnProposal,
    GenerationMetrics,
    list[SpecialistName] | None,
    list[str] | None,
    RoutingTrace | None,
]:
    if isinstance(result, DirectorRunResult):
        return (
            result.proposal,
            result.metrics,
            _completed_specialists(result.delegations),
            result.handoffs,
            result.routing_trace,
        )
    if isinstance(result, TurnRunResult):
        return (
            _proposal_from_run_result(result),
            result.metrics,
            result.directive.runtime_meta.specialists_called,
            None,
            None,
        )
    if isinstance(result, TurnProposal):
        return result, GenerationMetrics(latency_ms=elapsed_ms), None, None, None
    try:
        run_result = TurnRunResult.model_validate(result)
    except ValidationError:
        proposal = TurnProposal.model_validate(result)
        return proposal, GenerationMetrics(latency_ms=elapsed_ms), None, None, None
    return (
        _proposal_from_run_result(run_result),
        run_result.metrics,
        run_result.directive.runtime_meta.specialists_called,
        None,
        None,
    )


def _completed_specialists(delegations: Sequence[Any]) -> list[SpecialistName]:
    completed: list[SpecialistName] = []
    for event in delegations:
        if event.status != "completed" or event.specialist in completed:
            continue
        completed.append(event.specialist)
    return completed


def _load_live_runner() -> Callable[[TurnRequest], Awaitable[Any] | Any]:
    try:
        from npc_director.orchestration.run_turn import run_turn
    except (ImportError, AttributeError) as exc:
        raise EvalConfigurationError(
            "live mode requires npc_director.orchestration.run_turn.run_turn; "
            "the M1 live orchestration dependency is not available"
        ) from exc
    if not callable(run_turn):
        raise EvalConfigurationError(
            "npc_director.orchestration.run_turn.run_turn exists but is not callable"
        )
    return run_turn


async def _pace_live_cases() -> None:
    delay = float(os.getenv("NPC_DIRECTOR_EVAL_CASE_INTERVAL_SECONDS", "0"))
    if delay > 0:
        await asyncio.sleep(delay)


async def _call_with_throttle_retry(invoke: Callable[[], Awaitable[Any]]) -> Any:
    """Retry transient gateway failures using the active model profile's policy."""
    retry_policy = get_active_profile().retry
    attempts = int(os.getenv("NPC_DIRECTOR_EVAL_THROTTLE_RETRIES", str(retry_policy.max_attempts)))
    backoff_override = os.getenv("NPC_DIRECTOR_EVAL_THROTTLE_BACKOFF_SECONDS", "").strip()
    for attempt in range(attempts + 1):
        try:
            return await invoke()
        except Exception as exc:
            if is_allocation_quota_error(exc):
                raise
            if attempt >= attempts or not retry_policy.is_retryable(exc):
                raise
            if backoff_override:
                delay = float(backoff_override) * (attempt + 1)
            else:
                delay = retry_policy.backoff_seconds(attempt)
            await asyncio.sleep(delay)


def _append_candidate(
    candidates: list[CandidateResult],
    candidate: CandidateResult,
    checkpoint: CandidateCheckpoint | None,
) -> None:
    candidates.append(candidate)
    if checkpoint is not None:
        try:
            checkpoint(tuple(candidates))
        except Exception as exc:
            raise EvalCheckpointError(f"cannot persist eval checkpoint: {exc}") from exc


async def _run_live_cases(
    cases: Sequence[EvalCase],
    *,
    checkpoint: CandidateCheckpoint | None = None,
) -> list[CandidateResult]:
    run_turn = _load_live_runner()
    candidates = []
    for index, case in enumerate(cases):
        if index:
            await _pace_live_cases()
        started = time.perf_counter()
        try:

            async def _invoke(current_case: EvalCase = case):
                result = run_turn(current_case.input)
                if inspect.isawaitable(result):
                    result = await result
                return result

            result = await _call_with_throttle_retry(_invoke)
            elapsed_ms = (time.perf_counter() - started) * 1_000
            proposal, metrics, specialists_called, handoffs, routing_trace = (
                _coerce_live_result(result, elapsed_ms)
            )
            _append_candidate(
                candidates,
                CandidateResult(
                    id=case.id,
                    proposal=proposal,
                    metrics=metrics,
                    specialists_called=specialists_called,
                    handoffs=handoffs,
                    routing_trace=routing_trace,
                ),
                checkpoint,
            )
        except Exception as exc:
            if isinstance(exc, EvalCheckpointError):
                raise
            if is_allocation_quota_error(exc):
                raise EvalQuotaStopped(case.id, candidates, exc) from exc
            _append_candidate(
                candidates,
                CandidateResult(
                    id=case.id,
                    schema_error=f"live run failed: {type(exc).__name__}: {exc}",
                ),
                checkpoint,
            )
    return candidates


async def _run_live_main_sub_cases(
    cases: Sequence[EvalCase],
    *,
    checkpoint: CandidateCheckpoint | None = None,
) -> list[CandidateResult]:
    from npc_director.config import Settings
    from npc_director.orchestration.context_adapter import DefaultContextBuilder
    from npc_director.orchestration.emotion_policy import correct_emotion
    from npc_director.orchestration.executor import ResilientDirectorExecutor
    from npc_director.rag import CachedLoreRetriever, LexicalLoreIndex, LexicalLoreRetriever

    with tempfile.TemporaryDirectory() as temporary_directory:
        settings = dataclasses.replace(
            Settings.from_env(),
            database_path=Path(temporary_directory) / "eval.db",
        )
        lore_retriever = CachedLoreRetriever(
            LexicalLoreRetriever(LexicalLoreIndex.from_directory(settings.lore_path))
        )
        context_builder = DefaultContextBuilder(
            lore_retriever=lore_retriever,
            character_root=settings.character_path,
            settings=settings,
            lore_top_k=settings.lore_top_k,
            lore_token_budget=settings.lore_token_budget,
            history_limit=settings.context_history_limit,
        )
        executor = ResilientDirectorExecutor(settings, lore_retriever=lore_retriever)
        candidates = []
        for index, case in enumerate(cases):
            if index:
                await _pace_live_cases()
            try:
                guard = check_input(case.input)
                if guard.status is CheckStatus.FAIL:
                    _append_candidate(
                        candidates,
                        CandidateResult(
                            id=case.id,
                            proposal=build_safe_input_proposal(case.input),
                            metrics=GenerationMetrics(
                                model=INPUT_GUARD_VERSION,
                                latency_ms=0,
                            ),
                            specialists_called=[],
                            handoffs=[],
                        ),
                        checkpoint,
                    )
                    continue
                built = await context_builder.build(
                    case.input,
                    NPCDomainState(npc_id=case.input.npc_id),
                )
                result = await _call_with_throttle_retry(
                    lambda built=built: executor.generate(built.director_input)
                )
                # Mirror the service-layer post-processing chain so live eval
                # sees the same proposals Unity would receive.
                proposal = correct_emotion(
                    get_active_profile().normalizer.normalize(result.proposal)
                )
                _append_candidate(
                    candidates,
                    CandidateResult(
                        id=case.id,
                        proposal=proposal,
                        metrics=result.metrics,
                        specialists_called=_completed_specialists(result.delegations),
                        handoffs=result.handoffs,
                        routing_trace=result.routing_trace,
                    ),
                    checkpoint,
                )
            except Exception as exc:
                if isinstance(exc, EvalCheckpointError):
                    raise
                if is_allocation_quota_error(exc):
                    raise EvalQuotaStopped(case.id, candidates, exc) from exc
                _append_candidate(
                    candidates,
                    CandidateResult(
                        id=case.id,
                        schema_error=(f"live main-sub run failed: {type(exc).__name__}: {exc}"),
                    ),
                    checkpoint,
                )
        return candidates


def run_evaluation(
    *,
    mode: RunMode = "recorded",
    cases_path: Path = DEFAULT_CASES_PATH,
    baseline_path: Path = DEFAULT_BASELINE_PATH,
    architecture: Architecture = "single_agent",
    checkpoint_path: Path | None = None,
) -> EvalReport:
    cases = load_cases(Path(cases_path))
    if mode == "recorded":
        candidates, dataset_errors = load_recorded_baseline(Path(baseline_path))
    elif mode == "live":
        if not os.getenv("OPENAI_API_KEY", "").strip():
            raise EvalConfigurationError("live mode requires OPENAI_API_KEY")
        checkpoint = None
        if checkpoint_path is not None:

            def checkpoint(completed: Sequence[CandidateResult]) -> None:
                completed_cases = cases[: len(completed)]
                partial_report = evaluate_suite(
                    completed_cases,
                    completed,
                    mode=mode,
                    architecture=architecture,
                    run_status="running",
                    requested_cases=len(cases),
                    completed_cases=len(completed),
                )
                write_report(partial_report, checkpoint_path)

        try:
            candidates = asyncio.run(
                _run_live_main_sub_cases(cases, checkpoint=checkpoint)
                if architecture == "main_sub"
                else _run_live_cases(cases, checkpoint=checkpoint)
            )
        except EvalQuotaStopped as exc:
            completed_cases = cases[: len(exc.candidates)]
            exc.report = evaluate_suite(
                completed_cases,
                exc.candidates,
                mode=mode,
                architecture=architecture,
                run_status="stopped",
                requested_cases=len(cases),
                completed_cases=len(exc.candidates),
                stop_reason=exc.stop_reason,
            )
            if checkpoint_path is not None:
                write_report(exc.report, checkpoint_path)
            raise
        dataset_errors = []
    else:
        raise EvalConfigurationError(f"unsupported mode: {mode}")
    return evaluate_suite(
        cases,
        candidates,
        mode=mode,
        architecture=architecture,
        dataset_errors=dataset_errors,
    )


def write_report(report: EvalReport, path: Path) -> None:
    """Atomically replace one report so interrupted writes never corrupt it."""

    path.parent.mkdir(parents=True, exist_ok=True)
    payload = report.model_dump(mode="json", by_alias=True)
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            temporary_path = Path(handle.name)
            json.dump(payload, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_path, path)
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)


def partial_report_path(path: Path) -> Path:
    suffix = path.suffix
    return path.with_name(f"{path.stem}_partial{suffix}")


def promote_completed_report(report: EvalReport, output: Path, partial: Path) -> None:
    """Write completed metadata to the checkpoint, then promote it to final."""

    write_report(report, partial)
    os.replace(partial, output)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run NPC Director golden evaluations")
    parser.add_argument("--mode", choices=("recorded", "live"), default="recorded")
    parser.add_argument(
        "--architecture",
        "--variant",
        choices=("single_agent", "main_sub"),
        default="single_agent",
        help="single_agent skips future specialist-routing expectations",
    )
    parser.add_argument("--cases", type=Path, default=DEFAULT_CASES_PATH)
    parser.add_argument("--baseline", type=Path, default=DEFAULT_BASELINE_PATH)
    parser.add_argument("--output", type=Path, default=DEFAULT_REPORT_PATH)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    checkpoint_path = partial_report_path(args.output) if args.mode == "live" else None
    try:
        report = run_evaluation(
            mode=args.mode,
            cases_path=args.cases,
            baseline_path=args.baseline,
            architecture=args.architecture,
            checkpoint_path=checkpoint_path,
        )
        if checkpoint_path is None:
            write_report(report, args.output)
        else:
            promote_completed_report(report, args.output, checkpoint_path)
    except EvalConfigurationError as exc:
        print(f"configuration error: {exc}", file=sys.stderr)
        return 2
    except EvalQuotaStopped as exc:
        if exc.report is not None:
            print(
                json.dumps(
                    exc.report.model_dump(mode="json", by_alias=True),
                    ensure_ascii=False,
                    indent=2,
                )
            )
        print(
            f"live evaluation stopped: {exc.stop_reason}; partial report: {checkpoint_path}",
            file=sys.stderr,
        )
        return 75

    print(json.dumps(report.model_dump(mode="json", by_alias=True), ensure_ascii=False, indent=2))
    return 0 if report.passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
