"""Exercise the offline fixture generator, not hand-constructed success JSON."""
import hashlib
import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="module")
def fixture_bundle(tmp_path_factory):
    spec = importlib.util.spec_from_file_location("presentation_fixture_generator", ROOT / "tools/generate_presentation_fixtures.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    output = tmp_path_factory.mktemp("presentation-fixtures")
    manifest = module.generate(output)
    return output, manifest


def load(bundle, name):
    return json.loads((bundle[0] / (name + ".sequence.json")).read_text(encoding="utf-8"))


def item(view, item_id):
    return next(i for i in view["inventory"] if i["id"] == item_id)


def test_generation_covers_five_rooms_and_auditable_rule_receipts(fixture_bundle):
    output, manifest = fixture_bundle
    assert manifest["views"] == 7 and manifest["sequences"] == 30
    assert manifest["model_calls"] == 0 and not manifest["physical_state_injected"]
    assert not manifest["unity_capture_performed"]
    rooms = set()
    for row in manifest["files"]:
        path = output / row["file"]
        assert hashlib.sha256(path.read_bytes()).hexdigest() == row["sha256"]
        data = json.loads(path.read_text(encoding="utf-8"))
        if row["kind"] == "view":
            rooms.add(data["room_id"])
            continue
        assert data["before"]["mode"] == data["after"]["mode"] == "rehearsal"
        if row["source"] == "authoritative_rehearsal_fixture":
            receipt = data["receipt"]
            assert receipt["execution_id"] == data["execution"]["id"]
            assert receipt["elapsed_ticks"] == data["after"]["tick"] - data["before"]["tick"]
            plan = next(p for p in data["after"]["plans"] if p["id"] == receipt["plan_id"])
            assert plan["status"] == receipt["plan_status"]
    assert rooms == {"cabin05", "cabin06", "cabin07", "service", "tunnel"}


def test_power_sequences_use_true_custody_connections_and_consumption(fixture_bundle):
    taken = load(fixture_bundle, "10-take-backup")
    assert item(taken["before"], "backup")["holder_id"] == "xu"
    assert item(taken["after"], "backup")["holder_id"] == "player"
    connected = load(fixture_bundle, "11-connect-radio")
    assert item(connected["after"], "backup")["connected_to"] == "radio"
    assert item(connected["after"], "backup")["charge"] < item(connected["before"], "backup")["charge"]
    returned = load(fixture_bundle, "14-return-backup")
    assert item(returned["after"], "backup")["holder_id"] == "xu"
    assert item(returned["after"], "backup")["charge"] == item(returned["before"], "backup")["charge"]
    medical = load(fixture_bundle, "15-connect-medical")
    assert item(medical["after"], "backup")["connected_to"] == "medical"
    assert item(medical["after"], "medical")["connected_to"] == "backup"


def test_repair_and_person_transfers_have_actual_different_after_states(fixture_bundle):
    for name, expected in (("25-repair-joint", "repaired"), ("26-retest-repair", "tested"), ("27-restore-aux", "powered")):
        after = load(fixture_bundle, name)["after"]
        assert next(o for o in after["objects"] if o["id"] == "cable_joint")["state"] == expected
    for name, actor, source, destination in (("30-move-mother", "mother", "cabin06", "cabin07"),
                                            ("34-reunite-child", "xiaoman", "cabin05", "cabin07"),
                                            ("37-escort-mother", "mother", "cabin07", "tunnel")):
        data = load(fixture_bundle, name)
        assert next(a for a in data["before"]["actors"] if a["id"] == actor)["room_id"] == source
        assert next(a for a in data["after"]["actors"] if a["id"] == actor)["room_id"] == destination


def test_partial_cancel_and_crisis_do_not_pretend_that_unfinished_work_succeeded(fixture_bundle):
    partial = load(fixture_bundle, "40-parallel-partial")
    steps = {s["id"]: s for s in partial["receipt"]["steps"]}
    assert steps["tools"]["status"] == "completed" and steps["phone"]["remaining"] == 1
    cancelled = load(fixture_bundle, "41-cancel-after-partial")
    assert cancelled["operation"] == "cancel" and cancelled["receipt"]["elapsed_ticks"] == 0
    assert item(cancelled["after"], "tools")["holder_id"] == "chen"
    never_taken = load(fixture_bundle, "42-cancel-before-pickup")
    assert item(never_taken["after"], "lamp")["holder_id"] == ""
    failed = load(fixture_bundle, "43-crisis-interrupts-phone")
    assert failed["after"]["ending"] == "failed" and failed["receipt"]["plan_status"] == "failed"
    assert failed["receipt"]["steps"][0]["status"] == "cancelled"
