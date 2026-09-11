"""Presentation/receipt tests use recorded nodes, never a live model transport."""
import asyncio
import time
from copy import deepcopy
from functools import partial

import pytest
from fastapi.testclient import TestClient

from last_light.api import create_app
from last_light.director import DirectorBridge
from last_light.performance import visible_performance
from test_director_bridge import RecordedNodes, make_bridge, poll
from test_api import make_session


class RichNodes(RecordedNodes):
    async def __call__(self, agent, raw, output_type):
        result = await super().__call__(agent, raw, output_type)
        value = result.output
        if output_type.__name__ == "DialogueDraft":
            from npc_director.contracts.enums import CoarseEmotion, PrimaryEmotion, VoiceStyle
            value.coarse_emotion = CoarseEmotion.FEAR
            value.primary_emotion = PrimaryEmotion.WARY
            value.secondary_emotion = PrimaryEmotion.HOPEFUL
            value.intensity, value.valence, value.arousal = .83, -.4, .72
            value.dialogue.voice_style = VoiceStyle.ANXIOUS
        elif output_type.__name__ == "PerformanceOutput":
            from npc_director.contracts.performance import FaceCue, BodyCue, Gaze
            value.performance.face_cues = [
                FaceCue(preset="concerned", intensity=.81, start_ms=320, duration_ms=1300),
                FaceCue(preset="relieved_smile", intensity=.34, start_ms=1900, duration_ms=700),
            ]
            value.performance.body_cues = [
                BodyCue(action="small_nod", layer="upper_body", priority=20, start_ms=240),
                BodyCue(action="open_palms", layer="additive", priority=75, start_ms=1600),
            ]
            value.performance.gaze = Gaze(target="ground", mode="avoidant")
            from npc_director.contracts.enums import InterruptPolicy
            value.performance.interrupt_policy = InterruptPolicy.ALLOW_ANY
        return result


def event(line, kind, *, event_id=None, skipped=False):
    return {"line_id": line, "event_id": event_id or line + ":" + kind,
            "event_type": kind, "visuals_skipped": skipped}


async def ready(bridge, world, audience=None):
    job = await bridge.start(world.sid, "lin", "请说明你愿意承担的工作", audience or ["lin"])
    pending = await poll(bridge, world.sid, job["id"])
    assert pending["status"] == "waiting_delivery", pending
    return job["id"], pending["lines"][0]["id"]


@pytest.mark.asyncio
async def test_full_public_performance_survives_delivery_and_history(tmp_path):
    bridge, world, _ = make_bridge(tmp_path, RichNodes())
    job_id, line_id = await ready(bridge, world)
    line = bridge.get_job(world.sid, job_id)["lines"][0]
    p = line["performance"]
    assert p["emotion"]["primary"] == "wary" and p["emotion"]["secondary"] == "hopeful"
    assert p["emotion"]["intensity"] == .83 and p["emotion"]["valence"] == -.4
    assert p["dialogue"]["voice_style"] == "anxious"
    assert [c["start_ms"] for c in p["face_cues"]] == [320, 1900]
    assert p["face_cues"][1]["duration_ms"] == 700
    assert p["body_cues"][1]["layer"] == "additive" and p["body_cues"][1]["priority"] == 75
    assert p["gaze"] == {"target": "ground", "mode": "avoidant"}
    assert p["interrupt_policy"] == "allow_any"
    assert line["emotion"] == "concerned" and line["body_action"] == "small_nod"
    assert "runtime_meta" not in p and "evidence" not in p and "trace_id" not in str(p)
    unsafe = {**p, "runtime_meta": {"trace_id": "private-trace"}, "evidence": {"lore_refs": ["private-fact"]}}
    assert visible_performance(unsafe) == p
    for kind in ("ack", "started", "completed"):
        await bridge.performance_event(world.sid, job_id, event(line_id, kind))
    await poll(bridge, world.sid, job_id)
    history = bridge.present_view(world.sid, world.view())["dialogue"][-1]
    assert history["performance"] == p and history["delivered"]
    assert history["playback_status"] == history["delivery_status"] == "completed"
    assert not history["legacy"]
    assert bridge.ledger.report()["calls"] == []
    await bridge.close()


@pytest.mark.asyncio
async def test_receipts_do_not_commit_or_resume_parent_episode(tmp_path):
    bridge, world, nodes = make_bridge(tmp_path, RecordedNodes(cooperate=True))
    job_id, line_id = await ready(bridge, world, ["lin", "chen"])
    revision, calls = world.revision, len(nodes.calls)
    for kind in ("ack", "started"):
        result = await bridge.performance_event(world.sid, job_id, event(line_id, kind))
        assert result["status"] == "waiting_delivery"
        assert result["lines"][0]["playback_status"] == kind
        assert result["lines"][0]["delivery_status"] == "pending"
        assert not result["lines"][0]["delivered"]
    assert world.revision == revision and world.tick == 0 and world.applied == [] and world.lines == []
    assert len(nodes.calls) == calls and [v["npc_id"] for v in nodes.inputs] == ["lin"]
    delivery = bridge._load_job(world.sid, job_id)["_deliveries"][line_id]
    turn = await bridge._service(world.sid).turn_store.aget(delivery["turn_id"])
    assert turn.status.value == "emitted" and delivery["state"] == "pending"
    await bridge.performance_event(world.sid, job_id, event(line_id, "completed", skipped=True))
    next_beat = await poll(bridge, world.sid, job_id)
    assert next_beat["lines"][-1]["npc_id"] == "chen"
    assert next_beat["lines"][0]["visuals_skipped"]
    assert world.tick == 0 and [line["npc_id"] for line in world.lines] == ["lin"]
    await bridge.cancel(world.sid, job_id)


@pytest.mark.asyncio
@pytest.mark.parametrize("terminal", ["interrupted", "error"])
async def test_terminal_playback_rejects_late_completion(tmp_path, terminal):
    bridge, world, _ = make_bridge(tmp_path)
    job_id, line_id = await ready(bridge, world)
    await bridge.performance_event(world.sid, job_id, event(line_id, "ack"))
    await bridge.performance_event(world.sid, job_id, event(line_id, "started"))
    stopped = await bridge.performance_event(world.sid, job_id, event(line_id, terminal))
    assert stopped["status"] == ("failed" if terminal == "error" else "cancelled")
    assert stopped["lines"][0]["playback_status"] == terminal
    assert not stopped["lines"][0]["delivered"]
    with pytest.raises(ValueError, match="terminal"):
        await bridge.performance_event(world.sid, job_id, event(line_id, "completed"))
    assert not world.lines and not world.applied and world.tick == 0


@pytest.mark.asyncio
async def test_event_retries_are_idempotent_and_id_conflicts_fail(tmp_path):
    bridge, world, _ = make_bridge(tmp_path)
    job_id, line_id = await ready(bridge, world)
    with pytest.raises(ValueError, match="acknowledged"):
        await bridge.performance_event(world.sid, job_id, event(line_id, "started"))
    for kind in ("ack", "started", "completed"):
        request = event(line_id, kind)
        await bridge.performance_event(world.sid, job_id, request)
        await bridge.performance_event(world.sid, job_id, request)
    await poll(bridge, world.sid, job_id)
    revision = world.revision
    await bridge.performance_event(world.sid, job_id, event(line_id, "completed", event_id="new_retry"))
    assert world.revision == revision and len(world.lines) == 1
    with pytest.raises(ValueError, match="reused"):
        await bridge.performance_event(world.sid, job_id, event(line_id, "ack", event_id=line_id + ":started"))
    await bridge.close()


@pytest.mark.asyncio
async def test_restart_after_started_does_not_imply_delivery(tmp_path):
    original, world, _ = make_bridge(tmp_path, RichNodes())
    job_id, line_id = await ready(original, world)
    for kind in ("ack", "started"):
        await original.performance_event(world.sid, job_id, event(line_id, kind))
    saved = original.get_job(world.sid, job_id)["lines"][0]["performance"]
    fresh_nodes = RichNodes()
    restarted = DirectorBridge(tmp_path, lambda sid: world, lambda sid: None,
                               typed_runner=fresh_nodes, model="recorded-test")
    recovered = restarted.get_job(world.sid, job_id)
    assert recovered["status"] == "waiting_delivery"
    assert recovered["lines"][0]["performance"] == saved
    assert recovered["lines"][0]["playback_status"] == "started"
    assert recovered["lines"][0]["delivery_status"] == "pending"
    assert fresh_nodes.calls == [] and world.lines == []
    await restarted.performance_event(world.sid, job_id, event(line_id, "ack"))
    assert restarted.get_job(world.sid, job_id)["lines"][0]["playback_status"] == "started"
    await restarted.performance_event(world.sid, job_id, event(line_id, "completed"))
    await poll(restarted, world.sid, job_id)
    assert len(world.lines) == 1
    await restarted.close()
    # original represents a crashed process: do not run its stale shutdown handler.


@pytest.fixture
def performance_client(tmp_path):
    factory = partial(DirectorBridge, typed_runner=RichNodes(), model="recorded-test")
    app = create_app(tmp_path, director_factory=factory)
    with TestClient(app) as connection:
        yield connection


def rehearsal_job(client, sid, revision):
    response = client.post(f"/sessions/{sid}/talk", json={"expected_revision": revision,
        "npc_id": "lin", "text": "", "topic_id": "lin_report", "audience": ["lin"]})
    assert response.status_code == 200, response.text
    job = response.json()["job"]
    return job["id"], job["lines"][0]["id"]


def test_rehearsal_uses_same_real_delivery_boundary_without_models(performance_client):
    client = performance_client
    sid, initial = make_session(client)
    world = client.app.state.engines[sid]
    before = deepcopy(world.state)
    job_id, line_id = rehearsal_job(client, sid, initial["revision"])
    assert world.state == before and not world.knows("player", "crew_report")
    url = f"/sessions/{sid}/talk/{job_id}/performance-events"
    for kind in ("ack", "started"):
        response = client.post(url, json=event(line_id, kind))
        assert response.status_code == 200 and response.json()["job"]["status"] == "waiting_delivery"
        assert world.state == before
    result = client.post(url, json=event(line_id, "completed", skipped=True)).json()
    assert result["ok"] and result["job"]["status"] == "completed"
    assert world.knows("player", "crew_report") and world.state["tick"] == 0
    assert result["job"]["lines"][0]["delivered"] and not result["job"]["lines"][0]["legacy"]
    assert result["job"]["lines"][0]["visuals_skipped"]
    assert client.app.state.bridge.transport.calls == []
    assert client.app.state.bridge.ledger.report()["calls"] == []


def test_cancelled_rehearsal_preview_and_invalid_event_cannot_apply_decisions(performance_client):
    client = performance_client
    sid, view = make_session(client)
    world = client.app.state.engines[sid]
    before = deepcopy(world.state)
    job_id, line_id = rehearsal_job(client, sid, view["revision"])
    url = f"/sessions/{sid}/talk/{job_id}/performance-events"
    invalid = client.post(url, json={**event(line_id, "ack"), "world_flags": {"traffic_confirmed": True}})
    assert invalid.status_code == 422
    assert client.post(url, json=event(line_id, "interrupted")).json()["job"]["status"] == "cancelled"
    assert client.post(url, json=event(line_id, "completed")).status_code == 400
    assert world.state == before


@pytest.mark.parametrize("mode", ["live", "rehearsal"])
def test_legacy_ack_remains_idempotent_and_is_explicitly_marked(performance_client, mode):
    client = performance_client
    sid, view = make_session(client, mode)
    if mode == "rehearsal":
        job_id, line_id = rehearsal_job(client, sid, view["revision"])
    else:
        created = client.post(f"/sessions/{sid}/talk", json={"expected_revision": view["revision"],
            "npc_id": "lin", "text": "请说明分工", "audience": ["lin"]}).json()
        job_id = created["job"]["id"]
        for _ in range(300):
            current = client.get(f"/sessions/{sid}/talk/{job_id}").json()["job"]
            if current["status"] != "running":
                break
            time.sleep(.01)
        assert current["status"] == "waiting_delivery", current
        line_id = current["lines"][0]["id"]
    url = f"/sessions/{sid}/talk/{job_id}/ack"
    result = client.post(url, json={"line_id": line_id}).json()
    assert result["ok"] and result["legacy"] and result["delivery_protocol"] == "legacy_ack"
    line = result["job"]["lines"][0]
    assert line["delivered"] and line["legacy"] and line["playback_status"] == "completed"
    assert line["performance"] and line["emotion"] and line["body_action"]
    revision = result["view"]["revision"]
    repeated = client.post(url, json={"line_id": line_id}).json()
    assert repeated["ok"] and repeated["view"]["revision"] == revision
    assert repeated["view"]["tick"] == 0
