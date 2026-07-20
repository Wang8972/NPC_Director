from __future__ import annotations

from collections.abc import Sequence

from npc_director.contracts import (
    CheckResult,
    CheckSeverity,
    CheckStatus,
    DecisionAction,
    FinalizationDecision,
    PerformanceDirective,
    RuntimeMeta,
    SpecialistName,
    TurnProposal,
    TurnRequest,
    TurnStateRecord,
)

FINALIZER_PROMPT_VERSION = "finalizer-v1"
HARD_REJECT_CHECKS = frozenset(
    {
        "input_guard",
        "state_patch_permissions",
        "tool_permissions",
        "schema",
    }
)


def finalize_proposal(
    request: TurnRequest,
    proposal: TurnProposal,
    *,
    specialists_called: Sequence[SpecialistName | str],
    prompt_versions: Sequence[str],
    model: str | None,
    trace_id: str | None = None,
    response_id: str | None = None,
) -> PerformanceDirective:
    """Add runtime-owned identity and trace data to model-authored content."""
    specialists = [SpecialistName(value) for value in specialists_called]
    return PerformanceDirective(
        schema_version="1.0",
        session_id=request.session_id,
        turn_id=request.turn_id,
        npc_id=request.npc_id,
        runtime_meta=RuntimeMeta(
            specialists_called=specialists,
            prompt_versions=list(prompt_versions),
            model=model,
            trace_id=trace_id,
            response_id=response_id,
        ),
        **proposal.performance.model_dump(),
    )


def finalize_baseline_proposal(
    request: TurnRequest,
    proposal: TurnProposal,
    *,
    prompt_version: str,
    model: str | None,
    trace_id: str | None = None,
    response_id: str | None = None,
) -> PerformanceDirective:
    """Add trusted runtime fields outside the model-authored proposal."""
    return finalize_proposal(
        request,
        proposal,
        specialists_called=[SpecialistName.BASELINE],
        prompt_versions=[prompt_version],
        model=model,
        trace_id=trace_id,
        response_id=response_id,
    )


def _check_reason(check: CheckResult) -> str:
    detail = check.reason or check.status.value
    return f"{check.name}: {detail}"


def _repair_feedback(checks: Sequence[CheckResult]) -> str:
    feedback = [
        f"{check.name}: {check.repair_hint or check.reason}"
        for check in checks
        if check.status is CheckStatus.FAIL
    ]
    return "\n".join(feedback)[:2_000]


class Finalizer:
    """Deterministic policy gate; repair-attempt limits remain caller-owned."""

    def __init__(self, *, low_confidence_threshold: float = 0.55) -> None:
        if not 0 <= low_confidence_threshold <= 1:
            raise ValueError("low_confidence_threshold must be between 0 and 1")
        self.low_confidence_threshold = low_confidence_threshold

    def decide(
        self,
        proposal: TurnProposal,
        checks: Sequence[CheckResult],
        turn: TurnRequest | TurnStateRecord,
        *,
        specialists_called: Sequence[SpecialistName | str] = (SpecialistName.BASELINE,),
        prompt_versions: Sequence[str] = (FINALIZER_PROMPT_VERSION,),
        model: str | None = None,
        trace_id: str | None = None,
        response_id: str | None = None,
    ) -> FinalizationDecision:
        request = turn.request if isinstance(turn, TurnStateRecord) else turn
        failed = [check for check in checks if check.status is CheckStatus.FAIL]
        hard_rejections = [check for check in failed if check.name in HARD_REJECT_CHECKS]
        if hard_rejections:
            return FinalizationDecision(
                action=DecisionAction.REJECT,
                reasons=[_check_reason(check) for check in hard_rejections[:12]],
            )

        if proposal.performance.confidence < self.low_confidence_threshold:
            reasons = [
                "confidence: "
                f"{proposal.performance.confidence:.3f} is below "
                f"{self.low_confidence_threshold:.3f}"
            ]
            return FinalizationDecision(
                action=DecisionAction.REQUIRE_APPROVAL,
                reasons=reasons,
                directive=finalize_proposal(
                    request,
                    proposal,
                    specialists_called=specialists_called,
                    prompt_versions=prompt_versions,
                    model=model,
                    trace_id=trace_id,
                    response_id=response_id,
                ),
            )

        critical = [
            check
            for check in checks
            if check.severity is CheckSeverity.CRITICAL and check.status is not CheckStatus.PASS
        ]
        if critical:
            return FinalizationDecision(
                action=DecisionAction.REQUIRE_APPROVAL,
                reasons=[_check_reason(check) for check in critical[:12]],
                directive=finalize_proposal(
                    request,
                    proposal,
                    specialists_called=specialists_called,
                    prompt_versions=prompt_versions,
                    model=model,
                    trace_id=trace_id,
                    response_id=response_id,
                ),
            )

        if failed:
            return FinalizationDecision(
                action=DecisionAction.REPAIR,
                reasons=[_check_reason(check) for check in failed[:12]],
                repair_feedback=_repair_feedback(failed),
            )

        warnings = [check for check in checks if check.status is CheckStatus.WARN]
        return FinalizationDecision(
            action=DecisionAction.EMIT,
            reasons=[_check_reason(check) for check in warnings[:12]],
            directive=finalize_proposal(
                request,
                proposal,
                specialists_called=specialists_called,
                prompt_versions=prompt_versions,
                model=model,
                trace_id=trace_id,
                response_id=response_id,
            ),
        )


def decide_finalization(
    proposal: TurnProposal,
    checks: Sequence[CheckResult],
    turn: TurnRequest | TurnStateRecord,
    **runtime_fields: object,
) -> FinalizationDecision:
    return Finalizer().decide(proposal, checks, turn, **runtime_fields)
