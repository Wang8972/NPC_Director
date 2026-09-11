"""No-network tests: the real v2 service/executor/state with recorded model nodes."""
from __future__ import annotations

import asyncio
import copy
import json
from pathlib import Path

import pytest

from last_light.director import DirectorBridge, JOB_CONTEXT, UsageLedger, TokenBudgetExceeded
from last_light.director_contracts import TrainMeaning


def decode(raw):
    # v2 sometimes prefixes the JSON with its untrusted-player-input notice.
    start = raw.index("{")
    return json.JSONDecoder().raw_decode(raw[start:])[0]


class WorldDouble:
    """Only the world boundary is tiny; NPC service and its node DAG are real."""
    def __init__(self, sid="session_test"):
        self.sid, self.revision, self.tick = sid, 0, 0
        self.applied, self.lines, self.decision_ids = [], [], set()
        self.facts = {
            "lin": [{"id": "traffic_unknown", "text": "邻线状态未确认。", "source": "岗位消息", "quality": "reported"}],
            "chen": [{"id": "temporary_fix", "text": "陈默遗漏复测却签了完工。", "source": "亲历", "quality": "observed"}],
            "zhou": [], "xu": [],
        }

    def view(self):
        return {"session_id": self.sid, "revision": self.revision, "tick": self.tick,
                "mode": "live", "actors": [{"id": npc} for npc in ("player", "lin", "zhou", "chen", "xu")],
                "dialogue": self.lines}

    def npc_context(self, npc):
        return {"npc_id": npc, "name": npc, "room_id": "cabin07",
                "known_facts": copy.deepcopy(self.facts[npc]), "promises": [],
                "accepted_tasks": [], "witnesses": ["lin", "chen", "zhou", "xu"],
                "scene": {"actors": [{"id": x} for x in ("lin", "chen", "zhou", "xu")]},
                "events": [], "objectives": [],
                "legal_actions": [{"id": "isolate_aux", "target_id": "cabinet", "actor_ids": ["chen"],
                                   "label": "隔离辅助支路", "duration": 1},
                                  {"id": "count_passengers", "target_id": "manifest", "actor_ids": ["lin", "player"],
                                   "label": "清点", "duration": 1}]}

    def apply_decision(self, npc, decision):
        if decision["decision_id"] not in self.decision_ids:
            self.decision_ids.add(decision["decision_id"])
            self.applied.append((npc, decision))
            self.revision += 1
        return {"ok": True, "view": self.view()}

    def record_dialogue(self, npc, text, line_id, **kwargs):
        if not any(line["id"] == line_id for line in self.lines):
            self.lines.append({"id": line_id, "npc_id": npc, "text": text})
            self.revision += 1


class RecordedNodes:
    """Scripted transport, never exposed as live AI or a quality evaluation."""
    def __init__(self, *, cooperate=False, meaning=None):
        self.cooperate, self.meaning = cooperate, meaning or {}
        self.inputs, self.calls, self.sources = [], [], {}
        self.started, self.release = asyncio.Event(), asyncio.Event()
        self.block = False

    async def __call__(self, agent, raw, output_type):
        from npc_director.contracts import DialogueDraft, PerformanceOutput
        from npc_director.contracts.planning import TurnAnalysis, QualityVerdict
        from npc_director.orchestration.bounded_executor import TypedModelCall
        from last_light.director_contracts import PlayerEvidence

        payload = decode(raw)
        key = JOB_CONTEXT.get()
        if output_type is TurnAnalysis:
            self.inputs.append(copy.deepcopy(payload))
            self.sources[key] = payload
            self.started.set()
            if self.block:
                await self.release.wait()
            npc = payload["npc_id"]
            autonomous = payload.get("stimulus", {}).get("origin") == "npc"
            output = TurnAnalysis(
                intent="other", objective="真实回应并等待执行结果", confidence=.95,
                needs_narrative=False, needs_lore=False, negotiation=False,
                collaboration_requests=[{"target_npc_id": "chen", "purpose": "问清辅助支路", "text": "陈默，能否说明你能确认的支路情况？"}]
                if self.cooperate and npc == "lin" and not autonomous else [],
            )
        elif output_type is DialogueDraft:
            npc = self.sources[key]["npc_id"]
            dialogue = {"lin": "我愿意负责清点，先确认每个人的位置。",
                        "chen": "我愿意隔离辅助支路，之后仍要验证。",
                        "zhou": "我女儿还在05，我得去接她。",
                        "xu": "借用前我们先说清用途和归还时间。"}[npc]
            output = DialogueDraft(dialogue={"text": dialogue}, coarse_emotion="neutral", primary_emotion="calm")
        elif output_type is PerformanceOutput:
            output = PerformanceOutput(performance={
                "dialogue": payload["dialogue"], "emotion": {"coarse": "neutral", "primary": "calm"},
                "body_cues": [{"action": "idle"}], "face_cues": [{"preset": "neutral"}], "confidence": .95,
            })
        elif output_type is QualityVerdict:
            output = QualityVerdict(passed=True, naturalness=4, persona_consistency=4, response_coverage=4)
        elif output_type is TrainMeaning:
            output = TrainMeaning.model_validate(self.meaning.get(payload["npc_id"], {}))
        elif output_type is PlayerEvidence:
            output = PlayerEvidence()
        else:
            raise AssertionError(f"unexpected schema {output_type.__name__}")
        self.calls.append(output_type.__name__)
        return TypedModelCall(output=output)


async def poll(bridge, sid, job_id):
    for _ in range(500):
        result = bridge.get_job(sid, job_id)
        if result["status"] != "running":
            return result
        await asyncio.sleep(.01)
    raise AssertionError("job did not settle")


def make_bridge(tmp_path, transport=None, world=None):
    world = world or WorldDouble()
    transport = transport or RecordedNodes()
    bridge = DirectorBridge(tmp_path, lambda sid: world, lambda sid: None,
                            typed_runner=transport, model="recorded-test")
    return bridge, world, transport


@pytest.mark.asyncio
async def test_actual_v2_delivery_and_social_commit_are_idempotent(tmp_path):
    meaning = {"lin": {"title": "逐人清点", "steps": [{"id": "s1", "action_id": "count_passengers",
               "actor_id": "lin", "target_id": "manifest"}],
               "decisions": [{"kind": "accept_task", "evidence_quote": "我愿意负责清点", "action_ids": ["count_passengers"]}]}}
    bridge, world, nodes = make_bridge(tmp_path, RecordedNodes(meaning=meaning))
    job = await bridge.start(world.sid, "lin", "你愿意清点吗？", ["lin"])
    ready = await poll(bridge, world.sid, job["id"])
    assert ready["status"] == "waiting_delivery", ready
    assert world.applied == [] and world.tick == 0
    assert ready["suggested_steps"] == []
    assert {"TurnAnalysis", "DialogueDraft", "PerformanceOutput", "QualityVerdict", "TrainMeaning"} <= set(nodes.calls)
    line_id = ready["lines"][0]["id"]
    await bridge.acknowledge(world.sid, job["id"], line_id)
    await bridge.acknowledge(world.sid, job["id"], line_id)  # duplicate while processing
    complete = await poll(bridge, world.sid, job["id"])
    assert complete["status"] == "completed", complete
    await bridge.acknowledge(world.sid, job["id"], line_id)
    assert len(world.applied) == len(world.lines) == 1
    assert world.tick == 0  # talking and accepting never perform the task
    assert complete["suggested_steps"][0]["action_id"] == "count_passengers"
    store = bridge._service(world.sid).episodes.store
    assert store.get_context(world.sid, "lin")["dialogue_events"][-1]["speaker_id"] == "lin"
    await bridge.close()


@pytest.mark.asyncio
async def test_cancel_unheard_line_never_commits(tmp_path):
    bridge, world, _ = make_bridge(tmp_path)
    job = await bridge.start(world.sid, "lin", "请说明情况", ["lin"])
    ready = await poll(bridge, world.sid, job["id"])
    cancelled = await bridge.cancel(world.sid, job["id"])
    assert cancelled["status"] == "cancelled"
    assert not world.lines and not world.applied
    with pytest.raises(ValueError, match="cancelled"):
        await bridge.acknowledge(world.sid, job["id"], ready["lines"][0]["id"])
    context = bridge._service(world.sid).episodes.store.get_context(world.sid, "lin")
    assert not any(d["speaker_id"] == "lin" for d in context["dialogue_events"])


@pytest.mark.asyncio
async def test_cancellation_interrupts_inflight_generation(tmp_path):
    nodes = RecordedNodes()
    nodes.block = True
    bridge, world, _ = make_bridge(tmp_path, nodes)
    job = await bridge.start(world.sid, "lin", "你好", ["lin"])
    await asyncio.wait_for(nodes.started.wait(), 5)
    cancelled = await bridge.cancel(world.sid, job["id"])
    nodes.release.set()
    await asyncio.sleep(.01)
    assert cancelled["status"] == "cancelled"
    assert bridge.get_job(world.sid, job["id"])["lines"] == []
    assert world.applied == []


@pytest.mark.asyncio
async def test_world_revision_change_rejects_late_generation(tmp_path):
    nodes = RecordedNodes()
    nodes.block = True
    bridge, world, _ = make_bridge(tmp_path, nodes)
    job = await bridge.start(world.sid, "lin", "你好", ["lin"])
    await asyncio.wait_for(nodes.started.wait(), 5)
    world.revision += 1
    nodes.release.set()
    result = await poll(bridge, world.sid, job["id"])
    assert result["status"] == "failed"
    assert result["lines"] == [] and world.applied == []


@pytest.mark.asyncio
async def test_real_consultation_waits_for_delivery_and_keeps_private_context(tmp_path):
    bridge, world, nodes = make_bridge(tmp_path, RecordedNodes(cooperate=True))
    job = await bridge.start(world.sid, "lin", "请和陈默商量辅助支路", ["lin", "chen"])
    ready = await poll(bridge, world.sid, job["id"])
    assert ready["status"] == "waiting_delivery", ready
    assert [source["npc_id"] for source in nodes.inputs] == ["lin"]
    assert "遗漏复测" not in json.dumps(nodes.inputs[0], ensure_ascii=False)
    await bridge.acknowledge(world.sid, job["id"], ready["lines"][0]["id"])
    second = await poll(bridge, world.sid, job["id"])
    assert second["status"] == "waiting_delivery", second
    assert second["lines"][-1]["npc_id"] == "chen"
    assert "遗漏复测" in json.dumps(nodes.inputs[1], ensure_ascii=False)
    await bridge.cancel(world.sid, job["id"])
    # Lin's actually heard statement stays. Chen's unfinished delivery does not.
    assert [line["npc_id"] for line in world.lines] == ["lin"]


@pytest.mark.asyncio
async def test_sessions_and_checkpoint_do_not_rollback_cost(tmp_path):
    worlds = {key: WorldDouble(key) for key in ("one", "two")}
    bridge = DirectorBridge(tmp_path, worlds.__getitem__, lambda sid: None,
                            typed_runner=RecordedNodes(), model="recorded-test")
    for sid in worlds:
        job = await bridge.start(sid, "lin", "你好", ["lin"])
        ready = await poll(bridge, sid, job["id"])
        await bridge.acknowledge(sid, job["id"], ready["lines"][0]["id"])
        await poll(bridge, sid, job["id"])
    assert bridge._db_path("one") != bridge._db_path("two")
    snapshot = tmp_path / "snapshot.sqlite"
    await bridge.checkpoint("one", snapshot)
    call_id = bridge.ledger.reserve("recorded-test", "cost-fixture", 100)
    bridge.ledger.finish(call_id, total_tokens=30)
    await bridge.restore_checkpoint("one", snapshot)
    assert bridge.ledger.report()["charged_tokens"] == 30
    assert bridge._service("two").episodes.store.get_context("two", "lin")["dialogue_events"]
    await bridge.close()


def test_usage_ledger_reserves_atomically_and_charges_unknown_calls(tmp_path):
    ledger = UsageLedger(tmp_path / "usage.sqlite", limit=100)
    one = ledger.reserve("qwen3.8-flash", "planner", 70)
    with pytest.raises(TokenBudgetExceeded):
        ledger.reserve("qwen3.8-flash", "writer", 40)
    ledger.finish(one, total_tokens=20)
    two = ledger.reserve("qwen3.8-flash", "writer", 70)
    ledger.finish(two, status="cancelled")
    ledger.finish(two, total_tokens=0)  # cannot refund after cancellation
    assert ledger.report()["charged_tokens"] == 90
    assert UsageLedger(tmp_path / "usage.sqlite", limit=100).report()["charged_tokens"] == 90


def test_grounding_rejects_illegal_actions_private_facts_and_forged_consent(tmp_path):
    bridge, world, _ = make_bridge(tmp_path)
    job = bridge._new_job(world.sid, "lin", "你好", ["lin"])
    context = world.npc_context("lin")
    with pytest.raises(ValueError, match="unknown or mismatched"):
        bridge._validate_meaning(TrainMeaning(steps=[{"id": "s1", "action_id": "teleport",
            "actor_id": "lin", "target_id": "child"}]), "lin", "我可以", context, job)
    with pytest.raises(ValueError, match="unknown fact"):
        bridge._validate_meaning(TrainMeaning(decisions=[{"kind": "share_fact", "fact_ids": ["temporary_fix"],
            "audience": ["player"], "evidence_quote": "我可以"}]), "lin", "我可以", context, job)
    with pytest.raises(ValueError, match="not grounded"):
        bridge._validate_meaning(TrainMeaning(decisions=[{"kind": "accept_task", "action_ids": ["count_passengers"],
            "evidence_quote": "同意"}]), "lin", "还要问清条件", context, job)
    with pytest.raises(ValueError, match="another actor"):
        bridge._validate_meaning(TrainMeaning(decisions=[{"kind": "accept_task", "action_ids": ["isolate_aux"],
            "evidence_quote": "我可以"}]), "lin", "我可以", context, job)


@pytest.mark.asyncio
async def test_rehearsal_cannot_invoke_real_or_recorded_transport(tmp_path):
    bridge, world, nodes = make_bridge(tmp_path)
    old = world.view
    world.view = lambda: {**old(), "mode": "rehearsal"}
    await bridge.sync_world(world.sid)
    with pytest.raises(Exception, match="排练"):
        await bridge.start(world.sid, "lin", "你好", [])
    assert nodes.calls == []


def test_explicit_helper_consent_keeps_primary_actor_capability_checks(tmp_path):
    bridge, world, _ = make_bridge(tmp_path)
    job = bridge._new_job(world.sid, "lin", "一起协助检修", ["lin", "chen"])
    context = world.npc_context("lin")
    context["legal_actions"][0]["kind"] = "repair"
    meaning = TrainMeaning(decisions=[{"kind": "accept_task", "role": "helper",
        "action_ids": ["isolate_aux"], "evidence_quote": "我来协助陈默"}])
    validated = bridge._validate_meaning(meaning, "lin", "我来协助陈默。", context, job)
    assert validated.decisions[0].world_payload("helper_once")["role"] == "helper"
    with pytest.raises(ValueError, match="no capability"):
        bridge._validate_meaning(TrainMeaning(steps=[{"id": "s1", "action_id": "isolate_aux",
            "actor_id": "lin", "target_id": "cabinet"}]), "lin", "我来协助陈默。", context, job)
    context["legal_actions"][0]["kind"] = "communicate"
    with pytest.raises(ValueError, match="another actor"):
        bridge._validate_meaning(meaning, "lin", "我来协助陈默。", context, job)
