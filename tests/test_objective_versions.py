from __future__ import annotations

import pytest

from npc_director.contracts.content import ObjectiveRef
from npc_director.governance.content_review import ContentReviewError
from npc_director.state.content_store import ContentStore
from tests.test_content_review import publish, reviewed


def test_objective_lookup_preserves_instance_and_objective_identity(tmp_path):
    database = tmp_path / "state.db"
    store = ContentStore(database)
    original = ObjectiveRef(objective_id="repair-generator", quest_id="repair", version=2)
    other_instance = original.model_copy(update={"version": 7})
    store.register_objective("game-a", original)
    store.register_objective("game-b", other_instance)

    reopened = ContentStore(database)
    assert reopened.get_objective("game-a", "repair-generator") == original
    assert reopened.get_objective("game-b", "repair-generator") == other_instance
    assert reopened.get_objective("game-c", "repair-generator") is None
    assert reopened.get_objective("game-a", "missing-objective") is None
    assert reopened.get_objective("game-a", "repair") is None
    returned = reopened.get_objective("game-a", "repair-generator")
    returned.version = 99
    assert reopened.get_objective("game-a", "repair-generator") == original


@pytest.mark.parametrize(
    "session_id,objective_id,field",
    [
        ("", "repair", "session_id"),
        (" \t", "repair", "session_id"),
        ("game-a", "", "objective_id"),
        ("game-a", " \n", "objective_id"),
    ],
)
def test_objective_lookup_rejects_missing_scope_or_identity(
    tmp_path, session_id, objective_id, field
):
    store = ContentStore(tmp_path / "state.db")
    with pytest.raises(ValueError, match=f"{field} must not be blank"):
        store.get_objective(session_id, objective_id)


def test_registry_still_rejects_actual_stale_versions_and_changed_ownership(tmp_path):
    store = ContentStore(tmp_path / "state.db")
    initial = ObjectiveRef(objective_id="repair-generator", quest_id="repair", version=0)
    store.register_objective("game-a", initial)
    updated = initial.model_copy(update={"version": 1})
    store.register_objective("game-a", updated)
    store.register_objective("game-a", updated)

    with pytest.raises(ContentReviewError, match="stale objective version"):
        store.register_objective("game-a", initial)
    with pytest.raises(ContentReviewError, match="cannot change quest ownership"):
        store.register_objective("game-a", updated.model_copy(update={"quest_id": "other-quest"}))
    assert store.get_objective("game-a", initial.objective_id) == updated


def test_generated_quest_objective_uses_its_own_lifecycle_version(tmp_path):
    store = ContentStore(tmp_path / "state.db")
    staged = store.stage_reviewed("game-a", "episode-1", "turn-1", "mechanic", reviewed())
    publish(store)
    initial = store.get_objective("game-a", staged.quest_id)
    assert initial == ObjectiveRef(
        objective_id=staged.quest_id, quest_id=staged.quest_id, version=0
    )

    accepted = store.advance_quest("game-a", staged.quest_id, "accept-event", "accepted")
    current = store.get_objective("game-a", staged.quest_id)
    assert current.version == accepted.version == 1
    with pytest.raises(ContentReviewError, match="stale objective version"):
        store.register_objective("game-a", initial)
    assert store.get_objective("game-a", staged.quest_id) == current


@pytest.mark.parametrize("changed_field", ["objective_id", "version"])
def test_objective_lookup_rejects_inconsistent_registry_payload(tmp_path, changed_field):
    store = ContentStore(tmp_path / "state.db")
    ref = ObjectiveRef(objective_id="repair-generator", quest_id="repair", version=2)
    store.register_objective("game-a", ref)
    invalid = ref.model_copy(
        update={changed_field: "other-objective" if changed_field == "objective_id" else 9}
    )
    with store.transaction() as connection:
        connection.execute(
            "UPDATE narrative_objectives SET ref_json=? WHERE session_id=? AND objective_id=?",
            (invalid.model_dump_json(), "game-a", ref.objective_id),
        )
    with pytest.raises(ContentReviewError, match="registry identity or version mismatch"):
        store.get_objective("game-a", ref.objective_id)
