"""Free deterministic verification of presentation catalogue and visibility."""
from copy import deepcopy
import json

from last_light.content import ACTIONS
from last_light.engine import WorldEngine
from last_light.presentation_content import ACTION_PRESENTATIONS, CLIP_IDS, ITEM_IDS, SOCKET_IDS, export_catalog
from test_engine_routes import act, inner_child, ready, run_plan, step
from test_engine_power import lend


def begin_one(world, action_id, actor="player", helpers=()):
    proposal = world.propose([step(action_id, actor, helpers)])
    assert proposal["ok"], proposal.get("error")
    result = world.begin(proposal["plan_id"])
    assert result["ok"], result.get("error")
    return result["execution_id"], result["view"]["execution"]["steps"][0]


def test_catalogue_exactly_covers_all_actions_clips_sockets_and_six_items():
    catalog = export_catalog()
    assert len(catalog["actions"]) == 51
    assert {entry["action_id"] for entry in catalog["actions"]} == set(ACTIONS)
    assert len(CLIP_IDS) == len(set(CLIP_IDS)) == 32
    assert len(SOCKET_IDS) == len(set(SOCKET_IDS))
    assert set(ITEM_IDS) == set(WorldEngine().state["items"])
    for entry in catalog["actions"]:
        assert all(entry[key] in CLIP_IDS for key in ("preparation_clip", "result_clip", "failed_clip"))
        assert set(entry["resource_ids"]) <= set(ITEM_IDS)
        assert set(entry["socket_ids"]) <= set(SOCKET_IDS)
        assert all(isinstance(role, str) for role in entry["participant_roles"])
    assert json.loads(json.dumps(catalog)) == catalog


def test_export_does_not_share_mutable_catalogue_objects():
    exported = export_catalog()
    exported["actions"][0]["resource_ids"].append("imaginary_item")
    assert "imaginary_item" not in ACTION_PRESENTATIONS["collect_tools"]["resource_ids"]


def test_critical_actions_have_distinct_authored_behaviour_and_no_fake_placed_lamp():
    assert ACTION_PRESENTATIONS["repair_joint"]["result_clip"] == "repair_kneel"
    assert ACTION_PRESENTATIONS["retest_repair"]["result_clip"] == "verify_meter"
    assert ACTION_PRESENTATIONS["isolate_aux"]["result_clip"] == "switch_off"
    assert ACTION_PRESENTATIONS["restore_aux"]["result_clip"] == "switch_on"
    assert ACTION_PRESENTATIONS["clear_trolley"]["result_clip"] == "push_cart"
    assert ACTION_PRESENTATIONS["escort_mother"]["preparation_clip"] == "lift_stretcher"
    assert ACTION_PRESENTATIONS["light_walkway"]["result_clip"] == "point_route"


def test_borrow_endpoints_are_actual_visible_people_and_projection_is_read_only():
    world = ready()
    lend(world)
    execution, projected = begin_one(world, "take_backup")
    snapshot = deepcopy(world.state)
    assert projected["presentation"]["visual_kind"] == "handoff"
    assert projected["source_id"] == "xu" and projected["destination_id"] == "player"
    assert set(projected["participant_ids"]) == {"player", "xu"}
    assert projected["item_ids"] == ["backup"]
    assert projected["source_room_id"] == projected["destination_room_id"] == "cabin06"
    assert world.state["items"]["backup"]["holder_id"] == "xu"
    json.dumps(world.view())
    world.npc_context("xu")
    assert world.state == snapshot
    assert world.complete(execution)["ok"]
    assert world.state["items"]["backup"]["holder_id"] == "player"


def test_connection_endpoint_is_hidden_until_it_is_in_the_current_scene():
    world = ready()
    lend(world)
    act(world, "take_backup")
    execution, projected = begin_one(world, "connect_radio")
    assert projected["source_id"] == "player"
    assert projected["destination_id"] == projected["destination_room_id"] == ""
    assert projected["visible_target_id"] == ""  # radio is in07, observer is still06
    assert projected["item_ids"] == ["backup"]
    assert world.complete(execution)["ok"]
    _, projected = begin_one(world, "disconnect_radio")
    assert projected["source_id"] == "radio" and projected["destination_id"] == "player"
    assert projected["source_room_id"] == projected["destination_room_id"] == "cabin07"


def test_initial_activity_does_not_reveal_the_unheard_child_story():
    world = WorldEngine()
    before = deepcopy(world.state)
    zhou = next(a for a in world.view()["actors"] if a["id"] == "zhou")
    assert zhou["role"] == "乘客" and zhou["companions"] == []
    assert zhou["attention_target_id"] == "outer_door07"
    assert "xiaoman" not in json.dumps(zhou)
    lin_scene = world.npc_context("lin")["scene"]
    assert not any(a["id"] == "xiaoman" for a in lin_scene["actors"])
    assert world.state == before


def test_remote_work_does_not_expose_actor_location_item_custody_or_new_endpoints():
    world = ready()
    act(world, "collect_tools", "chen")
    _, projected = begin_one(world, "inspect_joint", "chen")
    assert world.state["room_id"] == "cabin07"
    for key in ("source_id", "destination_id", "source_room_id", "destination_room_id", "visible_target_id"):
        assert projected[key] == ""
    assert projected["participant_ids"] == projected["item_ids"] == []
    assert world._actor_presentation("chen", "lin") == {
        "activity": "unobserved", "attention_target_id": "", "health_display": "unknown", "companions": []}


def test_offscreen_handoff_recipient_is_not_added_to_visible_participants():
    world = ready()
    act(world, "collect_lamp")
    _, projected = begin_one(world, "give_lamp")
    assert projected["source_id"] == "player" and projected["source_room_id"] == "service"
    assert projected["destination_id"] == projected["destination_room_id"] == ""
    assert "lin" not in projected["participant_ids"]
    assert projected["item_ids"] == ["lamp"]


def test_physically_checked_child_is_unassessed_to_a_viewer_who_never_received_the_result():
    world = ready()
    act(world, "clear_trolley", helpers=["zhou"])
    act(world, "free_internal_door")
    world.move("cabin07")
    act(world, "check_child", "chen")
    assert world.has("child_checked") and not world.knows("player", "child_checked")
    world.move("cabin05")
    child = next(a for a in world.view()["actors"] if a["id"] == "xiaoman")
    assert child["health_display"] == "unassessed"
    chen_child = next(a for a in world.npc_context("chen")["scene"]["actors"] if a["id"] == "xiaoman")
    assert chen_child["health_display"] == "minor_scratches"
    assert world.apply_decision("chen", {"kind": "share_fact", "fact_ids": ["child_checked"], "audience": ["player"]})["ok"]
    child = next(a for a in world.view()["actors"] if a["id"] == "xiaoman")
    assert child["health_display"] == "reported_minor_scratches"


def test_visible_support_pose_neither_rewrites_medical_history_nor_exposes_it_remotely():
    world = ready()
    for _ in range(8):
        act(world, "wait")
    assert world.state["hazard"]["mother_worse"]
    assert world._actor_presentation("mother", "lin")["health_display"] == "unknown"
    world.move("cabin06")
    before = deepcopy(world.state)
    mother = next(a for a in world.view()["actors"] if a["id"] == "mother")
    assert mother["activity"] == "resting" and mother["health_display"] == "needs_support"
    world.npc_context("xu")
    assert world.state == before


def test_partial_batch_exposes_remaining_work_without_claiming_result_completion():
    world = ready()
    proposal = world.propose([step("clear_aisle", step_id="aisle"), step("restore_phone", "chen", step_id="phone")])
    begun = world.begin(proposal["plan_id"])
    execution = begun["view"]["execution"]
    phone = next(s for s in execution["steps"] if s["id"] == "phone")
    assert execution["duration"] == 1 and phone["remaining"] == 2
    assert phone["status"] == "executing"
    assert phone["presentation"]["result_clip"] == "connect_cable"
    after = world.complete(execution["id"])["view"]
    phone = next(s for p in after["plans"] for s in p["steps"] if p["id"] == proposal["plan_id"] and s["id"] == "phone")
    assert phone["remaining"] == 1 and phone["status"] != "completed"
    assert not world.has("phone_restored")


def test_all_51_step_projections_are_json_safe_and_never_mutate_authority():
    world = WorldEngine()
    before = deepcopy(world.state)
    visible = world._visible_entity_ids()
    for index, (action_id, spec) in enumerate(ACTIONS.items()):
        raw = step(action_id, spec["actors"][0], step_id=str(index))
        projected = world._step_view(raw)
        assert projected["presentation"]["action_id"] == action_id
        assert set(projected["item_ids"] + projected["participant_ids"]) <= visible
        assert all(not projected[key] or projected[key] in visible for key in ("source_id", "destination_id", "visible_target_id"))
        json.dumps(projected, allow_nan=False)
    assert world.state == before
