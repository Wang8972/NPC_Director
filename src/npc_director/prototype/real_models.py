from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from npc_director.contracts import GenerationMetrics, PerformanceDraft


class PrototypeRealModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class PrototypeFactView(PrototypeRealModel):
    fact_id: str = Field(min_length=1, max_length=120)
    text: str = Field(min_length=1, max_length=300)


class PrototypeCharacterView(PrototypeRealModel):
    npc_id: str = Field(min_length=1, max_length=80)
    display_name: str = Field(min_length=1, max_length=80)
    role: str = Field(min_length=1, max_length=200)
    stance: str = Field(min_length=1, max_length=500)
    style: str = Field(min_length=1, max_length=500)


class PrototypeTrustedContext(PrototypeRealModel):
    session_id: str
    turn_id: str
    selected_npc: PrototypeCharacterView
    player_input: str = Field(min_length=1, max_length=2_000)
    objective_state: str
    world_version: int = Field(ge=0)
    object_states: dict[str, str]
    visible_item_locations: dict[str, str]
    player_known_facts: list[PrototypeFactView]
    npc_known_facts: list[PrototypeFactView]
    allowed_action_types: list[str]
    canonical_object_ids: list[str]
    canonical_npc_ids: list[str]
    response_obligations: list[str] = Field(default_factory=list, max_length=12)
    origin: Literal["player", "internal_npc_reply"] = "player"


class PrototypeGroundedClaim(PrototypeRealModel):
    fact_id: str = Field(min_length=1, max_length=120)
    claim: str = Field(min_length=1, max_length=300)


class PrototypeSceneActionProposal(PrototypeRealModel):
    actor_id: str = Field(min_length=1, max_length=80)
    action_type: Literal[
        "inspect_object",
        "authorize_object",
        "give_item",
        "install_item",
        "operate_object",
        "tell_npc",
        "tell_player",
    ]
    object_id: str | None = None
    item_id: str | None = None
    target_id: str | None = None
    target_npc_id: str | None = None
    fact_id: str | None = None
    operation: str | None = None
    gameplay_intent: Literal["cooperation_offer", "request_authorization"] | None = None


class PrototypeRealTurnProposal(PrototypeRealModel):
    performance: PerformanceDraft
    action: PrototypeSceneActionProposal | None = None
    used_fact_ids: list[str] = Field(default_factory=list, max_length=12)
    grounded_claims: list[PrototypeGroundedClaim] = Field(default_factory=list, max_length=12)

    @field_validator("used_fact_ids")
    @classmethod
    def fact_ids_must_be_unique(cls, values: list[str]) -> list[str]:
        normalized = [value.strip() for value in values]
        if any(not value for value in normalized):
            raise ValueError("used_fact_ids must not contain blank values")
        if len(normalized) != len(set(normalized)):
            raise ValueError("used_fact_ids must not contain duplicates")
        return normalized


class PrototypeGenerationResult(PrototypeRealModel):
    proposal: PrototypeRealTurnProposal
    metrics: GenerationMetrics
    trace_id: str | None = None
    response_id: str | None = None
    fallback_reason: str | None = None


class PrototypeGovernanceResult(PrototypeRealModel):
    approved: bool
    reason_code: str | None = None
    feedback: str | None = None
