"""Complete action-to-animation catalogue, independent of authoritative physics.

Preparation is safe before a commit. Result clips require a successful world
receipt; a suggested plan or elapsed animation never establishes an outcome.
Export with: python -m last_light.presentation_content > presentation.json
"""
from copy import deepcopy
import json

from .content import ACTIONS

CLIP_IDS = (
    "idle_alert", "inspect_stand", "inspect_kneel", "read_record", "reach_item",
    "lift_item", "carry_item", "offer_item", "receive_item", "connect_cable",
    "disconnect_cable", "switch_off", "switch_on", "repair_kneel", "verify_meter",
    "operate_door", "brace_cart", "push_cart", "support_person", "escort_walk",
    "lift_stretcher", "unfold_stretcher", "use_phone", "use_radio", "announce",
    "point_route", "place_item", "gather_signal", "confirm_nod", "stop_work",
    "step_back", "hold_position",
)
ITEM_IDS = ("tools", "lamp", "spares", "stretcher", "backup", "medical")
SOCKET_IDS = (
    "hand_r", "hand_l", "carry_front", "tool_rack_tools", "tool_rack_lamp",
    "tool_rack_spares", "stretcher_rack_mount", "radio_power", "medical_power",
    "aux_breaker", "aux_joint", "aux_test", "phone_interface", "door_handle",
    "cart_grip_l", "cart_grip_r", "stretcher_front", "stretcher_rear",
    "support_l", "support_r", "refuge_lamp", "document_hold", "gather_point",
)


def _entry(kind, preparation, result, failure="stop_work", resources=(), sockets=(), roles=("actor", "helpers")):
    return {"visual_kind": kind, "preparation_clip": preparation, "result_clip": result,
            "failed_clip": failure, "resource_ids": list(resources), "socket_ids": list(sockets),
            "participant_roles": list(roles)}


# Explicit entries intentionally distinguish diagnosis, isolation and retest;
# electrical repair success is never borrowed from the dialogue animation.
ACTION_PRESENTATIONS = {
    "collect_tools": _entry("pickup", "reach_item", "lift_item", resources=["tools"], sockets=["tool_rack_tools", "hand_r"]),
    "collect_lamp": _entry("pickup", "reach_item", "lift_item", resources=["lamp"], sockets=["tool_rack_lamp", "hand_r"]),
    "collect_spares": _entry("pickup", "reach_item", "lift_item", resources=["spares"], sockets=["tool_rack_spares", "hand_r"]),
    "collect_stretcher": _entry("pickup", "reach_item", "carry_item", resources=["stretcher"], sockets=["stretcher_rack_mount", "carry_front"]),
    "examine_log": _entry("inspect", "read_record", "confirm_nod", sockets=["document_hold"]),
    "inspect_joint": _entry("inspect", "inspect_kneel", "verify_meter", resources=["tools"], sockets=["hand_r", "aux_joint"]),
    "isolate_aux": _entry("isolate", "inspect_stand", "switch_off", sockets=["hand_r", "aux_breaker"]),
    "verify_isolation": _entry("retest", "inspect_kneel", "verify_meter", resources=["tools"], sockets=["hand_r", "aux_test"]),
    "repair_joint": _entry("repair", "inspect_kneel", "repair_kneel", resources=["tools", "spares"], sockets=["hand_r", "aux_joint"]),
    "retest_repair": _entry("retest", "inspect_stand", "verify_meter", resources=["tools"], sockets=["hand_r", "aux_test"]),
    "restore_aux": _entry("power_restore", "inspect_stand", "switch_on", sockets=["hand_r", "aux_breaker"]),
    "manual_cutoff": _entry("isolate", "inspect_stand", "switch_off", sockets=["hand_r", "aux_breaker"]),
    "restore_phone": _entry("repair", "inspect_stand", "connect_cable", sockets=["hand_r", "phone_interface"]),
    "call_control": _entry("communication", "use_phone", "confirm_nod", sockets=["hand_r", "phone_interface"]),
    "connect_radio": _entry("connect", "reach_item", "connect_cable", resources=["backup"], sockets=["hand_r", "radio_power"]),
    "radio_request": _entry("communication", "use_radio", "confirm_nod", resources=["backup"], sockets=["radio_power"]),
    "disconnect_radio": _entry("disconnect", "reach_item", "disconnect_cable", resources=["backup"], sockets=["radio_power", "hand_r"]),
    "take_backup": _entry("handoff", "offer_item", "receive_item", resources=["backup"], sockets=["hand_r", "hand_l"], roles=["actor", "item_holder"]),
    "return_backup": _entry("handoff", "carry_item", "offer_item", resources=["backup"], sockets=["hand_r", "hand_l"], roles=["actor", "recipient"]),
    "connect_medical": _entry("connect", "reach_item", "connect_cable", resources=["backup", "medical"], sockets=["hand_r", "medical_power"], roles=["actor", "helpers", "patient"]),
    "disconnect_medical": _entry("disconnect", "inspect_stand", "disconnect_cable", resources=["backup", "medical"], sockets=["medical_power", "hand_r"], roles=["actor", "helpers", "patient"]),
    "close_vent": _entry("isolate", "reach_item", "switch_off", sockets=["hand_r"]),
    "move_mother": _entry("escort", "support_person", "escort_walk", "hold_position", resources=["medical", "backup"], sockets=["support_l", "support_r"], roles=["actor", "helpers", "patient"]),
    "assess_mother": _entry("care", "inspect_kneel", "confirm_nod", resources=["medical"], roles=["actor", "patient"]),
    "prepare_stretcher": _entry("stretcher", "reach_item", "unfold_stretcher", resources=["stretcher"], sockets=["stretcher_front", "stretcher_rear"]),
    "clear_aisle": _entry("clear", "reach_item", "place_item", sockets=["carry_front"]),
    "announce_facts": _entry("communication", "use_radio", "announce", sockets=["hand_r"]),
    "count_passengers": _entry("inspect", "read_record", "confirm_nod", sockets=["document_hold"], roles=["actor", "helpers", "passengers"]),
    "clear_trolley": _entry("cart", "brace_cart", "push_cart", "hold_position", sockets=["cart_grip_l", "cart_grip_r"]),
    "free_internal_door": _entry("door", "reach_item", "operate_door", "step_back", sockets=["hand_r", "door_handle"]),
    "call_child": _entry("communication", "inspect_stand", "announce", sockets=["door_handle"]),
    "open_external05": _entry("door", "inspect_stand", "operate_door", "step_back", sockets=["hand_r", "door_handle"]),
    "check_child": _entry("care", "inspect_kneel", "confirm_nod", roles=["actor", "helpers", "child"]),
    "reunite_child": _entry("escort", "support_person", "escort_walk", "hold_position", sockets=["hand_l", "support_r"], roles=["actor", "helpers", "child"]),
    "assign_child_care": _entry("care", "inspect_stand", "confirm_nod", roles=["actor", "child", "recipient"]),
    "scout_walkway": _entry("inspect", "inspect_stand", "point_route", resources=["lamp"], sockets=["hand_r", "door_handle"]),
    "open_outer_door": _entry("door", "inspect_stand", "operate_door", "step_back", sockets=["hand_r", "door_handle"]),
    # The authoritative action keeps the unique lamp held; do not invent a second placed lamp.
    "light_walkway": _entry("inspect", "carry_item", "point_route", resources=["lamp"], sockets=["hand_r", "refuge_lamp"]),
    "escort_mother": _entry("stretcher", "lift_stretcher", "escort_walk", "hold_position", resources=["stretcher", "medical", "backup"], sockets=["stretcher_front", "stretcher_rear"], roles=["actor", "helpers", "patient"]),
    "escort_child": _entry("escort", "support_person", "escort_walk", "hold_position", sockets=["hand_l", "support_r"], roles=["actor", "helpers", "child"]),
    "escort_passengers": _entry("gather", "gather_signal", "escort_walk", "hold_position", sockets=["gather_point"], roles=["actor", "helpers", "passengers"]),
    "final_sweep": _entry("inspect", "read_record", "confirm_nod", sockets=["document_hold"]),
    "shelter_group": _entry("gather", "gather_signal", "escort_walk", "hold_position", sockets=["gather_point"], roles=["actor", "helpers", "passengers"]),
    "await_rescue": _entry("communication", "use_radio", "confirm_nod", "hold_position", sockets=["gather_point"]),
    "finish_evacuation": _entry("gather", "gather_signal", "confirm_nod", "hold_position", sockets=["gather_point"]),
    "wait": _entry("wait", "idle_alert", "idle_alert", "hold_position"),
    "give_tools": _entry("handoff", "carry_item", "offer_item", resources=["tools"], sockets=["hand_r", "hand_l"], roles=["actor", "helpers", "recipient"]),
    "give_spares": _entry("handoff", "carry_item", "offer_item", resources=["spares"], sockets=["hand_r", "hand_l"], roles=["actor", "helpers", "recipient"]),
    "give_lamp": _entry("handoff", "carry_item", "offer_item", resources=["lamp"], sockets=["hand_r", "hand_l"], roles=["actor", "helpers", "recipient"]),
    "join_briefing": _entry("gather", "point_route", "escort_walk", "hold_position", sockets=["gather_point"]),
    "move_to_refuge": _entry("gather", "point_route", "escort_walk", "hold_position", sockets=["gather_point"]),
}

for _action_id, _presentation in ACTION_PRESENTATIONS.items():
    _presentation["action_id"] = _action_id


def presentation_for(action_id):
    if action_id not in ACTION_PRESENTATIONS:
        raise ValueError("No registered presentation for action: " + str(action_id))
    return deepcopy(ACTION_PRESENTATIONS[action_id])


def export_catalog():
    """JSON-safe arrays; fails loudly if a new action lacks an authored mapping."""
    if set(ACTION_PRESENTATIONS) != set(ACTIONS):
        raise ValueError("Action presentation catalogue does not exactly cover ACTIONS")
    for item in ACTION_PRESENTATIONS.values():
        if any(item[key] not in CLIP_IDS for key in ("preparation_clip", "result_clip", "failed_clip")):
            raise ValueError("Unknown clip in presentation catalogue")
        if set(item["resource_ids"]) - set(ITEM_IDS) or set(item["socket_ids"]) - set(SOCKET_IDS):
            raise ValueError("Unknown resource/socket in presentation catalogue")
    return {"schema_version": 1, "clips": list(CLIP_IDS), "sockets": list(SOCKET_IDS),
            "actions": [presentation_for(action_id) for action_id in ACTIONS]}


if __name__ == "__main__":
    print(json.dumps(export_catalog(), ensure_ascii=False, indent=2))
