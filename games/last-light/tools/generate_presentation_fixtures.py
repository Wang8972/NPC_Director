#!/usr/bin/env python3
"""Generate reproducible QA inputs from real, offline WorldEngine operations.

No renderer, model provider or network client is imported. These are rule
fixtures for Unity capture, not evidence that a Unity capture has run.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "backend"), str(ROOT / "backend/tests"), str(ROOT / "tools")]

from render_mock import fixture_views
from test_engine_routes import act, control, ready, stabilize, step
from test_engine_power import lend


def write_json(path, data):
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


class Capture:
    def __init__(self, directory):
        self.directory = directory
        self.rows = []

    def batch(self, name, world, steps=None, *, plan_id=None, operation="complete", observe=None):
        if observe:
            moved = world.move(observe)
            assert moved["ok"], (name, moved.get("error"))
        if plan_id is None:
            proposal = world.propose(steps, "表现QA · " + name)
            assert proposal["ok"], (name, proposal.get("error"))
            plan_id = proposal["plan_id"]
        before = deepcopy(world.view())
        begun = world.begin(plan_id)
        assert begun["ok"], (name, begun.get("error"))
        execution = deepcopy(begun["view"]["execution"])
        result = world.cancel(plan_id) if operation == "cancel" else world.complete(execution["id"])
        assert result["ok"], (name, result.get("error"))
        after = deepcopy(world.view())
        plan = next(p for p in after["plans"] if p["id"] == plan_id)
        statuses = [{"id": s["id"], "action_id": s["action_id"], "status": s["status"], "remaining": s["remaining"]} for s in plan["steps"]]
        receipt = {"ok": result["ok"], "error": result.get("error", ""), "operation": operation,
                   "execution_id": execution["id"], "plan_id": plan_id, "plan_status": plan["status"],
                   "elapsed_ticks": after["tick"] - before["tick"], "steps": statuses}
        payload = {"schema_version": 1, "id": name, "source": "authoritative_rehearsal_fixture",
                   "operation": operation, "before": before, "execution": execution, "after": after,
                   "receipt": receipt, "provenance": {"engine": "last_light.engine.WorldEngine",
                   "setup": "test_engine_routes.ready and public rule helpers", "model_calls": 0,
                   "physical_state_injected": False, "observer_move_is_free": True}}
        path = self.directory / (name + ".sequence.json")
        write_json(path, payload)
        self.rows.append({"id": name, "file": path.name, "kind": "sequence", "source": payload["source"],
                          "operation": operation, "action_ids": [s["action_id"] for s in execution["steps"]],
                          "plan_status": plan["status"], "before_tick": before["tick"], "after_tick": after["tick"],
                          "sha256": hashlib.sha256(path.read_bytes()).hexdigest()})
        return plan_id, payload

    def action(self, name, world, action_id, actor="player", helpers=(), observe=None):
        return self.batch(name, world, [step(action_id, actor, helpers)], observe=observe)


def capture_power(capture):
    world = ready()
    stabilize(world)
    lend(world)
    capture.action("10-take-backup", world, "take_backup", observe="cabin07")
    capture.action("11-connect-radio", world, "connect_radio", observe="cabin07")
    capture.action("12-radio-request", world, "radio_request", observe="cabin07")
    capture.action("13-disconnect-radio", world, "disconnect_radio", observe="cabin07")
    capture.action("14-return-backup", world, "return_backup", observe="cabin07")
    capture.action("15-connect-medical", world, "connect_medical", "xu", observe="cabin07")
    capture.action("16-disconnect-medical", world, "disconnect_medical", "xu", observe="cabin07")


def capture_engineering(capture):
    world = ready()
    chain = [
        ("20-isolate-aux", "isolate_aux"), ("21-collect-tools", "collect_tools"),
        ("22-collect-spares", "collect_spares"), ("23-inspect-joint", "inspect_joint"),
        ("24-verify-isolation", "verify_isolation"), ("25-repair-joint", "repair_joint"),
        ("26-retest-repair", "retest_repair"), ("27-restore-aux", "restore_aux"),
    ]
    for name, action_id in chain:
        capture.action(name, world, action_id, "chen", observe="service")


def capture_rescue(capture):
    world = ready()
    act(world, "isolate_aux", "chen")
    act(world, "clear_aisle")
    act(world, "close_vent", "xu")
    capture.action("30-move-mother", world, "move_mother", helpers=["xu"], observe="cabin06")
    act(world, "call_child", "zhou")
    capture.action("31-clear-trolley", world, "clear_trolley", helpers=["zhou"], observe="cabin06")
    capture.action("32-free-internal-door", world, "free_internal_door", observe="cabin06")
    capture.action("33-check-child", world, "check_child", "zhou", helpers=["player"], observe="cabin06")
    capture.action("34-reunite-child", world, "reunite_child", helpers=["zhou"], observe="cabin05")
    act(world, "assign_child_care", "zhou")
    control(world)
    act(world, "collect_lamp", "lin")
    act(world, "scout_walkway", "lin")
    act(world, "open_outer_door", "lin")
    act(world, "light_walkway", "lin")
    capture.action("35-collect-stretcher", world, "collect_stretcher", observe="service")
    capture.action("36-prepare-stretcher", world, "prepare_stretcher", observe="service")
    capture.action("37-escort-mother", world, "escort_mother", helpers=["xu"], observe="cabin07")


def capture_interruptions(capture):
    world = ready()
    plan_id, partial = capture.batch("40-parallel-partial", world, [
        step("collect_tools", "chen", step_id="tools"),
        step("restore_phone", step_id="phone"),
    ], observe="service")
    statuses = {s["id"]: s for s in partial["receipt"]["steps"]}
    assert statuses["tools"]["status"] == "completed"
    assert statuses["phone"]["remaining"] == 1 and not world.has("phone_restored")
    _, cancelled = capture.batch("41-cancel-after-partial", world, plan_id=plan_id, operation="cancel")
    assert cancelled["receipt"]["elapsed_ticks"] == 0
    assert world.state["items"]["tools"]["holder_id"] == "chen"
    assert not world.has("phone_restored")
    world = ready()
    _, cancelled = capture.batch("42-cancel-before-pickup", world, [step("collect_lamp")],
                                  operation="cancel", observe="service")
    assert cancelled["receipt"]["elapsed_ticks"] == 0
    assert world.state["items"]["lamp"]["holder_id"] == ""
    world = ready()
    for _ in range(50):
        if world.state["hazard"].get("unpowered_ticks", 0) >= 6 or world.state["ending"]:
            break
        act(world, "wait")
    assert not world.state["ending"], "Unexpected failure before the recorded failure boundary"
    assert world.state["hazard"].get("unpowered_ticks", 0) == 6
    _, failed = capture.action("43-crisis-interrupts-phone", world, "restore_phone", "chen", observe="service")
    assert failed["after"]["ending"] == "failed"
    assert failed["receipt"]["plan_status"] == "failed"
    assert not world.has("phone_restored")


def generate(output):
    output = Path(output).expanduser().resolve()
    output.mkdir(parents=True, exist_ok=True)
    # Preserve the existing generator and use its real world views unchanged.
    room_files = fixture_views(output)
    capture = Capture(output)
    capture_power(capture)
    capture_engineering(capture)
    capture_rescue(capture)
    capture_interruptions(capture)
    rows = [{"id": p.stem, "file": p.name, "kind": "view", "source": "render_mock.fixture_views",
             "sha256": hashlib.sha256(p.read_bytes()).hexdigest()} for p in room_files]
    for name in ("handoff", "mother-transfer", "child-reunion"):
        path = output / (name + ".sequence.json")
        rows.append({"id": name, "file": path.name, "kind": "sequence", "source": "render_mock.fixture_views",
                     "operation": "complete", "sha256": hashlib.sha256(path.read_bytes()).hexdigest()})
    rows.extend(capture.rows)
    manifest = {"schema_version": 1, "generator": "tools/generate_presentation_fixtures.py",
                "source": "authoritative_rehearsal_fixture", "model_calls": 0,
                "physical_state_injected": False, "unity_capture_performed": False,
                "views": len(room_files), "sequences": sum(r["kind"] == "sequence" for r in rows),
                "files": rows}
    write_json(output / "manifest.json", manifest)
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "artifacts/presentation/fixtures")
    args = parser.parse_args()
    manifest = generate(args.output)
    print(json.dumps({"output": str(args.output.resolve()), "views": manifest["views"],
                      "sequences": manifest["sequences"], "model_calls": 0}, ensure_ascii=False))


if __name__ == "__main__":
    main()
