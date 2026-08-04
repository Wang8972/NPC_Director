from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, field_validator

from npc_director.contracts.enums import Intent


class RoutingContract(BaseModel):
    model_config = ConfigDict(extra="forbid")


class RouteDecision(RoutingContract):
    """Semantic decision produced by the main agent before runtime orchestration.

    The model describes what the turn needs. Runtime code remains responsible for
    translating the decision into an allowed specialist execution plan.
    """

    intent: Intent
    objective: str = Field(min_length=1, max_length=500)
    needs_lore: bool = False
    needs_narrative: bool = False
    negotiation: bool = False
    ambiguity: bool = False
    confidence: float = Field(default=0.5, ge=0, le=1)
    lore_queries: list[str] = Field(default_factory=list, max_length=4)
    constraints: list[str] = Field(default_factory=list, max_length=8)
    response_obligations: list[str] = Field(default_factory=list, max_length=8)

    @field_validator("lore_queries", "constraints", "response_obligations")
    @classmethod
    def strings_are_unique_and_non_blank(cls, values: list[str]) -> list[str]:
        normalized = [value.strip() for value in values]
        if any(not value for value in normalized):
            raise ValueError("route decision strings must not be blank")
        if len(normalized) != len(set(normalized)):
            raise ValueError("route decision strings must not contain duplicates")
        return normalized
