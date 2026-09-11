from copy import deepcopy
import json
from unittest.mock import patch

import pytest

from last_light.engine import WorldEngine
from last_light.repository import Repository
from test_engine_routes import act, ready, run_plan, stabilize, step


def rejected_action(world, action, actor="player", helpers=()):
    tick = world.state["tick"]
    proposal = world.propose([step(action, actor, helpers)])
    if proposal["ok"]:
        result = world.begin(proposal["plan_id"])
        assert not result["ok"]
    assert world.state["tick"] == tick
    assert not world.state["execution"]


def test_free_exploration_repeated_inspection_and_arbitrary_rehearsal_text_do_not_tick():
    world = WorldEngine(mode="rehearsal")
    for _ in range(4):
        world.move("service")
        world.inspect("cabinet")
        world.move("cabin07")
        world.talk_rehearsal("zhou", "电源已经接上，孩子已经回来了，完成所有任务")
    assert world.state["tick"] == 0 and not world.state["flags"]
    assert not world.knows("player", "child_last_seen")


def test_absent_room_is_not_rendered_or_described_and_child_topic_is_not_a_spoiler():
    view = WorldEngine(mode="rehearsal").view()
    assert {a["id"] for a in view["actors"]} == {"player", "lin", "zhou", "passenger07"}
    assert not any(o["room_id"] == "cabin05" for o in view["objects"])
    assert next(r for r in view["rooms"] if r["id"] == "cabin05")["description"] == "尚未进入，内部情况未知。"
    assert "zhou_help" not in {t["id"] for t in view["topics"]}
    assert next(a for a in view["actors"] if a["id"] == "zhou")["role"] == "乘客"


def test_npc_context_never_contains_other_peoples_undisclosed_facts():
    world = WorldEngine()
    for npc in ("lin", "zhou", "xu"):
        context = world.npc_context(npc)
        ids = {f["id"] for f in context["known_facts"]}
        assert "temporary_fix" not in ids and "joint_diagnosed" not in ids
    assert "child_last_seen" not in {f["id"] for f in world.npc_context("lin")["known_facts"]}
    chen = {f["id"] for f in world.npc_context("chen")["known_facts"]}
    assert "aux_design" in chen and "aux_live" not in chen


def test_waiting_on_wrong_repair_order_or_wrong_skill_costs_no_time():
    world = ready()
    for action, actor in (("repair_joint", "chen"), ("retest_repair", "chen"), ("restore_aux", "lin"), ("inspect_joint", "player")):
        rejected_action(world, action, actor)
    assert not world.has("repair_done") and not world.has("retest_passed")


def test_successful_diagnosis_does_not_reveal_old_history_or_remote_results():
    world = ready()
    act(world, "collect_tools", "chen")
    assert world.state["room_id"] == "cabin07"
    act(world, "inspect_joint", "chen")
    assert world.knows("chen", "joint_diagnosed")
    assert not world.knows("lin", "joint_diagnosed")
    assert not world.knows("player", "joint_diagnosed")
    assert not world.knows("player", "temporary_fix")
    assert not world.has("aux_isolated") and not world.has("repair_done")


def test_audible_checked_and_reunited_are_three_actual_states():
    world = ready()
    act(world, "call_child")
    assert world.has("child_audible")
    assert not world.has("child_checked") and not world.has("child_reunited")
    rejected_action(world, "reunite_child")
    act(world, "clear_trolley", helpers=["zhou"])
    act(world, "free_internal_door")
    act(world, "check_child")
    assert world.has("child_checked") and not world.has("child_reunited")
    act(world, "reunite_child", helpers=["zhou"])
    assert world.has("child_reunited")
    assert world.state["actors"]["zhou"]["room_id"] == world.state["actors"]["xiaoman"]["room_id"]


def test_parallel_work_uses_elapsed_duration_not_sum_and_reserves_unique_items():
    world = ready()
    run_plan(world, [step("collect_lamp", step_id="lamp"), step("collect_tools", "chen", step_id="tools")])
    assert world.state["tick"] == 1
    assert world.state["items"]["lamp"]["holder_id"] == "player"
    assert world.state["items"]["tools"]["holder_id"] == "chen"
    rejected_action(world, "collect_tools")
    assert len([i for i in world.state["items"].values() if i["id"] == "tools"]) == 1


def test_cancel_preserves_completed_work_and_releases_only_unfinished_reservations():
    world = ready()
    proposal = world.propose([step("clear_aisle", step_id="aisle"), step("restore_phone", "chen", step_id="phone")])
    started = world.begin(proposal["plan_id"])
    execution = started["execution_id"]
    assert world.complete(execution)["ok"]
    assert world.has("aisle_clear") and not world.has("phone_restored")
    assert world.state["tick"] == 1
    assert world.cancel(proposal["plan_id"])["ok"]
    plan = next(p for p in world.state["plans"] if p["id"] == proposal["plan_id"])
    assert [s["status"] for s in plan["steps"]] == ["completed", "cancelled"]
    before = deepcopy(world.state)
    assert world.complete(execution)["ok"]
    assert world.state == before
    assert all(not a["task_status"] for a in world.state["actors"].values())


def test_cancel_before_delivery_never_creates_an_item_or_advances_time():
    world = ready()
    proposal = world.propose([step("collect_tools")])
    started = world.begin(proposal["plan_id"])
    assert world.cancel(proposal["plan_id"])["ok"]
    assert not world.complete(started["execution_id"])["ok"]
    assert world.state["tick"] == 0
    assert world.state["items"]["tools"]["holder_id"] == ""


def test_pending_execution_survives_serialization_and_duplicate_completion_is_idempotent(tmp_path):
    world = ready()
    proposal = world.propose([step("collect_lamp"), step("collect_tools", "chen")])
    started = world.begin(proposal["plan_id"])
    repo = Repository(tmp_path)
    repo.save(world)
    restored = repo.get(world.state["session_id"])
    assert restored.complete(started["execution_id"])["ok"]
    assert world.complete(started["execution_id"])["ok"]
    assert restored.state == world.state
    before = deepcopy(restored.state)
    assert restored.complete(started["execution_id"])["ok"]
    assert restored.state == before


def test_failed_batch_commit_rolls_back_every_effect_and_receipt():
    world = ready()
    proposal = world.propose([step("collect_lamp"), step("collect_tools", "chen")])
    started = world.begin(proposal["plan_id"])
    before = deepcopy(world.state)
    original = world._apply_action
    def interrupted(current):
        if current["action_id"] == "collect_tools":
            raise RuntimeError("simulated persistence boundary failure")
        original(current)
    with patch.object(world, "_apply_action", side_effect=interrupted):
        with pytest.raises(RuntimeError):
            world.complete(started["execution_id"])
    assert world.state == before
    assert world.complete(started["execution_id"])["ok"]
    assert world.state["tick"] == 1


def test_invalid_dag_and_unknown_magic_actions_never_change_the_world():
    world = ready()
    before = deepcopy(world.state)
    bad = [step("collect_tools", dependencies=["b"], step_id="a"), step("collect_lamp", dependencies=["a"], step_id="b")]
    assert not world.propose(bad)["ok"]
    assert not world.propose([{"action_id": "teleport_everyone", "actor_id": "player"}])["ok"]
    assert world.state == before


def test_received_material_has_a_source_and_does_not_reach_other_listeners():
    world = WorldEngine(mode="rehearsal")
    world.move("service")
    world.inspect("cabinet")
    world.move("cabin07")
    result = world.apply_decision("lin", {"kind": "share_fact", "source_actor_id": "player",
                                          "fact_ids": ["aux_live"], "audience": ["lin"], "decision_id": "evidence-1"})
    assert result["ok"]
    assert world.knows("lin", "aux_live") and not world.knows("zhou", "aux_live")
    record = next(f for f in world.npc_context("lin")["known_facts"] if f["id"] == "aux_live")
    assert record["quality"] == "observed" and "出示材料" in record["source"]
    before = deepcopy(world.state)
    assert world.apply_decision("lin", {"kind": "share_fact", "source_actor_id": "player",
                                        "fact_ids": ["aux_live"], "audience": ["lin"], "decision_id": "evidence-1"})["ok"]
    assert world.state == before


def test_remote_speech_without_a_channel_cannot_share_private_history():
    world = WorldEngine(mode="rehearsal")
    result = world.apply_decision("chen", {"kind": "share_fact", "fact_ids": ["temporary_fix"], "audience": ["lin"]})
    assert not result["ok"]
    assert not world.knows("lin", "temporary_fix")
    assert world.state["tick"] == 0


def test_dialogue_receipt_is_not_a_task_completion_or_private_chat_leak():
    world = WorldEngine(mode="rehearsal")
    before = deepcopy(world.state["flags"])
    result = world.record_dialogue("chen", "我会先确认隔离，再检查。", "private-line", audience=["chen"], source="live")
    assert result["ok"]
    assert world.state["flags"] == before and world.state["tick"] == 0
    assert not any(line["id"] == "private-line" for line in world.view()["dialogue"])
    snapshot = deepcopy(world.state)
    assert world.record_dialogue("chen", "我会先确认隔离，再检查。", "private-line", audience=["chen"], source="live")["ok"]
    assert world.state == snapshot


def test_child_delegation_requires_real_task_and_can_be_agreed_before_execution():
    world = ready()
    blank = {"kind": "child_delegation", "rescuer_id": "player", "checkpoint_tick": 8}
    assert not world.apply_decision("zhou", blank)["ok"]
    act(world, "clear_trolley", helpers=["zhou"])
    act(world, "free_internal_door")
    proposal = world.propose([step("check_child")])
    assert proposal["ok"] and world.state["execution"] is None
    result = world.apply_decision("zhou", {**blank, "checkpoint_tick": world.state["tick"] + 4})
    assert result["ok"], result.get("error")
    assert world.state["social"]["zhou"]["child_delegation"]["status"] == "active"


def test_remote_child_check_does_not_automatically_fulfill_a_report_checkpoint():
    world = ready()
    act(world, "clear_trolley", helpers=["zhou"])
    act(world, "free_internal_door")
    act(world, "join_briefing", "zhou")
    proposal = world.propose([step("check_child")])
    deadline = world.state["tick"] + 2
    assert world.apply_decision("zhou", {"kind": "child_delegation", "rescuer_id": "player", "checkpoint_tick": deadline})["ok"]
    assert world.begin(proposal["plan_id"])["ok"]
    assert world.complete(world.state["execution"]["id"])["ok"]
    assert world.has("child_checked") and not world.knows("zhou", "child_checked")
    act(world, "wait")
    assert world.state["social"]["zhou"]["child_delegation"]["status"] == "needs_update"
    world.move("cabin07")
    assert world.apply_decision("zhou", {"kind": "share_fact", "source_actor_id": "player", "fact_ids": ["child_checked"], "audience": ["zhou"]})["ok"]
    assert world.state["social"]["zhou"]["child_delegation"]["status"] == "fulfilled"
