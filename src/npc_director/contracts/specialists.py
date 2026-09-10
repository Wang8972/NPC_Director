from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from npc_director.contracts.content import NarrativeScopeDecision, ObjectiveEvent, ObjectiveStep
from npc_director.contracts.enums import (
    BodyAction,
    CoarseEmotion,
    FacePreset,
    Intent,
    PrimaryEmotion,
)
from npc_director.contracts.performance import Dialogue, PerformanceDraft
from npc_director.contracts.plan import StateChangeProposal


class SpecialistContract(BaseModel):
    model_config = ConfigDict(extra="forbid")


class DirectorInput(SpecialistContract):
    session_id: str = Field(min_length=1, max_length=120)
    turn_id: str = Field(min_length=1, max_length=120)
    npc_id: str = Field(min_length=1, max_length=80)
    player_input: str = Field(min_length=1, max_length=2_000)
    scene_summary: str = Field(min_length=1, max_length=1_500)
    character_core: str = Field(min_length=1, max_length=2_000)
    character_style: str = Field(default="", max_length=1_500)
    relationship_summary: str = Field(default="", max_length=800)
    quest_summary: str = Field(default="", max_length=1_500)
    history_summary: str = Field(default="", max_length=3_000)
    relevant_flags: list[str] = Field(default_factory=list, max_length=20)
    lore_scopes: list[str] = Field(default_factory=lambda: ["public"], max_length=8)
    allowed_actions: list[BodyAction] = Field(default_factory=list)
    allowed_faces: list[FacePreset] = Field(default_factory=list)
    allowed_state_paths: list[str] = Field(default_factory=list, max_length=24)
    state_tokens: list[str] = Field(default_factory=list, max_length=24)
    response_obligations: list[str] = Field(default_factory=list, max_length=8)
    policy_digest: str | None = Field(default=None, min_length=64, max_length=64)
    catalog_version: str | None = Field(default=None, max_length=40)
    max_tool_calls: int = Field(default=4, ge=0, le=8)
    max_specialist_calls: int = Field(default=4, ge=0, le=8)
    max_handoffs: int = Field(default=1, ge=0, le=2)
    episode_id: str | None = None
    stimulus: dict[str, Any] = Field(default_factory=dict)
    conversation_state: dict[str, Any] = Field(default_factory=dict)
    actor_context: dict[str, Any] = Field(default_factory=dict)
    actor_registry: list[dict[str, Any]] = Field(default_factory=list, max_length=32)
    content_policy: dict[str, Any] = Field(default_factory=dict)
    execution_budget: dict[str, Any] = Field(default_factory=dict)


class NarrativeInput(SpecialistContract):
    player_intent: Intent
    scene_summary: str = Field(min_length=1, max_length=1_500)
    current_quest_summary: str = Field(default="", max_length=1_500)
    relationship_summary: str = Field(default="", max_length=800)
    relevant_flags: list[str] = Field(default_factory=list, max_length=20)
    allowed_state_paths: list[str] = Field(default_factory=list, max_length=24)
    player_input: str = Field(default="", max_length=2000)
    objective: str = Field(default="", max_length=500)
    history_summary: str = Field(default="", max_length=3000)
    character_core: str = Field(default="", max_length=2000)
    analysis: dict[str, Any] = Field(default_factory=dict)
    evidence: list[dict[str, Any]] = Field(default_factory=list, max_length=16)
    conversation_state: dict[str, Any] = Field(default_factory=dict)
    actor_context: dict[str, Any] = Field(default_factory=dict)


class NarrativeBeat(SpecialistContract):
    order: int = Field(ge=1, le=8)
    description: str = Field(min_length=1, max_length=300)
    required: bool = True


class NarrativePlan(SpecialistContract):
    objective: str = Field(min_length=1, max_length=300)
    beats: list[NarrativeBeat] = Field(min_length=1, max_length=8)
    constraints: list[str] = Field(default_factory=list, max_length=8)
    proposed_state_changes: StateChangeProposal = Field(default_factory=StateChangeProposal)
    scope_decision: NarrativeScopeDecision | None = None
    steps: list[ObjectiveStep] = Field(default_factory=list, max_length=16)
    events: list[ObjectiveEvent] = Field(default_factory=list, max_length=8)

    @field_validator("beats")
    @classmethod
    def beats_are_ordered(cls, beats: list[NarrativeBeat]) -> list[NarrativeBeat]:
        orders = [beat.order for beat in beats]
        if orders != list(range(1, len(beats) + 1)):
            raise ValueError("narrative beat order must be contiguous and start at 1")
        return beats


class LoreInput(SpecialistContract):
    queries: list[str] = Field(min_length=1, max_length=4)
    scene_summary: str = Field(default="", max_length=1_500)
    allowed_scopes: list[str] = Field(default_factory=lambda: ["public"], max_length=8)
    max_results: int = Field(default=4, ge=1, le=8)


class LoreEvidenceItem(SpecialistContract):
    ref: str = Field(min_length=1, max_length=160)
    excerpt: str = Field(min_length=1, max_length=1_000)
    scope: str = Field(default="public", min_length=1, max_length=80)
    score: float = Field(default=0, ge=0, le=1)


class LoreEvidence(SpecialistContract):
    items: list[LoreEvidenceItem] = Field(default_factory=list, max_length=8)
    unanswered_queries: list[str] = Field(default_factory=list, max_length=4)


class ScreenwriterInput(SpecialistContract):
    character_core: str = Field(min_length=1, max_length=2_000)
    character_style: str = Field(default="", max_length=1_500)
    narrative_objective: str = Field(min_length=1, max_length=500)
    narrative_constraints: list[str] = Field(default_factory=list, max_length=8)
    lore_evidence: list[LoreEvidenceItem] = Field(default_factory=list, max_length=8)
    recent_history: list[str] = Field(default_factory=list, max_length=12)
    player_input: str = Field(min_length=1, max_length=2_000)
    response_obligations: list[str] = Field(default_factory=list, max_length=8)
    analysis: dict[str, Any] = Field(default_factory=dict)
    narrative_beats: list[NarrativeBeat] = Field(default_factory=list, max_length=8)
    negotiation: dict[str, Any] = Field(default_factory=dict)
    conversation_state: dict[str, Any] = Field(default_factory=dict)
    actor_context: dict[str, Any] = Field(default_factory=dict)
    pending_collaborations: list[dict[str, Any]] = Field(default_factory=list, max_length=3)
    repair_feedback: list[str] = Field(default_factory=list, max_length=12)


class DialogueDraft(SpecialistContract):
    dialogue: Dialogue
    coarse_emotion: CoarseEmotion
    primary_emotion: PrimaryEmotion
    secondary_emotion: PrimaryEmotion | None = None
    intensity: float = Field(default=0.5, ge=0, le=1)
    valence: float = Field(default=0, ge=-1, le=1)
    arousal: float = Field(default=0.4, ge=0, le=1)
    used_lore_refs: list[str] = Field(default_factory=list, max_length=8)
    used_fact_refs: list[str] = Field(default_factory=list, max_length=16)
    commitments: list[str] = Field(default_factory=list, max_length=8)
    reply_outcome: Literal["resolved", "partial", "pending", "refused"] = "partial"
    rationale: str = Field(default="", max_length=500)


class PerformanceInput(SpecialistContract):
    dialogue: Dialogue
    coarse_emotion: CoarseEmotion
    primary_emotion: PrimaryEmotion
    secondary_emotion: PrimaryEmotion | None = None
    intensity: float = Field(default=0.5, ge=0, le=1)
    valence: float = Field(default=0, ge=-1, le=1)
    arousal: float = Field(default=0.4, ge=0, le=1)
    scene_summary: str = Field(default="", max_length=1_500)
    allowed_actions: list[BodyAction] = Field(default_factory=list)
    allowed_faces: list[FacePreset] = Field(default_factory=list)


class PerformanceOutput(SpecialistContract):
    performance: PerformanceDraft
