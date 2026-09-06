from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, model_validator

from npc_director.prototype.models import ACTION_TYPES, ITEM_IDS, NPC_IDS, OBJECT_IDS, SCENE_ID
from npc_director.prototype.real_models import PrototypeCharacterView

DEFAULT_CATALOG_PATH = Path("data/prototype/vertical_slice_catalog.json")
FROZEN_ROUTE_IDS = ("cooperation", "procedure")


class CatalogModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class CatalogNpcProfile(CatalogModel):
    npc_id: str
    display_name: str
    role: str
    stance: str
    style: str
    allowed_action_types: list[str]


class CatalogFact(CatalogModel):
    fact_id: str
    text: str
    sensitive_surfaces: list[str] = Field(default_factory=list)


class PrototypeContentCatalog(CatalogModel):
    schema_version: str
    catalog_version: str
    scene_id: str
    npc_profiles: list[CatalogNpcProfile]
    object_ids: list[str]
    item_ids: list[str]
    route_ids: list[str]
    operation_ids: list[str]
    facts: list[CatalogFact]

    @model_validator(mode="after")
    def matches_frozen_vertical_slice_scope(self) -> PrototypeContentCatalog:
        _require_exact("npc_ids", [item.npc_id for item in self.npc_profiles], NPC_IDS)
        _require_exact("object_ids", self.object_ids, OBJECT_IDS)
        _require_exact("item_ids", self.item_ids, ITEM_IDS)
        _require_exact("route_ids", self.route_ids, FROZEN_ROUTE_IDS)
        if self.scene_id != SCENE_ID:
            raise ValueError(f"scene_id must remain {SCENE_ID!r}")
        if self.operation_ids != ["restart_gate_power"]:
            raise ValueError("vertical slice operation_ids changed")
        fact_ids = [item.fact_id for item in self.facts]
        if len(fact_ids) != len(set(fact_ids)):
            raise ValueError("fact_ids must be unique")
        for profile in self.npc_profiles:
            unknown = sorted(set(profile.allowed_action_types) - set(ACTION_TYPES))
            if unknown:
                raise ValueError(f"{profile.npc_id} has unknown actions: {unknown}")
        return self

    @property
    def character_views(self) -> dict[str, PrototypeCharacterView]:
        return {
            item.npc_id: PrototypeCharacterView(
                npc_id=item.npc_id,
                display_name=item.display_name,
                role=item.role,
                stance=item.stance,
                style=item.style,
            )
            for item in self.npc_profiles
        }

    @property
    def fact_texts(self) -> dict[str, str]:
        return {item.fact_id: item.text for item in self.facts}

    @property
    def sensitive_surfaces(self) -> dict[str, tuple[str, ...]]:
        return {
            item.fact_id: tuple(item.sensitive_surfaces)
            for item in self.facts
            if item.sensitive_surfaces
        }

    @property
    def actions_by_npc(self) -> dict[str, tuple[str, ...]]:
        return {
            item.npc_id: tuple(item.allowed_action_types) for item in self.npc_profiles
        }


def _require_exact(name: str, actual: list[str], expected: tuple[str, ...]) -> None:
    if len(actual) != len(set(actual)):
        raise ValueError(f"{name} must not contain duplicates")
    if set(actual) != set(expected):
        raise ValueError(
            f"{name} must remain frozen; "
            f"expected={sorted(expected)} actual={sorted(actual)}"
        )


@lru_cache(maxsize=4)
def load_prototype_content_catalog(
    path: str | Path = DEFAULT_CATALOG_PATH,
) -> PrototypeContentCatalog:
    resolved = Path(path)
    payload = json.loads(resolved.read_text(encoding="utf-8"))
    return PrototypeContentCatalog.model_validate(payload)
