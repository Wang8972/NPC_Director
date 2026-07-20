from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from npc_director.contracts import (
    BodyAction,
    CoarseEmotion,
    GenerationMetrics,
    Intent,
    PrimaryEmotion,
    SpecialistName,
    TurnProposal,
    TurnRequest,
)

Architecture = Literal["single_agent", "main_sub"]
RunMode = Literal["recorded", "live"]


class EvalModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class EmotionExpectation(EvalModel):
    coarse: list[CoarseEmotion] = Field(min_length=1)
    primary: list[PrimaryEmotion] = Field(min_length=1)
    secondary: list[PrimaryEmotion] = Field(default_factory=list)

    @field_validator("coarse", "primary", "secondary", mode="before")
    @classmethod
    def scalar_values_are_normalized_to_lists(cls, value: Any) -> Any:
        if value is None:
            return []
        if isinstance(value, str):
            return [value]
        return value

    @field_validator("coarse", "primary", "secondary")
    @classmethod
    def emotion_values_must_be_unique(cls, values: list[Any]) -> list[Any]:
        if len(values) != len(set(values)):
            raise ValueError("emotion expectation values must not contain duplicates")
        return values


class EvalExpectation(EvalModel):
    intent: Intent
    emotion: EmotionExpectation
    allowed_actions: list[BodyAction]
    state_patch_allowlist: list[str]
    required_text: list[str] = Field(default_factory=list)
    forbidden_text: list[str] = Field(default_factory=list)
    required_specialists: list[SpecialistName] = Field(default_factory=list)
    optional_specialists: list[SpecialistName] = Field(default_factory=list)
    forbidden_specialists: list[SpecialistName] = Field(default_factory=list)
    required_handoff: str | None = None

    @field_validator(
        "allowed_actions",
        "state_patch_allowlist",
        "required_text",
        "forbidden_text",
        "required_specialists",
        "optional_specialists",
        "forbidden_specialists",
    )
    @classmethod
    def values_must_be_unique(cls, values: list[Any]) -> list[Any]:
        if len(values) != len(set(values)):
            raise ValueError("expectation lists must not contain duplicates")
        return values

    @field_validator("state_patch_allowlist", "required_text", "forbidden_text")
    @classmethod
    def strings_must_not_be_blank(cls, values: list[str]) -> list[str]:
        if any(not value.strip() for value in values):
            raise ValueError("expectation strings must not be blank")
        return values

    @field_validator("required_handoff")
    @classmethod
    def required_handoff_must_not_be_blank(cls, value: str | None) -> str | None:
        if value is not None and not value.strip():
            raise ValueError("required_handoff must not be blank")
        return value.strip() if value is not None else None

    @model_validator(mode="after")
    def specialist_sets_must_not_overlap(self) -> EvalExpectation:
        required = set(self.required_specialists)
        optional = set(self.optional_specialists)
        forbidden = set(self.forbidden_specialists)
        if required & optional or required & forbidden or optional & forbidden:
            raise ValueError("required, optional, and forbidden specialists must be disjoint")
        return self


class EvalCase(EvalModel):
    id: str = Field(min_length=1, max_length=120)
    input: TurnRequest
    expect: EvalExpectation

    @model_validator(mode="after")
    def id_must_match_turn_id(self) -> EvalCase:
        if self.id != self.input.turn_id:
            raise ValueError("case id must match input.turn_id")
        return self


class RecordedBaseline(EvalModel):
    id: str = Field(min_length=1, max_length=120)
    proposal: TurnProposal
    metrics: GenerationMetrics
    specialists_called: list[SpecialistName] = Field(
        default_factory=lambda: [SpecialistName.BASELINE]
    )
    handoffs: list[str] = Field(default_factory=list, max_length=1)


class CandidateResult(EvalModel):
    id: str
    proposal: TurnProposal | None = None
    metrics: GenerationMetrics | None = None
    specialists_called: list[SpecialistName] | None = None
    handoffs: list[str] | None = Field(default=None, max_length=1)
    schema_error: str | None = None


class CheckResult(EvalModel):
    name: str
    passed: bool
    applicable: bool = True
    expected: Any = None
    actual: Any = None
    detail: str | None = None


class CaseResult(EvalModel):
    id: str
    passed: bool
    checks: list[CheckResult]


class RateSummary(EvalModel):
    total: int
    passed: int
    failed: int
    pass_rate: float


class SchemaSummary(RateSummary):
    errors: list[str] = Field(default_factory=list)


class QualitySummary(EvalModel):
    total_checks: int
    passed_checks: int
    failed_checks: int
    pass_rate: float
    passed_cases: int
    failed_cases: int
    case_pass_rate: float
    by_check: dict[str, RateSummary]


class LatencySummary(EvalModel):
    count: int
    average_ms: float | None
    p50_ms: float | None
    p95_ms: float | None
    max_ms: float | None


class TokenSummary(EvalModel):
    count: int
    input_total: int
    output_total: int
    total: int
    average_total: float | None


class CostSummary(EvalModel):
    available_count: int
    total_usd: float | None
    average_usd: float | None


class SystemSummary(EvalModel):
    latency: LatencySummary
    tokens: TokenSummary
    cost: CostSummary
    models: dict[str, int]


class EvalReport(EvalModel):
    mode: RunMode
    architecture: Architecture
    passed: bool
    total_cases: int
    passed_cases: int
    failed_cases: list[str]
    regressions: list[str]
    schema_summary: SchemaSummary = Field(serialization_alias="schema")
    quality: QualitySummary
    system: SystemSummary
    dataset_errors: list[str]
    cases: list[CaseResult]
