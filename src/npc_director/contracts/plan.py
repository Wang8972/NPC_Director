from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from npc_director.contracts.enums import Intent, SpecialistName


class ContractModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class RelationshipPatch(ContractModel):
    trust_delta: int = Field(default=0, ge=-10, le=10)
    affinity_delta: int = Field(default=0, ge=-10, le=10)


class QuestPatch(ContractModel):
    quest_id: str = Field(min_length=1, max_length=80, pattern=r"^[a-z0-9_.-]+$")
    status: str = Field(pattern=r"^(offered|accepted|active|completed|failed)$")


class FlagPatch(ContractModel):
    name: str = Field(min_length=1, max_length=80, pattern=r"^[a-zA-Z0-9_]+$")
    value: bool


class StateChangeProposal(ContractModel):
    relationship: RelationshipPatch | None = None
    flags: list[FlagPatch] = Field(default_factory=list, max_length=8)
    quests: list[QuestPatch] = Field(default_factory=list, max_length=4)

    @field_validator("flags")
    @classmethod
    def flag_names_must_be_unique(cls, flags: list[FlagPatch]) -> list[FlagPatch]:
        names = [flag.name for flag in flags]
        if len(names) != len(set(names)):
            raise ValueError("flags must not contain duplicate names")
        return flags


class TurnPlan(ContractModel):
    goal: str = Field(min_length=1, max_length=300)
    intent: Intent
    required_specialists: list[SpecialistName] = Field(min_length=1, max_length=4)
    lore_queries: list[str] = Field(default_factory=list, max_length=4)
    constraints: list[str] = Field(default_factory=list, max_length=8)
    proposed_state_changes: StateChangeProposal = Field(default_factory=StateChangeProposal)

    @field_validator("required_specialists")
    @classmethod
    def specialists_must_be_unique(cls, specialists: list[SpecialistName]) -> list[SpecialistName]:
        if len(specialists) != len(set(specialists)):
            raise ValueError("required_specialists must not contain duplicates")
        return specialists


def extract_state_change_paths(proposal: StateChangeProposal) -> set[str]:
    paths: set[str] = set()
    payload: dict[str, Any] = proposal.model_dump(exclude_none=True)

    relationship = payload.get("relationship", {})
    for key, value in relationship.items():
        if value != 0:
            paths.add(f"relationship.{key}")

    for flag in payload.get("flags", []):
        paths.add(f"flags.{flag['name']}")

    for quest in payload.get("quests", []):
        paths.add(f"quests.{quest['quest_id']}.status")

    return paths
