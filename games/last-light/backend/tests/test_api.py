"""The exact HTTP boundary used by Unity, with no live model calls."""
import asyncio
import time
from functools import partial

import pytest
from fastapi.testclient import TestClient

from last_light.api import create_app
from last_light.director import DirectorBridge
from test_director_bridge import RecordedNodes


@pytest.fixture
def client(tmp_path):
    factory = partial(DirectorBridge, typed_runner=RecordedNodes(), model="recorded-test")
    app = create_app(tmp_path, director_factory=factory)
    with TestClient(app) as connection:
        yield connection


def make_session(client, mode="rehearsal"):
    response = client.post("/sessions", json={"mode": mode})
    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] and payload["view"]["mode"] == mode
    return payload["session_id"], payload["view"]


def test_health_projection_and_no_hidden_people(client):
    assert client.get("/health").json()["ok"]
    sid, view = make_session(client)
    assert {a["id"] for a in view["actors"]} == {"player", "lin", "zhou", "passenger07"}
    assert "temporary_fix" not in str(view)
    assert next(r for r in view["rooms"] if r["id"] == "cabin05")["visited"] is False
    assert client.get("/sessions/" + sid).json()["view"] == view


def test_unity_shared_step_dto_is_accepted_but_duration_cannot_cheat(client):
    sid, view = make_session(client)
    response = client.post(f"/sessions/{sid}/plan", json={"expected_revision": view["revision"],
        "title": "整理过道", "steps": [{"id": "s1", "action_id": "clear_aisle", "actor_id": "player",
        "target_id": "aisle07", "helpers": [], "depends_on": [], "duration": 0,
        "status": "completed", "reason": "client cannot grant completion"}]})
    data = response.json()
    assert data["ok"], data
    plan = data["view"]["plans"][-1]
    assert plan["steps"][0]["status"] != "completed"
    assert plan["steps"][0]["duration"] == 1
    begin = client.post(f"/sessions/{sid}/begin", json={"expected_revision": data["view"]["revision"], "plan_id": plan["id"]}).json()
    assert begin["ok"] and begin["view"]["tick"] == 0
    execution = begin["view"]["execution"]["id"]
    completed = client.post(f"/sessions/{sid}/complete", json={"expected_revision": begin["view"]["revision"], "execution_id": execution}).json()
    assert completed["ok"] and completed["view"]["tick"] == 1
    duplicate = client.post(f"/sessions/{sid}/complete", json={"expected_revision": begin["view"]["revision"], "execution_id": execution}).json()
    assert duplicate["ok"] and duplicate["view"]["tick"] == 1


@pytest.mark.parametrize("legacy_plan_id", [None, ""])
def test_cancel_recovers_active_plan_when_legacy_unity_omits_plan_id(client, legacy_plan_id):
    sid, view = make_session(client)
    proposed = client.post(f"/sessions/{sid}/plan", json={"expected_revision": view["revision"],
        "title": "整理过道", "steps": [{"id": "s1", "action_id": "clear_aisle",
        "actor_id": "player", "target_id": "aisle07"}]}).json()
    plan = proposed["view"]["plans"][-1]
    begun = client.post(f"/sessions/{sid}/begin", json={"expected_revision": proposed["view"]["revision"],
        "plan_id": plan["id"]}).json()
    response = client.post(f"/sessions/{sid}/cancel", json={"expected_revision": begun["view"]["revision"],
        "plan_id": legacy_plan_id})
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["ok"]
    assert result["view"]["execution"] is None
    assert next(p for p in result["view"]["plans"] if p["id"] == plan["id"])["status"] == "cancelled"


def test_cancel_recovers_only_waiting_plan_when_legacy_unity_omits_plan_id(client):
    sid, view = make_session(client)
    proposed = client.post(f"/sessions/{sid}/plan", json={"expected_revision": view["revision"],
        "title": "尚未开始", "steps": [{"id": "s1", "action_id": "clear_aisle",
        "actor_id": "player", "target_id": "aisle07"}]}).json()
    plan = proposed["view"]["plans"][-1]
    response = client.post(f"/sessions/{sid}/cancel", json={"expected_revision": proposed["view"]["revision"]})
    assert response.status_code == 200, response.text
    assert next(p for p in response.json()["view"]["plans"] if p["id"] == plan["id"])["status"] == "cancelled"


def test_stale_commands_rejected_without_cost(client):
    sid, before = make_session(client)
    moved = client.post(f"/sessions/{sid}/move", json={"expected_revision": before["revision"], "room_id": "cabin06"}).json()
    assert moved["ok"]
    stale = client.post(f"/sessions/{sid}/inspect", json={"expected_revision": before["revision"], "target_id": "oxygen"})
    assert stale.status_code == 409
    assert client.get(f"/sessions/{sid}").json()["view"]["tick"] == 0


def test_pair_checkpoint_restores_world_and_invalidates_old_revision(client):
    sid, initial = make_session(client)
    assert client.post(f"/sessions/{sid}/save", json={}).json()["ok"]
    later = client.post(f"/sessions/{sid}/move", json={"expected_revision": initial["revision"], "room_id": "cabin06"}).json()["view"]
    restored = client.post(f"/sessions/{sid}/restore", json={}).json()
    assert restored["ok"], restored
    assert restored["view"]["room_id"] == "cabin07"
    assert restored["view"]["revision"] > later["revision"]


def test_cannot_post_arbitrary_world_state(client):
    sid, before = make_session(client)
    result = client.post(f"/sessions/{sid}/inspect", json={"expected_revision": before["revision"],
        "target_id": "radio", "world_flags": {"traffic_confirmed": True}})
    assert result.status_code == 422
    assert client.get(f"/sessions/{sid}").json()["view"] == before


def test_director_public_roster_does_not_disclose_father_before_he_speaks(client):
    sid, _ = make_session(client, "live")
    bridge = client.app.state.bridge
    registry = bridge._service(sid).context_builder.character_registry
    roster = registry.roster("cabin07", current_npc_id="lin")
    father = next(p for p in roster if p["npc_id"] == "zhou")
    assert father["role"] == "乘客"
    assert "小满" not in str(father) and "孩子" not in str(father)


def test_ended_game_cannot_create_further_model_conversation(client):
    from test_engine_routes import ready, prepare_stay, act
    world = ready()
    prepare_stay(world)
    act(world, "await_rescue")
    sid = world.state["session_id"]
    client.app.state.engines[sid] = world
    client.app.state.repository.save(world)
    result = client.post(f"/sessions/{sid}/talk", json={"expected_revision": world.state["revision"],
        "npc_id": "lin", "text": "继续创建新救援", "audience": ["lin"]})
    assert result.status_code == 409 and not client.app.state.bridge.has_active_job(sid)


def test_actual_v2_job_survives_get_and_requires_real_delivery(client):
    sid, view = make_session(client, "live")
    data = client.post(f"/sessions/{sid}/talk", json={"expected_revision": view["revision"],
        "npc_id": "lin", "text": "你愿意负责清点吗？", "topic_id": "", "audience": ["lin"]}).json()
    assert data["ok"] and data["job"]
    job_id = data["job"]["id"]
    for _ in range(300):
        current = client.get(f"/sessions/{sid}/talk/{job_id}").json()
        if current["job"]["status"] != "running":
            break
        time.sleep(.01)
    assert current["job"]["status"] == "waiting_delivery", current
    assert client.get(f"/sessions/{sid}").json()["job"]["id"] == job_id
    blocked = client.post(f"/sessions/{sid}/move", json={"expected_revision": current["view"]["revision"], "room_id": "cabin06"})
    assert blocked.status_code == 409
    line_id = current["job"]["lines"][0]["id"]
    acknowledged = client.post(f"/sessions/{sid}/talk/{job_id}/ack", json={"line_id": line_id}).json()
    assert acknowledged["ok"]
    assert acknowledged["view"]["tick"] == 0
