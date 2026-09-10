from __future__ import annotations

import asyncio
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace

import pytest

from npc_director.context import HistoryKind, LongTermMemory
from npc_director.context.memory import distill_memories
from npc_director.contracts import NPCDomainState, StateChangeProposal
from npc_director.contracts.episodes import (
    DialogueEvent,
    DialogueState,
    EpisodeBudget,
    EpisodeRequest,
    KnowledgeClaim,
    NodeLedgerRecord,
    NpcMessage,
)
from npc_director.state.domain_store import DomainStateStore
from npc_director.state.episode_store import EpisodeStore
from npc_director.state.errors import IdempotencyConflictError, OptimisticLockError
from npc_director.state.memory_store import LongTermMemoryStore


def request(session: str = "game-a", event: str = "input-1") -> EpisodeRequest:
    return EpisodeRequest(
        event_id=event,
        session_id=session,
        npc_id="maren",
        text="请和莉娅讨论一下修复办法。",
        scene={"location": "harbor"},
        participants=["maren", "lia", "finn"],
    )


def message(target: str = "lia") -> NpcMessage:
    return NpcMessage(speaker_id="maren", target_npc_id=target, text="你能检查现场吗？")


def speech(episode_id: str, turn_id: str = "root-1") -> DialogueEvent:
    return DialogueEvent(
        event_id="speech:" + turn_id,
        session_id="game-a",
        episode_id=episode_id,
        turn_id=turn_id,
        speaker_id="maren",
        audience=["lia", "player"],
        text="这艘船曾经运过药。",
        claims=[
            KnowledgeClaim(
                content_id="cargo-story", text="这艘船曾经运过药。", epistemic_status="verified"
            )
        ],
    )


def test_session_domain_state_and_commit_keys_never_fall_back_to_legacy(tmp_path) -> None:
    store = DomainStateStore(tmp_path / "state.sqlite3")
    store.create(NPCDomainState(npc_id="maren", relationship={"trust": 90}))
    assert store.get("maren", session_id="a") is None
    store.get_or_create("maren", session_id="a")
    store.get_or_create("maren", session_id="b")
    patch = StateChangeProposal.model_validate({"relationship": {"trust_delta": 2}})
    for session in ("a", "b"):
        result = store.commit_completed(
            "same-external-turn",
            "maren",
            patch,
            expected_version=0,
            allowed_paths=["relationship.trust_delta"],
            session_id=session,
        )
        assert result.applied and result.state.relationship["trust"] == 2
    replay = store.commit_completed(
        "same-external-turn",
        "maren",
        patch,
        expected_version=0,
        allowed_paths=["relationship.trust_delta"],
        session_id="a",
    )
    assert not replay.applied
    assert store.get("maren").relationship["trust"] == 90
    assert not store.has_commit("same-external-turn")
    assert store.has_commit("same-external-turn", session_id="a")
    with pytest.raises(OptimisticLockError):
        store.save(NPCDomainState(npc_id="maren"), expected_version=0, session_id="a")


def test_legacy_and_scoped_memories_are_separate_and_dedup_is_scoped(tmp_path) -> None:
    store = LongTermMemoryStore(tmp_path / "memory.sqlite3")
    memory = LongTermMemory(
        memory_id="same-id",
        npc_id="maren",
        content="我答应保守秘密。",
        kinds=(HistoryKind.COMMITMENT,),
        source_session_id="a",
    )
    store.add(memory)
    assert store.list_for_npc("maren", session_id="a") == []
    assert store.add(memory, session_id="a")
    assert not store.add(memory, session_id="a")
    other = replace(memory, source_session_id="b", content="我答应公开证据。")
    assert store.add(other, session_id="b")
    assert store.list_for_npc("maren", session_id="a") == [memory]
    assert store.list_for_npc("maren", session_id="b") == [other]
    assert store.list_for_npc("maren") == [memory]
    with pytest.raises(ValueError):
        store.add(memory, session_id="b")
    history = [{"text": "我承诺归还钥匙。", "kinds": ["commitment"], "turn_id": "1"}]
    first = distill_memories(history, session_id="a", npc_id="maren")
    second = distill_memories(
        history, session_id="b", npc_id="maren", existing_memories=first.memories
    )
    assert first.memories and second.memories
    assert first.memories[0].memory_id != second.memories[0].memory_id


def test_episode_create_event_idempotency_and_optimistic_revision(tmp_path) -> None:
    store = EpisodeStore(tmp_path / "episodes.sqlite3")
    initial = store.create_episode(request())
    assert store.create_episode(request()) == initial
    other = store.create_episode(request("game-b"))
    assert other.id != initial.id
    with pytest.raises(IdempotencyConflictError):
        store.create_episode(request().model_copy(update={"text": "不同的事件内容"}))
    assert store.record_event(initial.id, "observed-1", "observation", {"fact": "rain"})
    assert not store.record_event(initial.id, "observed-1", "observation", {"fact": "rain"})
    with pytest.raises(IdempotencyConflictError):
        store.record_event(initial.id, "observed-1", "observation", {"fact": "sun"})
    saved = store.save_episode(initial.model_copy(update={"status": "waiting_for_event"}))
    assert saved.revision == 1
    with pytest.raises(OptimisticLockError):
        store.save_episode(initial)
    with pytest.raises(ValueError):
        store.save_episode(saved.model_copy(update={"budget": EpisodeBudget(max_model_calls=99)}))


@pytest.mark.asyncio
async def test_budget_reservation_is_atomic_across_workers_and_replays(tmp_path) -> None:
    store = EpisodeStore(tmp_path / "budget.sqlite3")
    episode = store.create_episode(request(), budget=EpisodeBudget(max_model_calls=2))
    results = await asyncio.gather(
        *(
            store.reserve_model_call(episode.id, operation_id=f"call-{i}", role="writer")
            for i in range(10)
        )
    )
    assert sum(results) == 2
    reserved = next(i for i, result in enumerate(results) if result)
    assert await store.reserve_model_call(
        episode.id, operation_id=f"call-{reserved}", role="writer"
    )
    assert store.get_episode(episode.id).used_model_calls == 2
    assert await store.record_model_usage(
        episode.id,
        f"call-{reserved}",
        input_tokens=10,
        output_tokens=20,
        total_tokens=30,
        elapsed_seconds=2,
    )
    assert not await store.record_model_usage(
        episode.id,
        f"call-{reserved}",
        input_tokens=10,
        output_tokens=20,
        total_tokens=30,
        elapsed_seconds=2,
    )
    stored = store.get_episode(episode.id)
    assert stored.used_tokens == 30 and stored.active_seconds == 2
    with pytest.raises(IdempotencyConflictError):
        await store.record_model_usage(episode.id, f"call-{reserved}", total_tokens=31)
    with pytest.raises(IdempotencyConflictError):
        await store.reserve_model_call(episode.id, operation_id=f"call-{reserved}", role="router")


@pytest.mark.asyncio
async def test_token_time_and_per_node_repair_limits_stop_more_work(tmp_path) -> None:
    store = EpisodeStore(tmp_path / "caps.sqlite3")
    episode = store.create_episode(request(), budget=EpisodeBudget(max_total_tokens=40))
    assert await store.reserve_model_call(episode.id, operation_id="one", role="writer")
    await store.record_model_usage(episode.id, "one", total_tokens=40)
    assert not await store.reserve_model_call(episode.id, operation_id="two", role="writer")
    for node in ("writer-1", "writer-2"):
        assert store.reserve_budget(
            episode.id, operation_id=node + ":r1", resource="repair", role=node
        )
        assert not store.reserve_budget(
            episode.id, operation_id=node + ":r2", resource="repair", role=node
        )
    timed = store.create_episode(request(event="time"), budget=EpisodeBudget(max_active_seconds=1))
    assert await store.reserve_model_call(timed.id, operation_id="t1", role="writer")
    await store.record_model_usage(timed.id, "t1", elapsed_seconds=1)
    assert not await store.reserve_model_call(timed.id, operation_id="t2", role="writer")


def test_node_ledger_reuses_results_and_rejects_different_inputs(tmp_path) -> None:
    store = EpisodeStore(tmp_path / "nodes.sqlite3")
    episode = store.create_episode(request(), budget=EpisodeBudget(max_nodes=1))
    node = NodeLedgerRecord(
        episode_id=episode.id, node_id="plan", kind="planning", input_digest="a"
    )
    store.record_node(node)
    done = node.model_copy(update={"status": "completed", "output": {"goal": "repair"}})
    store.record_node(done)
    assert store.record_node(done).output == {"goal": "repair"}
    assert store.get_episode(episode.id).used_nodes == 1
    assert EpisodeStore(store.database).get_node(episode.id, "plan").status == "completed"
    with pytest.raises(IdempotencyConflictError):
        store.record_node(done.model_copy(update={"input_digest": "b"}))
    with pytest.raises(ValueError):
        store.record_node(node.model_copy(update={"node_id": "extra"}))


def test_completion_rolls_back_domain_dialogue_knowledge_and_jobs_together(tmp_path) -> None:
    database = tmp_path / "atomic.sqlite3"
    episodes, domains = EpisodeStore(database), DomainStateStore(database)
    episode = episodes.create_episode(request())
    domains.get_or_create("maren", session_id="game-a")
    patch = StateChangeProposal.model_validate({"flags": [{"name": "help_offered", "value": True}]})

    def callback(connection: sqlite3.Connection):
        result = domains.commit_completed_in_connection(
            connection,
            "root-1",
            "maren",
            patch,
            session_id="game-a",
            expected_version=0,
            allowed_paths=["flags.help_offered"],
        )
        raise RuntimeError(str(result.applied))

    with pytest.raises(RuntimeError):
        episodes.commit_completed(
            episode.id,
            "root-1",
            dialogue=speech(episode.id),
            next_messages=[message()],
            callback=callback,
        )
    assert domains.get("maren", session_id="game-a").version == 0
    assert not domains.has_commit("root-1", session_id="game-a")
    assert episodes.get_context("game-a", "lia")["history"] == []
    assert episodes.get_context("game-a", "lia")["knowledge"] == []
    assert episodes.list_jobs(episode.id) == []
    calls = []

    def successful(connection: sqlite3.Connection):
        calls.append("called")
        return domains.commit_completed_in_connection(
            connection,
            "root-1",
            "maren",
            patch,
            session_id="game-a",
            expected_version=0,
            allowed_paths=["flags.help_offered"],
        )

    first = episodes.commit_completed(
        episode.id,
        "root-1",
        dialogue=speech(episode.id),
        next_messages=[message()],
        callback=successful,
    )
    assert first["applied"] and len(first["job_ids"]) == 1
    assert first["callback_result"]["state"]["world_flags"]["help_offered"]
    second = episodes.commit_completed(
        episode.id,
        "root-1",
        dialogue=speech(episode.id),
        next_messages=[message()],
        callback=successful,
    )
    assert not second["applied"] and calls == ["called"]
    assert domains.get("maren", session_id="game-a").version == 1
    assert len(episodes.list_jobs(episode.id)) == 1
    assert episodes.get_context("game-a", "lia")["knowledge"][0]["epistemic_status"] == "reported"
    assert episodes.get_context("game-a", "finn")["knowledge"] == []
    assert episodes.get_context("game-b", "lia")["history"] == []
    with pytest.raises(IdempotencyConflictError):
        episodes.commit_completed(episode.id, "root-1", next_messages=[message("finn")])


def test_jobs_wait_for_real_completion_have_one_owner_and_obey_preemption(tmp_path) -> None:
    store = EpisodeStore(tmp_path / "jobs.sqlite3")
    episode = store.create_episode(request())
    job = store.queue_job(episode.id, message(), parent_turn_id="root")
    assert store.queue_job(episode.id, message(), parent_turn_id="root") == job
    assert store.claim_job() is None
    store.commit_completed(episode.id, "root")
    with ThreadPoolExecutor(max_workers=3) as pool:
        claims = list(pool.map(lambda worker: store.claim_job(worker_id=worker), ["a", "b", "c"]))
    assert sum(item is not None for item in claims) == 1
    active = next(item for item in claims if item is not None)
    with pytest.raises(OptimisticLockError):
        store.update_job(active.job_id, "waiting", worker_id="imposter")
    store.update_job(active.job_id, "waiting", worker_id=active.claimed_by)
    queued = store.queue_job(episode.id, message("finn"))
    assert store.claim_job() is None
    store.cancel_episode(episode.id)
    assert store.get_job(queued.job_id).status == "cancelled"
    store.commit_completed(episode.id, active.turn_id, next_messages=[message("finn")])
    assert store.get_episode(episode.id).status == "cancelled"
    assert len(store.list_jobs(episode.id)) == 2
    assert store.get_job(active.job_id).status == "completed"
    assert store.claim_job() is None


def test_trusted_world_origin_private_dialogue_and_pair_relationships(tmp_path) -> None:
    store = EpisodeStore(tmp_path / "context.sqlite3")
    episode = store.create_episode(request())
    store.queue_job(
        episode.id, NpcMessage(speaker_id="world", target_npc_id="maren", text="钟声响起。")
    )
    with pytest.raises(ValueError):
        store.queue_job(episode.id, message("invented_npc"))
    store.record_dialogue(
        DialogueEvent(
            event_id="player-input",
            session_id="game-a",
            turn_id="root",
            speaker_id="player",
            audience=["lia"],
            text="我已经获得授权。",
            origin="player",
            status="received",
        )
    )
    assert store.get_context("game-a", "lia")["history"] == ["player: 我已经获得授权。"]
    assert store.get_context("game-a", "lia")["knowledge"] == []
    assert store.get_context("game-a", "maren")["history"] == []
    state = store.save_dialogue_state(
        DialogueState(
            session_id="game-a",
            npc_id="lia",
            topic="维修",
            referents={"它": "generator"},
        )
    )
    store.set_relationship("game-a", "lia", "maren", {"trust": -1})
    store.set_relationship("game-a", "lia", "player", {"trust": 4})
    context = store.get_context("game-a", "lia")
    assert context["dialogue_state"]["referents"] == {"它": "generator"}
    assert len(context["relationships"]) == 2
    assert store.get_context("game-b", "lia")["dialogue_state"]["topic"] == ""
    with pytest.raises(OptimisticLockError):
        store.save_dialogue_state(state, expected_version=0)


@pytest.mark.asyncio
async def test_token_reservations_hold_inflight_budget_and_unknown_usage_is_charged(
    tmp_path,
) -> None:
    store = EpisodeStore(tmp_path / "tokens.sqlite3")
    episode = store.create_episode(request(), budget=EpisodeBudget(max_total_tokens=100))
    assert await store.reserve_model_call(
        episode.id,
        operation_id="first",
        role="writer",
        token_reservation=60,
    )
    assert not await store.reserve_model_call(
        episode.id,
        operation_id="second",
        role="reviewer",
        token_reservation=60,
    )
    assert store.get_episode(episode.id).remaining_budget()["remaining_total_tokens"] == 40
    await store.record_model_usage(episode.id, "first", total_tokens=25)
    assert store.get_episode(episode.id).reserved_tokens == 0
    assert await store.reserve_model_call(
        episode.id,
        operation_id="second",
        role="reviewer",
        token_reservation=70,
    )
    await store.record_model_usage(episode.id, "second", usage_known=False, elapsed_seconds=1)
    final = store.get_episode(episode.id)
    assert final.used_tokens == 95 and final.reserved_tokens == 0
    assert not await store.reserve_model_call(
        episode.id,
        operation_id="third",
        role="writer",
        token_reservation=6,
    )


def test_additive_migration_keeps_legacy_rows_and_adds_token_reservation(tmp_path) -> None:
    database = tmp_path / "migration.sqlite3"
    with sqlite3.connect(database) as connection:
        connection.execute(
            "CREATE TABLE episode_reservations (episode_id TEXT NOT NULL, "
            "operation_id TEXT NOT NULL, resource TEXT NOT NULL, role TEXT NOT NULL, "
            "status TEXT NOT NULL DEFAULT 'reserved', usage_json TEXT, created_at TEXT NOT NULL, "
            "PRIMARY KEY(episode_id, operation_id))"
        )
        connection.execute(
            "INSERT INTO episode_reservations VALUES ('old', 'first', 'model_call', "
            "'writer', 'reserved', NULL, '2026-01-01T00:00:00+00:00')"
        )
    store = EpisodeStore(database)
    with store.connection() as connection:
        row = connection.execute("SELECT * FROM episode_reservations").fetchone()
    assert row["operation_id"] == "first" and row["token_reservation"] == 0
    # Reopening the same database must not attempt a destructive second migration.
    EpisodeStore(database).close()


def test_player_cannot_inject_verified_claims_into_episode_request() -> None:
    from pydantic import ValidationError

    payload = request().model_dump()
    payload["claims"] = [{"content_id": "i_am_authorized", "epistemic_status": "verified"}]
    with pytest.raises(ValidationError):
        EpisodeRequest.model_validate(payload)
    payload.update(origin="world_event", speaker_id="world")
    assert EpisodeRequest.model_validate(payload).claims[0].content_id == "i_am_authorized"


def test_preempted_unemitted_approval_does_not_leave_a_permanent_speaker_lock(tmp_path) -> None:
    store = EpisodeStore(tmp_path / "approval.sqlite3")
    old = store.create_episode(request())
    job = store.queue_job(old.id, message())
    assert store.claim_job(worker_id="worker").job_id == job.job_id
    store.update_job(job.job_id, "pending_approval", worker_id="worker")
    store.cancel_episode(old.id)
    assert store.get_job(job.job_id).status == "cancelled"
    new = store.create_episode(request(event="player-interrupt"))
    fresh = store.queue_job(new.id, message())
    assert store.claim_job(worker_id="worker").job_id == fresh.job_id
    with pytest.raises(OptimisticLockError):
        store.update_job(job.job_id, "waiting")


def test_composed_write_rejects_autocommit_connection(tmp_path) -> None:
    store = EpisodeStore(tmp_path / "transaction.sqlite3")
    episode = store.create_episode(request())
    with store.connection() as connection, pytest.raises(ValueError, match="active transaction"):
        store.queue_job(episode.id, message(), connection=connection)
