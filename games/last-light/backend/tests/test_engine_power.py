from copy import deepcopy

from test_engine_routes import act, ready, stabilize
from test_engine_invariants import rejected_action


def test_restored_train_supply_does_not_magically_charge_portable_medical_device():
    from test_engine_routes import prepare_stay
    world = ready()
    prepare_stay(world)
    before = world.state["items"]["medical"]["charge"]
    assert world.state["items"]["medical"]["connected_to"] == "internal"
    act(world, "wait")
    act(world, "wait")
    assert world.state["items"]["medical"]["charge"] == before - 1


def lend(world, duration=6):
    assert world.move(world.state["actors"]["xu"]["room_id"])["ok"]
    result = world.apply_decision("xu", {"kind": "loan", "purpose": "radio", "recipient_id": "player",
                                        "deadline_tick": world.state["tick"] + duration, "reserve": 4})
    assert result["ok"], result.get("error")
    return world._loan()


def test_social_loan_is_not_physical_delivery_and_missing_consent_is_free():
    world = ready()
    before = deepcopy(world.state["items"]["backup"])
    rejected_action(world, "take_backup")
    loan = lend(world)
    assert loan["status"] == "accepted"
    assert world.state["items"]["backup"] == before
    assert not world.has("backup_taken") and world.state["tick"] == 0


def test_real_borrow_connect_communicate_disconnect_return_preserves_charge():
    world = ready()
    stabilize(world)
    loan = lend(world)
    act(world, "take_backup")
    assert world.state["items"]["backup"]["holder_id"] == "player"
    act(world, "connect_radio")
    assert world.state["items"]["backup"]["connected_to"] == "radio"
    assert world.move("service")["ok"]
    assert world.state["items"]["backup"]["room_id"] == "cabin07"
    assert not any(i["id"] == "backup" for i in world.view()["inventory"])
    act(world, "radio_request")
    assert world.has("rescue_contact") and world.has("traffic_confirmed")
    act(world, "disconnect_radio")
    remaining = world.state["items"]["backup"]["charge"]
    assert remaining < 18
    act(world, "return_backup")
    item = world.state["items"]["backup"]
    assert item["holder_id"] == "xu" and item["connected_to"] == ""
    assert item["room_id"] == world.state["actors"]["xu"]["room_id"]
    assert item["charge"] == remaining
    assert world._loan()["status"] == "returned"
    assert world.state["tick"] <= loan["deadline_tick"]


def test_changed_medical_need_revokes_only_when_original_guarantee_becomes_insufficient():
    world = ready()
    for _ in range(5):
        act(world, "wait")
    loan = lend(world, duration=12)
    act(world, "take_backup")
    act(world, "connect_radio")
    assert not world.state["hazard"]["mother_worse"]
    before = deepcopy(world.state["items"]["backup"])
    act(world, "wait")
    assert world.state["hazard"]["mother_worse"]
    assert world.state["tick"] < loan["deadline_tick"]
    assert world._loan()["status"] == "reclaim_requested"
    after = world.state["items"]["backup"]
    assert after["room_id"] == before["room_id"] == "cabin07"
    assert after["connected_to"] == "radio"
    assert after["charge"] < before["charge"]  # a request neither refunds nor disconnects
    assert not world.knows("lin", "mother_worse")
    act(world, "disconnect_radio")
    remaining = world.state["items"]["backup"]["charge"]
    act(world, "return_backup")
    assert world.state["items"]["backup"]["charge"] == remaining
    assert world._loan()["status"] == "returned"


def test_early_protection_can_prevent_both_illness_and_reclaim():
    world = ready()
    stabilize(world)
    lend(world, duration=12)
    act(world, "take_backup")
    act(world, "connect_radio")
    for _ in range(5):
        act(world, "wait")
    assert not world.state["hazard"]["mother_worse"]
    assert world._loan()["status"] == "active"
    assert not any(e["kind"] == "loan_reclaim_requested" for e in world.state["events"])
