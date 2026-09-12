from __future__ import annotations

import json
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from npc_director.contracts.cognition import BehaviorModeDefinition


class CharacterProfile(BaseModel):
    """Authored character data. Public roster entries deliberately omit private traits."""

    model_config = ConfigDict(extra="forbid")
    npc_id: str = Field(pattern=r"^[a-zA-Z0-9_.:-]+$")
    display_name: str = ""
    role: str = ""
    core: str
    style: str = ""
    background: str = ""
    goals: list[str] = Field(default_factory=list)
    concerns: list[str] = Field(default_factory=list)
    values: list[str] = Field(default_factory=list)
    boundaries: list[str] = Field(default_factory=list)
    voice_examples: list[str] = Field(default_factory=list)
    locations: list[str] = Field(default_factory=list)
    capabilities: list[str] = Field(default_factory=list)
    deception_policy: str = "character_consistent"
    behavior_modes: list[BehaviorModeDefinition] = Field(default_factory=list)
    initial_behavior_mode: str = "neutral"
    protected_memory_refs: list[str] = Field(default_factory=list)

    def public_view(self) -> dict[str, object]:
        return self.model_dump(
            include={"npc_id", "display_name", "role", "locations", "capabilities"}
        )


class CharacterRegistry:
    """Server-owned roster; client nearby_entities cannot register or summon an actor."""

    def __init__(self, profiles: list[CharacterProfile] | None = None) -> None:
        self._profiles: dict[str, CharacterProfile] = {}
        for profile in profiles or []:
            self.register(profile)

    @classmethod
    def from_directory(cls, root: Path) -> CharacterRegistry:
        profiles = []
        for path in sorted(root.glob("*.json")):
            profile = CharacterProfile.model_validate(json.loads(path.read_text(encoding="utf-8")))
            if path.stem != profile.npc_id:
                raise ValueError(f"character filename does not match npc_id: {path.name}")
            profiles.append(profile)
        return cls(profiles)

    def register(self, profile: CharacterProfile) -> None:
        existing = self._profiles.get(profile.npc_id)
        if existing is not None and existing != profile:
            raise ValueError(f"character is already registered: {profile.npc_id}")
        self._profiles[profile.npc_id] = profile

    def get(self, npc_id: str) -> CharacterProfile | None:
        return self._profiles.get(npc_id)

    def require(self, npc_id: str) -> CharacterProfile:
        profile = self.get(npc_id)
        if profile is None:
            raise ValueError(f"unregistered actor: {npc_id}")
        return profile

    def roster(
        self, location: str, *, current_npc_id: str | None = None
    ) -> list[dict[str, object]]:
        return [
            profile.public_view()
            for profile in self._profiles.values()
            if location in profile.locations or profile.npc_id == current_npc_id
        ]
