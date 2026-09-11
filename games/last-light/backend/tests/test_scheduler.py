"""Scheduler invariants against real content; no model or Unity required."""
from copy import deepcopy

from last_light.content import ACTIONS, OBJECTS
from last_light.models import new_state
from last_light.scheduler import PlanRules


class SchedulerWorld(PlanRules):
    def __init__(self):
        self.state = new_state("scheduler_test")
        self.effects = []
        self.pause_at = None
        self.invalidated = set()
        self.on_advance = lambda: None
        self.on_apply = lambda step: None

    def _id(self, prefix):
        self.state["next_id"] += 1
        return f"{prefix}_{self.state['next_id']}"

    def _result(self, ok=True, error="", **extra):
        return {"ok": ok, "error": error, "view": deepcopy(self.state), **extra}

    def _changed(self):
        self.state["revision"] += 1

    def has(self, flag):
        return flag in self.state["flags"]

    def _event(self, kind, text, witnesses):
        self.state["events"].append({"kind": kind, "text": text, "witnesses": witnesses})

    def _target_room(self, target_id):
        return OBJECTS[target_id]["room_id"]

    def _check_action(self, step):
        if step["action_id"] in self.invalidated:
            return "原先的同意条件已改变。"
        missing = [f for f in ACTIONS[step["action_id"]]["requires"] if not self.has(f)]
        return "缺少：" + ",".join(missing) if missing else ""

    def _action_resources(self, step):
        resource = ACTIONS[step["action_id"]]["resource"]
        return {resource} if resource else set()

    def _apply_action(self, step):
        self.effects.append(step["action_id"])
        for flag in ACTIONS[step["action_id"]]["provides"]:
            if not self.has(flag):
                self.state["flags"].append(flag)
        self.on_apply(step)

    def _advance_time(self, duration):
        assert duration == 1
        self.state["tick"] += 1
        self.on_advance()
        return self.state["tick"] == self.pause_at


def step(action_id, actor_id="player", **extra):
    return {"action_id": action_id, "actor_id": actor_id,
            "target_id": ACTIONS[action_id]["target_id"], **extra}


def repair_ready(world):
    world.state["flags"] += ["aux_isolated", "isolation_verified", "joint_diagnosed", "spares_ready", "tools_ready"]
    world.state["flags"] += ACTIONS["call_control"]["requires"]


def test_parallel_partial_work_uses_maximum_time_not_sum():
    world = SchedulerWorld()
    repair_ready(world)
    plan_id = world.propose([step("repair_joint", "chen"), step("clear_aisle")])["plan_id"]
    assert world._plan(plan_id)["total_ticks"] == 3
    first = world.begin(plan_id)["execution_id"]
    assert world.state["execution"]["duration"] == 1
    world.complete(first)
    assert world.state["tick"] == 1 and world.effects == ["clear_aisle"]
    assert world._plan(plan_id)["steps"][0]["remaining"] == 2
    second = world.begin(plan_id)["execution_id"]
    world.complete(second)
    assert world.state["tick"] == 3 and world._plan(plan_id)["status"] == "completed"


def test_propose_preserves_unmet_future_dependencies_and_rejects_cycles():
    world = SchedulerWorld()
    result = world.propose([step("collect_tools", "chen", id="get"),
                            step("inspect_joint", "chen", id="inspect", depends_on=["get"])])
    assert result["ok"] and world._plan(result["plan_id"])["conditions"]
    first = world.begin(result["plan_id"])["execution_id"]
    assert len(world.state["execution"]["step_ids"]) == 1
    world.complete(first)
    second = world.begin(result["plan_id"])["execution_id"]
    world.complete(second)
    assert world.state["tick"] == 3 and world.has("joint_diagnosed")
    bad = world.propose([step("clear_aisle", id="a", depends_on=["b"]),
                         step("close_vent", "lin", id="b", depends_on=["a"])])
    assert not bad["ok"] and "循环" in bad["error"]


def test_same_resource_or_helper_cannot_be_used_twice_in_one_batch():
    world = SchedulerWorld()
    world.state["flags"].append("tools_ready")
    plan = world.propose([step("collect_tools"), step("inspect_joint", "chen")])["plan_id"]
    world.begin(plan)
    assert len(world.state["execution"]["steps"]) == 1
    world.cancel(plan)
    world.state["flags"].append("door_jammed")
    plan = world.propose([step("clear_trolley", "zhou", helpers=["lin"]),
                          step("close_vent", "lin")])["plan_id"]
    world.begin(plan)
    assert len(world.state["execution"]["steps"]) == 1
    assert "lin" in world.state["execution"]["actor_ids"]


def test_crisis_pauses_every_parallel_task_without_losing_progress():
    world = SchedulerWorld()
    repair_ready(world)
    world.pause_at = 1
    plan_id = world.propose([step("repair_joint", "chen"), step("call_control")])["plan_id"]
    first = world.begin(plan_id)["execution_id"]
    assert world.state["execution"]["duration"] == 2
    result = world.complete(first)
    assert result["paused"] and result["elapsed_ticks"] == 1
    assert [s["remaining"] for s in world._plan(plan_id)["steps"]] == [2, 1]
    assert not world.effects and world.state["execution"] is None
    second = world.begin(plan_id)["execution_id"]
    world.complete(second)
    assert world.effects == ["call_control"] and world.state["tick"] == 2
    third = world.begin(plan_id)["execution_id"]
    world.complete(third)
    assert world.has("repair_done") and world.state["tick"] == 3


def test_changed_condition_stops_work_before_commit():
    world = SchedulerWorld()
    repair_ready(world)
    world.on_advance = lambda: world.invalidated.add("repair_joint")
    plan_id = world.propose([step("repair_joint", "chen")])["plan_id"]
    execution = world.begin(plan_id)["execution_id"]
    result = world.complete(execution)
    assert result["elapsed_ticks"] == 1 and not world.effects
    pending = world._plan(plan_id)["steps"][0]
    assert pending["remaining"] == 2 and pending["status"] == "waiting"
    assert not world.begin(plan_id)["ok"]


def test_same_tick_completion_rechecks_after_other_side_effects():
    world = SchedulerWorld()
    world.on_apply = lambda completed: world.invalidated.add("isolate_aux")
    plan_id = world.propose([step("close_vent"), step("isolate_aux", "lin")])["plan_id"]
    execution = world.begin(plan_id)["execution_id"]
    world.complete(execution)
    assert world.effects == ["close_vent"]
    assert not world.has("aux_isolated")
    assert world._plan(plan_id)["steps"][1]["remaining"] == 1


def test_cancel_preserves_finished_effects_and_duplicate_completion_is_inert():
    world = SchedulerWorld()
    repair_ready(world)
    plan_id = world.propose([step("clear_aisle"), step("repair_joint", "chen")])["plan_id"]
    first = world.begin(plan_id)["execution_id"]
    world.complete(first)
    before = deepcopy(world.state)
    assert world.complete(first)["ok"] and world.state == before
    second = world.begin(plan_id)["execution_id"]
    world.cancel(plan_id)
    assert world.has("aisle_clear") and not world.has("repair_done")
    assert world.state["tick"] == 1 and world.state["execution"] is None
    assert world._plan(plan_id)["steps"][0]["status"] == "completed"
    assert not world.complete(second)["ok"]
    before = deepcopy(world.state)
    assert world.cancel(plan_id)["ok"] and world.state == before


def test_untrusted_client_cannot_supply_duration_status_or_completion():
    world = SchedulerWorld()
    result = world.propose([step("clear_aisle", status="completed", duration=0, remaining=0)])
    normalized = world._plan(result["plan_id"])["steps"][0]
    assert normalized["duration"] == normalized["remaining"] == 1
    assert normalized["status"] == "pending" and world.state["tick"] == 0
    assert not world.propose([step("repair_joint", "zhou")])["ok"]
    assert not world.propose([step("clear_aisle", helpers=["xiaoman"])])["ok"]
    assert not world.propose([step("clear_aisle", depends_on=["nonexistent"])])["ok"]
