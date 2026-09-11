"""Save schema and validation; internal maps never cross the Unity view boundary."""
from __future__ import annotations

from copy import deepcopy
import re
from uuid import uuid4

from .content import ACTIONS, ACTOR_IDS, FACTS, INITIAL_ACTORS, INITIAL_KNOWLEDGE, NPC_IDS, ROOMS, SCHEMA_VERSION

SESSION_RE = re.compile(r"^[A-Za-z0-9_-]{1,80}$")


def validate_session_id(value: str) -> str:
    if not isinstance(value, str) or not SESSION_RE.fullmatch(value):
        raise ValueError("Invalid session id")
    return value


def new_state(session_id=None, mode="live"):
    if mode not in ("live", "rehearsal"):
        raise ValueError("mode must be live or rehearsal")
    sid = validate_session_id(session_id or uuid4().hex)
    actors = {aid: {"id": aid, "room_id": room, "x": x, "z": z, "pose": "idle", "emotion": "concerned" if aid != "player" else "neutral", "task_status": "", "carrying": ""}
              for aid, (room, x, z) in INITIAL_ACTORS.items()}
    items = {
        "tools": {"id": "tools", "label": "应急工具包", "owner_id": "train", "holder_id": "", "room_id": "service", "connected_to": "", "state": "stored", "charge": -1},
        "lamp": {"id": "lamp", "label": "应急手电", "owner_id": "train", "holder_id": "", "room_id": "service", "connected_to": "", "state": "stored", "charge": -1},
        "spares": {"id": "spares", "label": "密封接头备件", "owner_id": "train", "holder_id": "", "room_id": "service", "connected_to": "", "state": "stored", "charge": -1},
        "stretcher": {"id": "stretcher", "label": "折叠担架", "owner_id": "train", "holder_id": "", "room_id": "service", "connected_to": "", "state": "stored", "charge": -1},
        "backup": {"id": "backup", "label": "备用电源", "owner_id": "xu", "holder_id": "xu", "room_id": "cabin06", "connected_to": "", "state": "held", "charge": 18},
        "medical": {"id": "medical", "label": "便携呼吸支持设备", "owner_id": "mother", "holder_id": "mother", "room_id": "cabin06", "connected_to": "internal", "state": "running", "charge": 24},
    }
    knowledge = {aid: [{"id": fid, "source": "亲历" if aid != "lin" or fid != "crew_report" else "司机岗位无线电", "quality": "verified", "tick": 0}
                       for fid in INITIAL_KNOWLEDGE[aid]] for aid in ACTOR_IDS}
    return {
        "schema_version": SCHEMA_VERSION, "session_id": sid, "mode": mode, "revision": 0, "tick": 0,
        "room_id": "cabin07", "visited": ["cabin07"], "inspected": [], "flags": [],
        "actors": actors, "items": items, "knowledge": knowledge,
        "hazard": {"heat": 0, "mother_exposure": 0, "mother_worse": False, "mother_injured": False, "smoke_alerted": False, "severe_alerted": False},
        "social": {aid: {"accepted_tasks": [], "refusals": [], "disclosure": "limited", "child_delegation": None} for aid in NPC_IDS},
        "promises": [], "plans": [], "execution": None, "completed_executions": [], "cancelled_executions": [],
        "applied_decisions": [], "delivered_lines": [], "events": [], "journal": [], "dialogue": [],
        "ending": "", "ending_title": "", "ending_text": "", "epilogues": [], "next_id": 1,
        "child_caregiver": "passenger05", "sweep_revision": -1,
    }


def validate_state(raw: dict) -> dict:
    """Reject corrupt/incompatible data before it can drive effects. No pickle/eval."""
    if not isinstance(raw, dict) or raw.get("schema_version") != SCHEMA_VERSION:
        raise ValueError("Unsupported or missing save schema")
    s = deepcopy(raw)
    validate_session_id(s.get("session_id"))
    if s.get("mode") not in ("live", "rehearsal") or s.get("room_id") not in ROOMS:
        raise ValueError("Invalid mode or player room")
    for key in ("revision", "tick", "next_id"):
        if type(s.get(key)) is not int or not 0 <= s[key] <= 10000000:
            raise ValueError("Invalid numeric save field: " + key)
    for key in ("visited", "inspected", "flags", "promises", "plans", "completed_executions", "cancelled_executions", "applied_decisions", "delivered_lines", "events", "journal", "dialogue", "epilogues"):
        if not isinstance(s.get(key), list) or len(s[key]) > 100000:
            raise ValueError("Invalid save collection: " + key)
    if any(room not in ROOMS for room in s["visited"]):
        raise ValueError("Unknown visited room")
    actors = s.get("actors", {})
    if not isinstance(actors, dict) or set(actors) != set(ACTOR_IDS):
        raise ValueError("Missing/unknown actors")
    for aid, a in actors.items():
        if not isinstance(a, dict) or a.get("id") != aid or a.get("room_id") not in ROOMS:
            raise ValueError("Invalid actor state")
        for axis in ("x", "z"):
            if not isinstance(a.get(axis), (float, int)) or not -20 <= a[axis] <= 20:
                raise ValueError("Invalid actor position")
    if actors["player"]["room_id"] != s["room_id"]:
        raise ValueError("Player location mismatch")
    items = s.get("items", {})
    if not isinstance(items, dict) or set(items) != {"tools", "lamp", "spares", "stretcher", "backup", "medical"}:
        raise ValueError("Invalid inventory")
    for iid, item in items.items():
        if not isinstance(item, dict) or item.get("id") != iid or item.get("room_id") not in ROOMS:
            raise ValueError("Invalid item")
        if item.get("holder_id") not in ("", *ACTOR_IDS) or type(item.get("charge")) is not int or not -1 <= item["charge"] <= 100:
            raise ValueError("Invalid item custody/charge")
        if item.get("connected_to") not in ("", "internal", "radio", "medical", "walkway", "backup"):
            raise ValueError("Unknown item connection")
    if items["backup"]["connected_to"] == "medical" and items["medical"]["connected_to"] != "backup":
        raise ValueError("Medical connection mismatch")
    knowledge = s.get("knowledge", {})
    if not isinstance(knowledge, dict) or set(knowledge) != set(ACTOR_IDS):
        raise ValueError("Invalid knowledge store")
    for records in knowledge.values():
        if not isinstance(records, list) or len(records) != len({r.get("id") for r in records if isinstance(r, dict)}):
            raise ValueError("Duplicate/invalid knowledge records")
        if any(not isinstance(r, dict) or r.get("id") not in FACTS or r.get("quality") not in ("reported", "observed", "verified") for r in records):
            raise ValueError("Invalid knowledge fact")
    social = s.get("social", {})
    if not isinstance(social, dict) or set(social) != set(NPC_IDS):
        raise ValueError("Invalid social state")
    for value in social.values():
        if not isinstance(value, dict) or not isinstance(value.get("accepted_tasks"), list) or any(a not in ACTIONS for a in value["accepted_tasks"]):
            raise ValueError("Unknown accepted task")
    hazard = s.get("hazard", {})
    for field in ("heat", "mother_exposure"):
        if type(hazard.get(field)) is not int or not 0 <= hazard[field] <= 100000:
            raise ValueError("Invalid hazard")
    flags = set(s["flags"])
    if len(flags) != len(s["flags"]) or any(not isinstance(f, str) for f in flags):
        raise ValueError("Duplicate/invalid flags")
    chains = {"isolation_verified": "aux_isolated", "repair_done": "isolation_verified", "retest_passed": "repair_done", "aux_restored": "retest_passed", "inner_door_open": "trolley_cleared", "outer_open": "path_surveyed", "path_surveyed": "traffic_confirmed", "route_lit": "outer_open", "child_reunited": "child_checked"}
    if any(k in flags and required not in flags for k, required in chains.items()):
        raise ValueError("Impossible causal flag chain")
    if s.get("child_caregiver") not in ACTOR_IDS:
        raise ValueError("Invalid child caregiver")
    plan_ids = set()
    step_ids = set()
    for p in s["plans"]:
        if not isinstance(p, dict) or p.get("id") in plan_ids or not isinstance(p.get("steps"), list):
            raise ValueError("Invalid/duplicate plan")
        plan_ids.add(p["id"])
        local = {step.get("id") for step in p["steps"]}
        if len(local) != len(p["steps"]):
            raise ValueError("Duplicate plan steps")
        for step in p["steps"]:
            if step.get("action_id") not in ACTIONS or step.get("actor_id") not in ACTOR_IDS or any(dep not in local for dep in step.get("depends_on", [])):
                raise ValueError("Invalid plan step")
            if type(step.get("remaining")) is not int or not 0 <= step["remaining"] <= ACTIONS[step["action_id"]]["duration"]:
                raise ValueError("Invalid remaining work")
            step_ids.add((p["id"], step["id"]))
        visited, stack = set(), set()
        by_id = {step["id"]: step for step in p["steps"]}
        def walk(node):
            if node in stack:
                raise ValueError("Cyclic saved plan")
            if node in visited:
                return
            stack.add(node)
            for dep in by_id[node]["depends_on"]:
                walk(dep)
            stack.remove(node)
            visited.add(node)
        for node in local:
            walk(node)
    execution = s.get("execution")
    if execution is not None:
        if not isinstance(execution, dict) or execution.get("plan_id") not in plan_ids or type(execution.get("duration")) is not int or execution["duration"] < 1:
            raise ValueError("Invalid active execution")
        if execution.get("id") in s["completed_executions"]:
            raise ValueError("Execution already committed")
        if any((execution["plan_id"], sid) not in step_ids for sid in execution.get("step_ids", [])):
            raise ValueError("Unknown active step")
    if s.get("ending") not in ("", "stay_all", "evacuate_all", "costly", "failed"):
        raise ValueError("Unknown ending")
    return s
