from __future__ import annotations

import json
from dataclasses import replace

import pytest

from npc_director.config import Settings
from npc_director.contracts.cognition import BehaviorDecision, MemoryConsolidation, MemoryInsight
from npc_director.contracts.episodes import DialogueEvent, EpisodeRequest
from npc_director.contracts.planning import TurnAnalysis
from npc_director.orchestration.cognition import preview_behavior
from npc_director.orchestration.service import build_default_service
from npc_director.state.cognition_store import CognitionStore
from npc_director.state.episode_store import EpisodeStore
from tests.test_episode_service import Adapter, FixtureExecutor, complete, request


def event(i, *, session="s", npc="elder_maren", text=None, episode=None):
    return DialogueEvent(
        event_id=f"event-{i}",
        session_id=session,
        turn_id=f"turn-{i}",
        speaker_id="player",
        audience=[npc],
        origin="player",
        status="received",
        text=text or f"今天谈论衣服编号{i}",
        episode_id=episode,
    )


def job_store(tmp_path):
    store = CognitionStore(tmp_path / "state.db", reflect_after=2)
    episodes = EpisodeStore(tmp_path / "state.db")
    ep = episodes.create_episode(
        EpisodeRequest(
            event_id="root",
            session_id="s",
            npc_id="elder_maren",
            text="请核实",
            scene={"location": "village_gate", "catalog_version": "m0-v1"},
        )
    )
    store.observe(event(1, text="玩家承诺归还扳手", episode=ep.id))
    store.observe(event(2, text="玩家报告工具已经交还，需要核实", episode=ep.id))
    with store.transaction() as conn:
        store.enqueue(conn, "s", "elder_maren", ep.id)
    return store, episodes, ep


def test_older_than_256_recall_and_owner_isolation(tmp_path):
    store = CognitionStore(tmp_path / "state.db")
    store.observe(event(0, text="矿井扳手藏在工具箱里"))
    for i in range(1, 300):
        store.observe(event(i))
    store.observe(event(0, session="other", text="矿井扳手在另一个存档的秘密地点"))
    store.observe(event(0, npc="village_guard", text="矿井扳手在守卫私密夹层"))
    found = store.recall("s", "elder_maren", "矿井 扳手 工具箱")
    assert found[0]["content"] == "玩家说：矿井扳手藏在工具箱里"
    assert found[0]["source_event_ids"] == ["event-0"]
    assert "秘密" not in json.dumps(found, ensure_ascii=False)
    assert store.recall("missing", "elder_maren", "扳手") == []


def test_duplicate_input_and_read_dont_strengthen_memory(tmp_path):
    store = CognitionStore(tmp_path / "state.db")
    store.observe(event(0, text="旧矿井的扳手"))
    for i in range(1, 34):
        store.observe(event(i))
    before = store.snapshot("s", "elder_maren")
    store.observe(event(0, text="旧矿井的扳手"))
    for _ in range(5):
        store.recall("s", "elder_maren", "扳手")
    assert store.snapshot("s", "elder_maren") == before
    mid = store.recall("s", "elder_maren", "扳手")[0]["memory_id"]
    with store.transaction() as conn:
        store.commit_state(conn, "s", "elder_maren", "completed", memory_refs=[mid])
    reinforced = store.snapshot("s", "elder_maren")
    with store.transaction() as conn:
        store.commit_state(conn, "s", "elder_maren", "completed", memory_refs=[mid])
    assert store.snapshot("s", "elder_maren") == reinforced
    assert next(m for m in reinforced["memories"] if m["memory_id"] == mid)["activation"] == 1


def test_open_commitment_survives_decay_and_restart(tmp_path):
    path = tmp_path / "state.db"
    store = CognitionStore(path)
    store.observe(event(0, text="玩家答应归还扳手"))
    with store.transaction() as conn:
        store.commit_state(
            conn,
            "s",
            "elder_maren",
            "commit",
            commitments=[{"text": "归还扳手", "status": "open", "source_turn_id": "turn-0"}],
        )
    for i in range(1, 130):
        store.observe(event(i))
    records = CognitionStore(path).records("s", "elder_maren")
    commitment = next(m for m in records if m.kind == "commitment")
    assert commitment.pinned and commitment.activation == 1
    assert any(m.validity == "dormant" for m in records if m.kind == "experience")


def test_reflection_has_source_and_cannot_overwrite_experience(tmp_path):
    store, _, _ = job_store(tmp_path)
    job = store.claim("worker")
    inputs = json.loads(job["snapshot_json"])["memories"]
    mid = inputs[0]["memory_id"]
    bad = MemoryConsolidation(
        insights=[
            MemoryInsight(
                kind="belief", content="玩家值得信任", source_memory_ids=[mid], supersedes=[mid]
            )
        ]
    )
    with pytest.raises(ValueError, match="original"):
        store.finish(job, bad)
    good = MemoryConsolidation(
        insights=[
            MemoryInsight(
                kind="belief", content="玩家声称已归还，仍需核实", source_memory_ids=[mid]
            )
        ]
    )
    assert store.finish(job, good)
    result = store.snapshot("s", "elder_maren")
    belief = next(m for m in result["memories"] if m["kind"] == "belief")
    assert belief["epistemic_status"] == "inferred"
    assert belief["source_event_ids"]
    assert not store.finish(job, good)


def test_stale_and_foreign_reflections_are_rejected(tmp_path):
    store, _, _ = job_store(tmp_path)
    job = store.claim("w")
    output = MemoryConsolidation(
        insights=[
            MemoryInsight(kind="summary", content="来自别人的秘密", source_memory_ids=["foreign"])
        ]
    )
    with pytest.raises(ValueError, match="invisible"):
        store.finish(job, output)
    store.observe(event(3, text="新证据表明工具并未交还"))
    assert not store.finish(job, MemoryConsolidation())
    assert store.snapshot("s", "elder_maren")["jobs"][0]["status"] == "obsolete"


@pytest.mark.asyncio
async def test_mode_is_only_committed_on_completion_and_survives_restart(tmp_path):
    config = Settings(database_path=tmp_path / "state.db", cognition_enabled=True)
    service = build_default_service(config)

    class ModeExecutor(FixtureExecutor):
        async def generate(self, source, *, repair_feedback=None):
            result = await super().generate(source, repair_feedback=repair_feedback)
            cog = source.actor_context["cognition"]
            decision = BehaviorDecision(
                mode_id="guarded",
                reason="听到了威胁",
                reason_code="boundary",
                evidence_refs=[cog["visible_event_ids"][0]],
            )
            preview = preview_behavior(
                source,
                TurnAnalysis(intent="threat", objective="回应威胁", behavior_decision=decision),
            )
            return result.model_copy(
                update={
                    "cognitive_commit": {
                        "behavior": preview.actor_context["cognition"]["effective_behavior"],
                        "expected_version": cog["behavior"].get("version", 0),
                    }
                }
            )

    service.executor = ModeExecutor()
    adapter = Adapter()
    await service.run_turn(request(text="不照办就让你付出代价"), adapter=adapter)
    assert service.get_cognition("session-v2", "elder_maren")["behavior"]["mode_id"] == "neutral"
    await complete(service, adapter.directives[0])
    assert service.get_cognition("session-v2", "elder_maren")["behavior"]["mode_id"] == "guarded"
    restarted = build_default_service(replace(config, cognition_enabled=False))
    assert restarted.get_cognition("session-v2", "elder_maren")["behavior"]["mode_id"] == "guarded"


@pytest.mark.asyncio
async def test_cross_role_hearing_requires_completion(tmp_path):
    service = build_default_service(
        Settings(database_path=tmp_path / "state.db", cognition_enabled=True)
    )
    service.executor = FixtureExecutor(cooperate=True)
    adapter = Adapter()
    await service.run_turn(request(text="请问守卫记录"), adapter=adapter)
    assert service.get_cognition("session-v2", "village_guard")["memories"] == []
    await complete(service, adapter.directives[0])
    heard = service.get_cognition("session-v2", "village_guard")["memories"]
    assert heard and all(m["epistemic_status"] == "reported" for m in heard)
    assert service.get_cognition("elsewhere", "village_guard")["memories"] == []


def test_budget_is_reserved_before_job_and_no_duplicate_reservations(tmp_path):
    store, episodes, ep = job_store(tmp_path)
    before = episodes.get_episode(ep.id)
    assert before.used_model_calls == 1 and before.reserved_tokens > 0
    with store.transaction() as conn:
        store.enqueue(conn, "s", "elder_maren", ep.id)
    assert episodes.get_episode(ep.id).used_model_calls == 1
