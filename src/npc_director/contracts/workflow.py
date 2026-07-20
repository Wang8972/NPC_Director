from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from npc_director.contracts.enums import (
    ApprovalStatus,
    CheckSeverity,
    CheckStatus,
    DecisionAction,
    EngineEventType,
    SpecialistName,
    TurnStatus,
)
from npc_director.contracts.performance import PerformanceDirective, TurnProposal
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


class DirectorRunResult(WorkflowContract):
    proposal: TurnProposal
    metrics: GenerationMetrics
    delegations: list[DelegationEvent] = Field(default_factory=list, max_length=8)
    handoffs: list[str] = Field(default_factory=list, max_length=1)
    lore_refs_accessed: list[str] = Field(default_factory=list, max_length=16)
    trace_id: str | None = None
    response_id: str | None = None


class TurnStateRecord(WorkflowContract):
    turn_id: str
    session_id: str
    npc_id: str
    status: TurnStatus = TurnStatus.RUNNING
    request: TurnRequest
    domain_version: int | None = Field(default=None, ge=0)
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
    repair_attempts: int = Field(default=0, ge=0, le=2)
    approval_id: str | None = None
    idempotency_key: str | None = None
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


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
