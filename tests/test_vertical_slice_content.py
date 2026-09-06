from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from npc_director.prototype.content_catalog import (
    DEFAULT_CATALOG_PATH,
    PrototypeContentCatalog,
    load_prototype_content_catalog,
)
from npc_director.prototype.real_director import (
    ALLOWED_ACTIONS_BY_NPC,
    CHARACTERS,
    FACT_TEXTS,
    SENSITIVE_FACT_SURFACES,
)

UNITY_CATALOG = Path(
    "unity/NPCDirectorClient/Resources/VerticalSliceContentCatalog.json"
)


def test_vertical_slice_catalog_is_frozen_and_drives_real_context() -> None:
    catalog = load_prototype_content_catalog()

    assert catalog.catalog_version == "vertical-slice-v1"
    assert len(catalog.npc_profiles) == 3
    assert len(catalog.object_ids) == 6
    assert len(catalog.facts) == 11
    assert catalog.character_views == CHARACTERS
    assert catalog.fact_texts == FACT_TEXTS
    assert catalog.sensitive_surfaces == SENSITIVE_FACT_SURFACES
    assert catalog.actions_by_npc == ALLOWED_ACTIONS_BY_NPC


def test_unity_resource_is_generated_from_the_backend_catalog() -> None:
    backend = json.loads(DEFAULT_CATALOG_PATH.read_text(encoding="utf-8"))
    unity = json.loads(UNITY_CATALOG.read_text(encoding="utf-8"))

    assert unity == backend


def test_catalog_rejects_vertical_slice_scope_expansion() -> None:
    payload = json.loads(DEFAULT_CATALOG_PATH.read_text(encoding="utf-8"))
    payload["object_ids"].append("scope_creep_object")

    with pytest.raises(ValidationError, match="object_ids must remain frozen"):
        PrototypeContentCatalog.model_validate(payload)
