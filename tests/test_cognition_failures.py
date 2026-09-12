from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta

import pytest

from eval.token_ledger import EvaluationBudgetExceeded, TokenLedger
from npc_director.config import Settings
from npc_director.contracts import EngineEvent
from npc_director.contracts.cognition import BehaviorDecision, MemoryConsolidation, MemoryInsight
from npc_director.contracts.episodes import KnowledgeClaim
from npc_director.contracts.planning import TurnAnalysis
from npc_director.orchestration.bounded_executor import TypedModelCall
from npc_director.orchestration.cognition import preview_behavior
from npc_director.orchestration.service import build_default_service
from npc_director.state.cognition_store import CognitionStore
from npc_director.state.memory_store import LongTermMemoryStore
from npc_director.unity_adapter.base import build_idempotency_key
from tests.test_cognition import event, job_store
from tests.test_episode_service import Adapter, FixtureExecutor, request
from tests.test_memory_relevance import memory


def test_migration_retains_id_and_provenance_without_global_copy(tmp_path):
    path = tmp_path / "db"
    old = LongTermMemoryStore(path)
    old.add(memory("scoped", "旧承诺"), session_id="game-a")
    old.add(memory("global", "全局秘密"))
    migrated = CognitionStore(path)
    record = migrated.records("game-a", "elder_maren")[0]
    assert record.memory_id == "scoped"
    assert record.source_turn_ids == ["earlier-turn"]
    assert record.epistemic_status == "legacy_unverified"
    assert migrated.records("new-game", "elder_maren") == []
    assert len(CognitionStore(path).records("game-a", "elder_maren")) == 1


def test_expired_source_excluded_from_recall_and_reflection(tmp_path):
    store, _, ep = job_store(tmp_path)
    expired = event(3, text="限时通行授权", episode=ep.id).model_copy(
        update={
            "claims": [
                KnowledgeClaim(
                    content_id="pass", expires_at=datetime.now(UTC) - timedelta(seconds=1)
                )
            ]
        }
    )
    store.observe(expired)
    assert not any("限时" in m["content"] for m in store.recall("s", "elder_maren", "限时通行"))


def test_association_can_return_related_memory_without_query_words(tmp_path):
    store = CognitionStore(tmp_path / "db")
    for i, text in enumerate(["扳手仍在我的箱子里", "那个箱子是蓝色的"]):
        store.observe(
            event(i, text=text).model_copy(
                update={"origin": "npc", "status": "completed", "speaker_id": "village_guard"}
            )
        )
    found = store.recall("s", "elder_maren", "扳手")
    assert any("蓝色" in m["content"] for m in found)
    assert store.recall("another", "elder_maren", "扳手") == []


def test_parallel_claim_is_single_owner_and_retry_reserves_again(tmp_path):
    store, episodes, ep = job_store(tmp_path)
    with ThreadPoolExecutor(max_workers=2) as pool:
        jobs = list(pool.map(store.claim, ["worker-a", "worker-b"]))
    assert sum(j is not None for j in jobs) == 1
    job = next(j for j in jobs if j)
    episodes._record_model_usage(ep.id, job["reservation_id"], usage_known=False)
    store.finish(job, None, error="TimeoutError")
    assert store.retry_failed(job["job_id"])
    second = store.claim("worker-c")
    assert second["reservation_id"] != job["reservation_id"]
    assert episodes.get_episode(ep.id).used_model_calls == 2
    assert not store.finish(job, MemoryConsolidation())
    store.finish(second, None, error="TimeoutError")
    assert not store.retry_failed(job["job_id"])


@pytest.mark.asyncio
async def test_interruption_never_commits_candidate_mode(tmp_path):
    service = build_default_service(Settings(database_path=tmp_path / "db", cognition_enabled=True))

    class Executor(FixtureExecutor):
        async def generate(self, source, **kwargs):
            result = await super().generate(source, **kwargs)
            return result.model_copy(
                update={
                    "cognitive_commit": {
                        "expected_version": 0,
                        "behavior": {"mode_id": "guarded", "version": 0},
                    }
                }
            )

    service.executor = Executor()
    adapter = Adapter()
    await service.run_turn(request(), adapter=adapter)
    directive = adapter.directives[0]
    await service.process_engine_event(
        EngineEvent(
            session_id=directive.session_id,
            turn_id=directive.turn_id,
            idempotency_key=build_idempotency_key(directive),
            event_type="interrupted",
        )
    )
    snapshot = service.get_cognition("session-v2", "elder_maren")
    assert snapshot["behavior"]["mode_id"] == "neutral"
    assert not any(m["content"].startswith("elder_maren报告") for m in snapshot["memories"])


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "decision,error",
    [
        ({"mode_id": "omnipotent", "reason": "test"}, "unregistered"),
        (
            {
                "mode_id": "guarded",
                "reason": "test",
                "reason_code": "boundary",
                "evidence_refs": ["foreign"],
            },
            "visible",
        ),
        ({"mode_id": "guarded", "reason": "test", "reason_code": "boundary"}, "causal"),
        (
            {"mode_id": "neutral", "reason": "任务已完成", "reason_code": "goal_completed"},
            "observed",
        ),
    ],
)
async def test_mode_admission_rejects_fabricated_authority(tmp_path, decision, error):
    service = build_default_service(Settings(database_path=tmp_path / "db", cognition_enabled=True))
    executor = FixtureExecutor()
    service.executor = executor
    await service.run_turn(request(), adapter=Adapter())
    with pytest.raises(ValueError, match=error):
        preview_behavior(
            executor.inputs[0],
            TurnAnalysis(
                intent="other", objective="问候", behavior_decision=BehaviorDecision(**decision)
            ),
        )


@pytest.mark.asyncio
async def test_memory_worker_failure_is_bounded_and_never_writes_world(tmp_path):
    service = build_default_service(
        Settings(database_path=tmp_path / "state.db", cognition_enabled=True)
    )
    store, _, ep = job_store(tmp_path)
    calls = []

    async def bad(agent, text, output_type):
        calls.append(text)
        return TypedModelCall(
            output=MemoryConsolidation(
                insights=[
                    MemoryInsight(
                        kind="belief", content="来自其他角色的秘密", source_memory_ids=["foreign"]
                    )
                ]
            ),
            total_tokens=10,
        )

    service.executor.primary._typed_runner = bad
    before = service.domain_store.get("elder_maren", session_id="s")
    await service.drain_memory_jobs("s")
    assert len(calls) == 2
    assert service.domain_store.get("elder_maren", session_id="s") == before
    assert not any(m.kind == "belief" for m in store.records("s", "elder_maren"))
    assert service.episodes.store.get_episode(ep.id).reserved_tokens == 0


def test_global_budget_is_shared_across_phases_and_failures(tmp_path):
    ledger = TokenLedger(tmp_path / "ledger.db")
    ledger.PILOT = 100
    first = ledger.reserve(80, "memory")
    ledger.settle(first)  # unknown usage remains conservatively charged
    with pytest.raises(EvaluationBudgetExceeded):
        ledger.reserve(21, "judge")
    assert ledger.snapshot()["stopped"]
    other = TokenLedger(tmp_path / "ledger.db", phase="full")
    assert other.snapshot()["charged_tokens"] == 80
    second = other.reserve(50, "writer")
    other.settle(second, 25)
    assert other.snapshot()["charged_tokens"] == 105
    assert other.snapshot()["unknown_usage_calls"] == 1


def test_parallel_global_reservations_cannot_overspend(tmp_path):
    ledger = TokenLedger(tmp_path / "ledger.db")
    ledger.PILOT = 100

    def reserve(_):
        try:
            return ledger.reserve(60, "model")
        except EvaluationBudgetExceeded:
            return None

    with ThreadPoolExecutor(max_workers=4) as pool:
        tickets = list(pool.map(reserve, range(4)))
    assert sum(t is not None for t in tickets) == 1
    assert ledger.snapshot()["charged_tokens"] == 60


def test_short_aliases_are_resolved_only_inside_current_owner_view():
    from npc_director.contracts.cognition import default_modes
    from tests.test_bounded_executor import director_input

    source = director_input().model_copy(
        update={
            "actor_context": {
                "cognition": {
                    "behavior": {"mode_id": "neutral", "version": 0},
                    "mode_catalog": [m.model_dump() for m in default_modes()],
                    "visible_event_ids": ["private-owned-event"],
                    "recalled_memories": [],
                    "evidence_aliases": {
                        "e1": "private-owned-event",
                        "bounded-turn": "private-owned-event",
                    },
                }
            }
        }
    )
    analysis = TurnAnalysis(
        intent="other",
        objective="回应威胁",
        behavior_decision=BehaviorDecision(
            mode_id="guarded", reason="当前收到威胁", reason_code="boundary", evidence_refs=["e1"]
        ),
    )
    result = preview_behavior(source, analysis)
    assert result.actor_context["cognition"]["effective_behavior"]["evidence_refs"] == [
        "private-owned-event"
    ]
    analysis.behavior_decision.evidence_refs = ["e999"]
    with pytest.raises(ValueError, match="visible"):
        preview_behavior(source, analysis)
    unchanged = TurnAnalysis(
        intent="other",
        objective="问候",
        used_memory_refs=["not-recalled"],
        behavior_decision=BehaviorDecision(
            mode_id="neutral", reason="继续", evidence_refs=["unknown"]
        ),
    )
    result = preview_behavior(source, unchanged)
    assert unchanged.used_memory_refs == []
    assert result.actor_context["cognition"]["effective_behavior"]["mode_id"] == "neutral"


@pytest.mark.asyncio
async def test_implicit_planner_operation_cannot_bypass_mode_scope():
    from npc_director.contracts.cognition import BehaviorModeDefinition
    from tests.test_bounded_executor import ROUTER, director_input
    from tests.test_dynamic_planning import make_executor, successful_outputs

    source = director_input().model_copy(
        update={
            "actor_context": {
                "cognition": {
                    "behavior": {"mode_id": "neutral", "version": 0},
                    "mode_catalog": [
                        BehaviorModeDefinition(
                            mode_id="neutral", purpose="仅对话", allowed_operations=[]
                        ).model_dump()
                    ],
                    "visible_event_ids": [],
                    "recalled_memories": [],
                }
            }
        }
    )
    analysis = TurnAnalysis(intent="lore_question", objective="查找秘密", needs_lore=True)
    executor, calls = make_executor(successful_outputs(analysis))
    result = await executor.generate(source)
    assert result.execution_trace.stop_reason in {"invalid_plan", "node_failed"}
    assert all(call[0] is ROUTER for call in calls)


@pytest.mark.asyncio
async def test_crash_recovery_does_not_double_charge_known_usage(tmp_path):
    service = build_default_service(
        Settings(database_path=tmp_path / "state.db", cognition_enabled=True)
    )
    store, episodes, ep = job_store(tmp_path)
    first = store.claim("crashed-worker", lease_seconds=-1)
    episodes._record_model_usage(ep.id, first["reservation_id"], total_tokens=7)

    async def runner(agent, text, output_type):
        return TypedModelCall(
            output=MemoryConsolidation(
                insights=[
                    MemoryInsight(
                        kind="belief", content="仍需核实玩家的说法", source_memory_ids=["m1"]
                    )
                ]
            ),
            total_tokens=10,
        )

    service.executor.primary._typed_runner = runner
    await service.drain_memory_jobs("s", limit=2)
    assert episodes.get_episode(ep.id).used_tokens == 17
    belief = next(m for m in store.records("s", "elder_maren") if m.kind == "belief")
    assert belief.source_memory_ids and all(
        mid.startswith("cog:") for mid in belief.source_memory_ids
    )
    assert not store.finish(first, MemoryConsolidation())


def test_new_evidence_revises_belief_without_rewriting_original_events(tmp_path):
    store, episodes, ep = job_store(tmp_path)
    first = store.claim("first")
    source = json.loads(first["snapshot_json"])["memories"][0]["memory_id"]
    episodes._record_model_usage(ep.id, first["reservation_id"], total_tokens=0)
    store.finish(
        first,
        MemoryConsolidation(
            insights=[
                MemoryInsight(
                    kind="belief",
                    content="对方声称已归还，可信程度仍待确认",
                    source_memory_ids=[source],
                )
            ]
        ),
    )
    old = next(m for m in store.records("s", "elder_maren") if m.kind == "belief")
    originals = {
        m.memory_id: m.content for m in store.records("s", "elder_maren") if m.kind == "experience"
    }
    store.observe(event(3, text="我承认之前说归还了不是真的", episode=ep.id))
    with store.transaction() as conn:
        store.enqueue(conn, "s", "elder_maren", ep.id)
    second = store.claim("second")
    new_source = next(
        m.memory_id for m in store.records("s", "elder_maren") if "event-3" in m.source_event_ids
    )
    assert store.finish(
        second,
        MemoryConsolidation(
            insights=[
                MemoryInsight(
                    kind="belief",
                    content="玩家已纠正先前说法，不应再依据旧说法相信物品已归还",
                    source_memory_ids=[new_source],
                    supersedes=[old.memory_id],
                )
            ]
        ),
    )
    records = store.records("s", "elder_maren")
    assert next(m for m in records if m.memory_id == old.memory_id).validity == "superseded"
    assert all(
        next(m for m in records if m.memory_id == mid).content == text
        for mid, text in originals.items()
    )
    assert len([m for m in records if m.kind == "belief" and m.validity == "active"]) == 1


@pytest.mark.asyncio
async def test_fallback_without_analysis_can_complete_without_cognitive_side_effects(tmp_path):
    from npc_director.contracts.planning import ExecutionTrace
    from npc_director.orchestration.testing import DeterministicDirectorExecutor
    from tests.test_episode_service import complete

    service = build_default_service(Settings(database_path=tmp_path / "db", cognition_enabled=True))

    class EmptyAnalysisExecutor:
        async def generate(self, source, **kwargs):
            result = await DeterministicDirectorExecutor().generate(source, **kwargs)
            return result.model_copy(
                update={"execution_trace": ExecutionTrace(stop_reason="node_failed")}
            )

    service.executor = EmptyAnalysisExecutor()
    adapter = Adapter()
    await service.run_turn(request(), adapter=adapter)
    await complete(service, adapter.directives[0])
    snapshot = service.get_cognition("session-v2", "elder_maren")
    assert snapshot["behavior"]["mode_id"] == "neutral"
    assert all(m["kind"] == "experience" for m in snapshot["memories"])


@pytest.mark.asyncio
async def test_cognition_judge_receives_persistence_evidence_without_live_calls():
    from pathlib import Path

    from eval.episode_runner import EpisodeQualityVerdict, LiveEpisodeTransport, load_episode_cases

    class Spy(LiveEpisodeTransport):
        def __init__(self):
            self.settings = Settings()
            self.judge_model = None

        async def __call__(self, agent, run_input, output_type):
            self.payload = json.loads(run_input)
            self.instructions = agent.instructions
            return TypedModelCall(
                output=EpisodeQualityVerdict(
                    task_completion=4,
                    continuity=4,
                    persona=4,
                    naturalness=4,
                    performance_alignment=4,
                    passed=True,
                    reasons=["fixture only"],
                )
            )

    case = next(
        c for c in load_episode_cases(Path("eval/cases/cognition.jsonl")) if c.id == "cog_restart"
    )
    spy = Spy()
    await spy.evaluate(
        case,
        {
            "transcript": [],
            "checks": {"expected_behavior_mode": True},
            "published_content": [],
            "cognition": {
                "main": {
                    "elder_maren": {
                        "behavior": {"mode_id": "guarded", "source_turn_id": "completed-turn"},
                        "memories": [],
                        "jobs": [],
                    }
                }
            },
        },
    )
    assert (
        spy.payload["cognition_evidence"]["main"]["elder_maren"]["behavior"]["mode_id"] == "guarded"
    )
    assert spy.payload["injected_fault"] == "restart_after_first"
    assert "不要求NPC向玩家解释" in spy.instructions
