from __future__ import annotations

import sqlite3

import pytest

from npc_director.contracts.content import ObjectiveEvent, ObjectiveRef, ObjectiveStep
from npc_director.governance.content_review import ContentReviewError
from npc_director.state.content_store import CONTENT_SCHEMA, ContentStore
from npc_director.state.errors import IdempotencyConflictError

PARENT = ObjectiveRef(objective_id="repair-generator", quest_id="repair", version=2)


def definitions(ref=PARENT):
    return (
        [
            ObjectiveStep(
                step_id="inspect", objective=ref, description="检查已有的发电机", action="inspect"
            ),
            ObjectiveStep(
                step_id="take-tool",
                objective=ref,
                description="取旁边已有的扳手",
                action="take",
                depends_on=["inspect"],
            ),
        ],
        [
            ObjectiveEvent(
                event_id="repair-choice",
                objective=ref,
                description="选择已有的维修路径",
                choices=["先排查线路", "先检查保险丝"],
                consequences=["按选择继续检查"],
            )
        ],
    )


def save(
    store,
    *,
    turn="turn-1",
    event="completed-1",
    session="game-a",
    npc="mechanic",
    steps=None,
    events=None,
    refs=(PARENT,),
    actions=("inspect", "take"),
):
    default_steps, default_events = definitions()
    with store.transaction() as connection:
        return store.save_objective_plan_in_connection(
            connection,
            session,
            npc,
            turn,
            event,
            steps=default_steps if steps is None else steps,
            events=default_events if events is None else events,
            current_objective_refs=refs,
            allowed_actions=actions,
        )


def read(store, *, session="game-a", npc="mechanic", refs=(PARENT,), limit=8):
    return store.list_objective_plans(session, npc, parent_refs=refs, limit=limit)


def test_completed_definitions_are_durable_without_content_publication_or_quest_quota(tmp_path):
    store = ContentStore(tmp_path / "state.db")
    store.register_objective("game-a", PARENT)
    assert read(store) == []
    assert save(store)
    steps, events = definitions()
    reopened = ContentStore(store.database)
    assert read(reopened) == [
        {
            "objective": PARENT.model_dump(mode="json"),
            "steps": [item.model_dump(mode="json") for item in steps],
            "events": [item.model_dump(mode="json") for item in events],
            "source_turn_id": "turn-1",
            "source_event_id": "completed-1",
            "revision": 1,
        }
    ]
    assert reopened.list_published("game-a") == []
    assert reopened.list_quests("game-a") == []
    assert reopened.quota_usage("game-a", "episode-1") == {"reserved": 0, "consumed": 0}
    with reopened.connection() as connection:
        assert connection.execute("SELECT COUNT(*) FROM narrative_content").fetchone()[0] == 0


def test_plan_and_replay_ledger_roll_back_with_completion_transaction(tmp_path):
    store = ContentStore(tmp_path / "state.db")
    store.register_objective("game-a", PARENT)
    steps, events = definitions()
    with (
        pytest.raises(RuntimeError, match="other completion write failed"),
        store.transaction() as connection,
    ):
        assert store.save_objective_plan_in_connection(
            connection,
            "game-a",
            "mechanic",
            "turn-1",
            "completed-1",
            steps=steps,
            events=events,
            current_objective_refs=[PARENT],
            allowed_actions=["inspect", "take"],
        )
        raise RuntimeError("other completion write failed")
    assert read(store) == []
    with store.connection() as connection:
        assert (
            connection.execute("SELECT COUNT(*) FROM narrative_objective_plan_commits").fetchone()[
                0
            ]
            == 0
        )
        with pytest.raises(ValueError, match="requires a completion transaction"):
            store.save_objective_plan_in_connection(
                connection,
                "game-a",
                "mechanic",
                "turn-1",
                "completed-1",
                steps=steps,
                current_objective_refs=[PARENT],
                allowed_actions=["inspect", "take"],
            )
    assert save(store)


def test_exact_replay_never_rewinds_newer_definition_and_changed_keys_are_rejected(tmp_path):
    store = ContentStore(tmp_path / "state.db")
    store.register_objective("game-a", PARENT)
    assert save(store)
    assert not save(store)
    steps, events = definitions()
    steps[0].description = "从已有的控制面板开始检查"
    assert save(store, turn="turn-2", event="completed-2", steps=steps, events=events)
    assert not save(store)
    current = read(store)[0]
    assert current["revision"] == 2 and current["source_turn_id"] == "turn-2"
    assert current["steps"][0]["description"] == steps[0].description
    for changed in (
        {"steps": steps},
        {"event": "different-event"},
        {"turn": "different-turn"},
        {"npc": "other-npc"},
    ):
        with pytest.raises(IdempotencyConflictError, match="completion replay differs"):
            save(store, **changed)
    assert read(store)[0] == current


def test_reads_require_actor_scope_authorized_parent_and_current_version(tmp_path):
    store = ContentStore(tmp_path / "state.db")
    store.register_objective("game-a", PARENT)
    store.register_objective("game-b", PARENT)
    save(store)
    assert read(store, session="game-b") == []
    assert read(store, npc="other-npc") == []
    assert read(store, refs=[]) == []
    assert read(store, refs=[PARENT.model_copy(update={"quest_id": "other-quest"})]) == []
    newer = PARENT.model_copy(update={"version": 3})
    store.register_objective("game-a", newer)
    assert read(store) == []
    assert read(store, refs=[newer]) == []
    assert not save(store)  # A past completion remains an idempotent no-op.
    with pytest.raises(ContentReviewError, match="stale parent"):
        save(store, turn="turn-2", event="completed-2")
    steps, events = definitions(newer)
    assert save(store, turn="turn-2", event="completed-2", steps=steps, events=events, refs=[newer])
    assert read(store, refs=[newer])[0]["objective"]["version"] == 3


@pytest.mark.parametrize(
    "failure", ["unknown-parent", "unauthorized-parent", "action", "cycle", "dependency"]
)
def test_invalid_definitions_never_enter_storage(tmp_path, failure):
    store = ContentStore(tmp_path / "state.db")
    if failure != "unknown-parent":
        store.register_objective("game-a", PARENT)
    steps, events = definitions()
    refs = [] if failure == "unauthorized-parent" else [PARENT]
    if failure == "action":
        steps[0].action = "spawn-item"
    elif failure == "cycle":
        steps[0].depends_on = ["take-tool"]
    elif failure == "dependency":
        steps[0].depends_on = ["another-parent-step"]
    with pytest.raises(ContentReviewError):
        save(store, steps=steps, events=events, refs=refs)
    assert read(store) == []


def test_reads_filter_stale_plans_before_bounded_limit(tmp_path):
    store = ContentStore(tmp_path / "state.db")
    other = ObjectiveRef(objective_id="existing-route", version=0)
    for ref in (PARENT, other):
        store.register_objective("game-a", ref)
    save(store)
    steps, events = definitions(other)
    save(store, turn="turn-2", event="completed-2", steps=steps, events=events, refs=[other])
    store.register_objective("game-a", other.model_copy(update={"version": 1}))
    assert [item["objective"] for item in read(store, refs=[PARENT, other], limit=1)] == [
        PARENT.model_dump(mode="json")
    ]
    assert read(store, limit=0) == []


def test_definition_and_reference_counts_are_bounded(tmp_path):
    store = ContentStore(tmp_path / "state.db")
    store.register_objective("game-a", PARENT)
    steps, events = definitions()
    with pytest.raises(ContentReviewError, match="definition limit exceeded"):
        save(store, steps=steps * 9)
    with pytest.raises(ContentReviewError, match="definition limit exceeded"):
        save(store, events=events * 9)
    with pytest.raises(ContentReviewError, match="parent reference limit exceeded"):
        read(store, refs=[PARENT] * 129)
    assert read(store) == []


def test_v1_database_migrates_without_losing_existing_objective_registry(tmp_path):
    database = tmp_path / "v1.db"
    with sqlite3.connect(database) as connection:
        connection.executescript(CONTENT_SCHEMA)
        connection.execute(
            "INSERT INTO narrative_objectives VALUES(?,?,?,?)",
            ("game-a", PARENT.objective_id, PARENT.model_dump_json(), PARENT.version),
        )
    store = ContentStore(database)
    assert store.get_objective("game-a", PARENT.objective_id) == PARENT
    assert save(store)
    reopened = ContentStore(database)
    assert read(reopened) == read(store)
    with reopened.connection() as connection:
        assert [
            row[0]
            for row in connection.execute(
                "SELECT version FROM narrative_content_schema ORDER BY version"
            )
        ] == [1, 2]
