"""Social invariants on the complete authoritative WorldEngine."""
from copy import deepcopy

from last_light.engine import WorldEngine


def world():
    return WorldEngine(session_id="social_test")


def accept(w, npc, action, **extra):
    return w.apply_decision(npc, {"kind": "accept_task", "action_ids": [action], "conditions": [], **extra})


def plan(w, action, actor="player"):
    return w.propose([{"action_id": action, "actor_id": actor}])["plan_id"]


def execute(w, plan_id):
    started = w.begin(plan_id)
    assert started["ok"], started.get("error")
    result = w.complete(started["execution_id"])
    assert result["ok"], result.get("error")


def test_owned_fact_sharing_is_scoped_and_reported_not_global_verified():
    w = world()
    result = w.apply_decision("lin", {"kind": "share_fact", "fact_ids": ["crew_report"],
                                      "audience": ["player", "zhou"]})
    assert result["ok"]
    assert w.knows("player", "crew_report") and w.knows("zhou", "crew_report")
    assert not w.knows("chen", "crew_report") and not w.knows("xu", "crew_report")
    record = next(f for f in w.state["knowledge"]["zhou"] if f["id"] == "crew_report")
    assert record["quality"] == "reported"
    assert not w.apply_decision("lin", {"kind": "share_fact", "fact_ids": ["temporary_fix"], "audience": ["player"]})["ok"]
    assert not w.apply_decision("lin", {"kind": "share_fact", "fact_ids": ["crew_report"], "audience": ["chen"]})["ok"]


def test_player_can_present_real_observation_but_not_other_characters_secrets():
    w = world()
    w.move("cabin06")
    w.inspect("blocked_door")
    w.move("cabin07")
    result = w.apply_decision("lin", {"kind": "share_fact", "source_actor_id": "player",
                                      "fact_ids": ["door_jammed"], "audience": ["lin"]})
    assert result["ok"] and w.knows("lin", "door_jammed")
    assert not w.apply_decision("lin", {"kind": "share_fact", "source_actor_id": "player",
        "fact_ids": ["temporary_fix"], "audience": ["lin"]})["ok"]
    assert not w.apply_decision("lin", {"kind": "share_fact", "source_actor_id": "chen",
        "fact_ids": ["temporary_fix"], "audience": ["lin"]})["ok"]


def test_loan_is_idempotent_agreement_and_not_physical_delivery():
    w = world()
    before = deepcopy(w.state["items"])
    decision = {"kind": "loan", "purpose": "radio", "recipient_id": "player",
                "deadline_tick": 6, "reserve": 4, "decision_id": "loan_once"}
    assert w.apply_decision("xu", decision)["ok"]
    revision = w.state["revision"]
    assert w.apply_decision("xu", decision)["ok"] and w.state["revision"] == revision
    assert w.state["items"] == before and w.state["tick"] == 0
    assert w._loan()["status"] == "accepted"
    assert not w.apply_decision("xu", {**decision, "reserve": 5})["ok"]
    assert not w.apply_decision("xu", {"kind": "withdraw_loan"})["ok"]
    assert not w.apply_decision("chen", {**decision, "decision_id": "stolen_owner"})["ok"]


def test_withdrawal_after_real_transfer_does_not_teleport_or_refund():
    w = world()
    w.move("cabin06")
    assert w.apply_decision("xu", {"kind": "loan", "purpose": "radio", "recipient_id": "player",
                                   "deadline_tick": 6, "reserve": 4})["ok"]
    execute(w, plan(w, "take_backup"))
    assert w.state["items"]["backup"]["holder_id"] == "player"
    w._advance_time(5)
    before, tick = deepcopy(w.state["items"]), w.state["tick"]
    assert w.apply_decision("xu", {"kind": "withdraw_loan", "reason": "期限已到"})["ok"]
    assert w.state["items"] == before and w.state["tick"] == tick
    assert w._loan()["status"] == "reclaim_requested"


def test_conditions_gate_execution_and_helper_acceptance_cannot_grant_lead_skill():
    w = world()
    assert accept(w, "chen", "collect_tools", conditions=["with_helper"])["ok"]
    primary = {"action_id": "collect_tools", "actor_id": "chen", "target_id": "tool_rack", "helpers": []}
    assert "协助" in w._check_action(primary)
    assert accept(w, "lin", "collect_tools", role="helper")["ok"]
    assert not w._check_action({**primary, "helpers": ["lin"]})
    assert accept(w, "zhou", "repair_joint", role="helper")["ok"]
    assert not w.propose([{"action_id": "repair_joint", "actor_id": "zhou"}])["ok"]
    assert not accept(w, "zhou", "call_control", role="helper")["ok"]
    assert not accept(w, "chen", "repair_joint", conditions=["ignore_all_safety"])["ok"]


def test_delegation_needs_existing_accepted_feasible_rescue_and_checkpoint():
    w = world()
    offer = {"kind": "child_delegation", "rescuer_id": "lin", "checkpoint_tick": 2}
    assert not w.apply_decision("zhou", offer)["ok"]
    assert accept(w, "lin", "check_child")["ok"]
    w._add_flag("trolley_cleared")
    w._add_flag("inner_door_open")
    rescue = plan(w, "check_child", "lin")
    # The player has confirmed a real plan and Lin has independently consented.
    # Delegation must be possible before begin(), which locks dialogue in the UI.
    assert w.apply_decision("zhou", offer)["ok"]
    assert w.state["execution"] is None
    delegation = w.state["social"]["zhou"]["child_delegation"]
    assert delegation["plan_id"] == rescue and delegation["status"] == "active"
    assert not w.has("child_checked") and w.state["tick"] == 0
    assert not w.apply_decision("zhou", {**offer, "checkpoint_tick": 0})["ok"]


def test_revoke_does_not_undo_fulfilled_task_or_modify_physics():
    w = world()
    assert accept(w, "xu", "close_vent")["ok"]
    execute(w, plan(w, "close_vent", "xu"))
    before, tick = deepcopy(w.state["items"]), w.state["tick"]
    assert w.apply_decision("xu", {"kind": "revoke_task", "action_ids": ["close_vent"]})["ok"]
    assert w.has("vent_closed") and w.state["items"] == before and w.state["tick"] == tick
    assert any(p.get("action_id") == "close_vent" and p["status"] == "fulfilled" for p in w.state["promises"])
    assert "close_vent" not in w.state["social"]["xu"]["accepted_tasks"]


def test_delivered_line_is_idempotent_and_unheard_private_line_is_not_in_player_view():
    w = world()
    assert w.record_dialogue("chen", "这段话只有我自己听见。", "private", audience=["chen"])["ok"]
    assert not any(line["id"] == "private" for line in w.view()["dialogue"])
    assert w.record_dialogue("lin", "我还没有收到封锁回执。", "heard", audience=["player"])["ok"]
    revision = w.state["revision"]
    assert w.record_dialogue("lin", "我还没有收到封锁回执。", "heard", audience=["player"])["ok"]
    assert w.state["revision"] == revision and w.state["tick"] == 0
    assert not w.record_dialogue("lin", "已经封锁了。", "heard", audience=["player"])["ok"]
    assert sum(line["id"] == "heard" for line in w.view()["dialogue"]) == 1
