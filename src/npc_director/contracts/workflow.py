from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from npc_director.contracts.content import ObjectiveEvent, ObjectiveStep
from npc_director.contracts.enums import (
    ApprovalStatus,
    BodyAction,
    CheckSeverity,
    CheckStatus,
    DecisionAction,
    EngineEventType,
    FacePreset,
    Intent,
    SpecialistName,
    TurnStatus,
    UncertaintyKind,
)
from npc_director.contracts.performance import PerformanceDirective, TurnProposal
from npc_director.contracts.planning import (
    CollaborationRequest,
    DialogueStateDelta,
    ExecutionTrace,
)
from npc_director.contracts.routing import RouteDecision
from npc_director.contracts.state import GenerationMetrics, TurnRequest


def utc_now() -> datetime:
    return datetime.now(UTC)


class WorkflowContract(BaseModel):
    model_config = ConfigDict(extra="forbid")


class CheckResult(WorkflowContract):
    name: str = Field(min_length=1, max_length=100)
    status: CheckStatus
    severity: CheckSeverity = CheckSeverity.LOW
    reason: str = Field(default="", max_length=1_000)
    repair_hint: str | None = Field(default=None, max_length=1_000)


class FinalizationDecision(WorkflowContract):
    action: DecisionAction
    reasons: list[str] = Field(default_factory=list, max_length=12)
    directive: PerformanceDirective | None = None
    repair_feedback: str | None = Field(default=None, max_length=2_000)


class DelegationEvent(WorkflowContract):
    specialist: SpecialistName
    tool_name: str = Field(min_length=1, max_length=100)
    call_id: str | None = Field(default=None, max_length=160)
    input_payload: str = Field(default="", max_length=12_000)
    status: str = Field(pattern=r"^(started|completed|failed)$")
    started_at: datetime = Field(default_factory=utc_now)
    latency_ms: float | None = Field(default=None, ge=0)
    error: str | None = Field(default=None, max_length=2_000)


class RoutingTrace(WorkflowContract):
    decision: RouteDecision
    final_intent: Intent
    uncertainty_kind: UncertaintyKind = UncertaintyKind.NONE
    use_lore: bool = False
    use_narrative: bool = False
    use_negotiator: bool = False
    advisory_only: bool = False
    clarification_fallback: bool = False
    fallback_reason: str | None = Field(default=None, max_length=500)


class DirectorRunResult(WorkflowContract):
    proposal: TurnProposal
    metrics: GenerationMetrics
    delegations: list[DelegationEvent] = Field(default_factory=list, max_length=8)
    handoffs: list[str] = Field(default_factory=list, max_length=1)
    lore_refs_accessed: list[str] = Field(default_factory=list, max_length=16)
    routing_trace: RoutingTrace | None = None
    trace_id: str | None = None
    response_id: str | None = None
    execution_trace: ExecutionTrace | None = None
    collaboration_messages: list[CollaborationRequest] = Field(default_factory=list, max_length=3)
    dialogue_state_delta: DialogueStateDelta = Field(default_factory=DialogueStateDelta)
    content_candidates: list[dict[str, Any]] = Field(default_factory=list, max_length=8)
    objective_steps: list[ObjectiveStep] = Field(default_factory=list, max_length=16)
    objective_events: list[ObjectiveEvent] = Field(default_factory=list, max_length=8)
    cognitive_commit: dict[str, Any] = Field(default_factory=dict)


class TurnStateRecord(WorkflowContract):
    turn_id: str
    session_id: str
    npc_id: str
    status: TurnStatus = TurnStatus.RUNNING
    request: TurnRequest
    domain_version: int | None = Field(default=None, ge=0)
    policy_digest: str | None = Field(
        default=None,
        min_length=64,
        max_length=64,
        pattern=r"^[0-9a-f]{64}$",
    )
    policy_catalog_version: str | None = Field(default=None, max_length=40)
    allowed_actions: list[BodyAction] = Field(default_factory=list)
    allowed_faces: list[FacePreset] = Field(default_factory=list)
    allowed_state_paths: list[str] = Field(default_factory=list, max_length=24)
    state_tokens: list[str] = Field(default_factory=list, max_length=24)
    max_tool_calls: int = Field(default=0, ge=0, le=8)
    max_specialist_calls: int = Field(default=0, ge=0, le=8)
    max_handoffs: int = Field(default=0, ge=0, le=2)
    proposal: TurnProposal | None = None
    directive: PerformanceDirective | None = None
    metrics: GenerationMetrics | None = None
    specialists_called: list[SpecialistName] = Field(default_factory=list, max_length=4)
    handoffs: list[str] = Field(default_factory=list, max_length=1)
    prompt_versions: list[str] = Field(default_factory=list, max_length=8)
    trace_id: str | None = None
    response_id: str | None = None
    available_lore_refs: list[str] = Field(default_factory=list, max_length=32)
    checks: list[CheckResult] = Field(default_factory=list)
    repair_attempts: int = Field(default=0, ge=0, le=4)
    approval_id: str | None = None
    idempotency_key: str | None = None
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)

    @field_validator("allowed_state_paths")
    @classmethod
    def state_paths_must_be_exact_and_unique(cls, paths: list[str]) -> list[str]:
        normalized = [path.strip() for path in paths]
        if any(not path for path in normalized):
            raise ValueError("allowed_state_paths must not contain blank paths")
        wildcard_paths = sorted(path for path in normalized if any(char in path for char in "*?["))
        if wildcard_paths:
            raise ValueError("allowed_state_paths must be exact: " + ", ".join(wildcard_paths))
        if len(normalized) != len(set(normalized)):
            raise ValueError("allowed_state_paths must not contain duplicates")
        return sorted(normalized)

    @field_validator("state_tokens")
    @classmethod
    def state_tokens_must_be_non_blank_and_unique(cls, tokens: list[str]) -> list[str]:
        normalized = [token.strip() for token in tokens]
        if any(not token for token in normalized):
            raise ValueError("state_tokens must not contain blank tokens")
        if len(normalized) != len(set(normalized)):
            raise ValueError("state_tokens must not contain duplicates")
        return sorted(normalized)

    @field_validator("allowed_actions", "allowed_faces")
    @classmethod
    def enum_capabilities_must_be_unique(cls, values: list[Any]) -> list[Any]:
        if len(values) != len(set(values)):
            raise ValueError("policy capabilities must not contain duplicates")
        return values


class ApprovalRecord(WorkflowContract):
    approval_id: str
    turn_id: str
    status: ApprovalStatus = ApprovalStatus.PENDING
    reasons: list[str] = Field(default_factory=list, max_length=12)
    proposed_directive: PerformanceDirective
    resolved_directive: PerformanceDirective | None = None
    reviewer: str | None = Field(default=None, max_length=120)
    comment: str | None = Field(default=None, max_length=1_000)
    created_at: datetime = Field(default_factory=utc_now)
    resolved_at: datetime | None = None


class EngineEmitReceipt(WorkflowContract):
    turn_id: str
    idempotency_key: str
    status: str = Field(pattern=r"^(sent|duplicate|queued)$")
    detail: str | None = None


class EngineEvent(WorkflowContract):
    session_id: str
    turn_id: str
    idempotency_key: str
    event_type: EngineEventType
    detail: str | None = Field(default=None, max_length=2_000)
    occurred_at: datetime = Field(default_factory=utc_now)


class TurnExecutionResult(WorkflowContract):
    turn_id: str
    status: TurnStatus
    plan: Any | None = None
    directive: PerformanceDirective | None = None
    metrics: GenerationMetrics | None = None
    checks: list[CheckResult] = Field(default_factory=list)
    approval_id: str | None = None
    idempotency_key: str | None = None
