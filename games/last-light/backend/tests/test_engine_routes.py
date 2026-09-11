"""Whole stories from a fresh save; no physical success flags are injected."""
from copy import deepcopy

import pytest

from last_light.content import ACTIONS, ACTOR_IDS
from last_light.engine import WorldEngine


def step(action, actor="player", helpers=(), dependencies=(), step_id=""):
    return {"id": step_id, "action_id": action, "actor_id": actor,
            "target_id": ACTIONS[action]["target_id"], "helpers": list(helpers),
            "depends_on": list(dependencies)}


def run_plan(world, steps, title="集成验证中的明确救援安排"):
    proposal = world.propose(steps, title)
    assert proposal["ok"], proposal.get("error")
    plan_id = proposal["plan_id"]
    for _ in range(80):
        plan = next(p for p in world.state["plans"] if p["id"] == plan_id)
        if plan["status"] == "completed":
            return plan
        result = world.begin(plan_id)
        assert result["ok"], (result.get("error"), plan["conditions"], world.state["tick"])
        result = world.complete(result["execution_id"])
        assert result["ok"], result.get("error")
        if world.state["ending"]:
            return plan
    pytest.fail("Plan did not settle within its bounded work")


def act(world, action, actor="player", helpers=()):
    return run_plan(world, [step(action, actor, helpers)])


def ready():
    world = WorldEngine(mode="rehearsal")
    for npc, topics, room in (
        ("lin", ["lin_report", "lin_help"], "cabin07"),
        ("zhou", ["zhou_child", "zhou_help"], "cabin07"),
        ("chen", ["chen_work"], "service"),
        ("xu", ["xu_mother", "xu_help"], "cabin06"),
    ):
        assert world.move(room)["ok"]
        for topic in topics:
            result = world.talk_rehearsal(npc, "", topic)
            assert result["ok"], result.get("error")
    for room, objects in (("service", ["cabinet", "fixed_phone"]), ("cabin06", ["blocked_door", "oxygen", "backup_supply"])):
        assert world.move(room)["ok"]
        for oid in objects:
            assert world.inspect(oid)["ok"]
    assert world.move("cabin07")["ok"]
    assert world.state["tick"] == 0
    return world


def stabilize(world):
    run_plan(world, [step("isolate_aux", "chen", step_id="power"),
                     step("clear_aisle", step_id="aisle"),
                     step("close_vent", "xu", step_id="air")])
    assert world.state["tick"] == 1
    act(world, "move_mother", helpers=["xu"])


def repair(world):
    actions = ["collect_tools", "collect_spares", "inspect_joint", "verify_isolation", "repair_joint", "retest_repair", "restore_aux"]
    run_plan(world, [step(a, "chen", dependencies=[] if i == 0 else ["work" + str(i - 1)], step_id="work" + str(i))
                     for i, a in enumerate(actions)])


def inner_child(world):
    act(world, "clear_trolley", helpers=["zhou"])
    act(world, "free_internal_door")
    act(world, "check_child")
    act(world, "reunite_child", helpers=["zhou"])
    act(world, "assign_child_care", "zhou")


def control(world):
    act(world, "restore_phone")
    act(world, "call_control")


def prepare_stay(world, gather_adults=True):
    stabilize(world)
    repair(world)
    inner_child(world)
    control(world)
    act(world, "count_passengers")
    act(world, "shelter_group")
    if gather_adults:
        act(world, "join_briefing", helpers=["lin", "zhou", "chen", "xu"])
    act(world, "final_sweep")


def test_complete_stay_route_requires_real_repair_reunion_and_gathering():
    world = ready()
    prepare_stay(world)
    assert not world.knows("player", "temporary_fix")  # cooperation did not require confession
    assert all(world.state["actors"][a]["room_id"] == "cabin07" for a in ACTOR_IDS)
    act(world, "await_rescue")
    assert world.state["ending"] == "stay_all"
    assert world.has("retest_passed") and world.has("child_reunited")
    assert not world.state["hazard"]["mother_worse"]
    assert WorldEngine(state=deepcopy(world.state)).state == world.state


def test_complete_external_evacuation_route_does_not_require_inner_door_or_repair():
    world = ready()
    stabilize(world)
    control(world)
    act(world, "collect_lamp", "lin")
    act(world, "scout_walkway", "lin")
    act(world, "open_outer_door", "lin")
    act(world, "light_walkway", "lin")
    assert not world.can_visit("cabin05")
    assert world.move("tunnel")["ok"]
    exterior = next(o for o in world.view()["objects"] if o["id"] == "outer_door05")
    assert exterior["room_id"] == "tunnel" and "看不到" in exterior["description"]
    assert not any(a["id"] == "xiaoman" for a in world.view()["actors"])
    act(world, "open_external05")
    assert world.can_visit("cabin05") and not world.has("inner_door_open")
    act(world, "check_child")
    act(world, "count_passengers")
    act(world, "escort_child", helpers=["zhou"])
    act(world, "assign_child_care", "zhou")
    act(world, "collect_stretcher")
    act(world, "prepare_stretcher")
    act(world, "escort_mother", helpers=["xu"])
    act(world, "escort_passengers", "lin")
    act(world, "move_to_refuge", "chen")
    act(world, "final_sweep")
    act(world, "finish_evacuation")
    assert world.state["ending"] == "evacuate_all"
    assert not world.has("repair_done") and not world.has("inner_door_open")
    assert all(a["room_id"] == "tunnel" for a in world.state["actors"].values())
    assert WorldEngine(state=deepcopy(world.state)).state == world.state


def test_omitted_engineer_is_not_teleported_into_a_good_ending():
    world = ready()
    prepare_stay(world, gather_adults=False)
    assert world.state["actors"]["chen"]["room_id"] == "service"
    act(world, "await_rescue")
    assert world.state["ending"] == "costly"
    assert world.state["actors"]["chen"]["room_id"] == "service"
    assert "陈默" in world.state["ending_text"]


def test_failure_comes_from_actual_uncontrolled_hazard_or_power_loss():
    world = WorldEngine(mode="rehearsal")
    for _ in range(50):
        if world.state["ending"]:
            break
        act(world, "wait")
    assert world.state["ending"] == "failed"
    assert world.state["tick"] > 0
    assert world.state["hazard"]["heat"] >= 30 or world.state["hazard"].get("unpowered_ticks", 0) >= 7


def test_early_physical_protection_prevents_the_written_mother_crisis():
    world = ready()
    stabilize(world)
    for _ in range(12):
        act(world, "wait")
    assert world.has("mother_protected")
    assert world.state["hazard"]["mother_exposure"] == 0
    assert not world.state["hazard"]["mother_worse"]
    assert not any(e["kind"] == "mother_need_changed" for e in world.state["events"])
