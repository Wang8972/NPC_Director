from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

import npc_director.state.content_store as content_module
import npc_director.state.episode_store as episode_module
from npc_director.contracts import TurnStatus
from npc_director.contracts.content import ContentFact, NarrativeScopeDecision
from npc_director.contracts.episodes import KnowledgeClaim
from npc_director.contracts.planning import (
    DialogueStateDelta,
    ExecutionTrace,
    TurnAnalysis,
    TurnGoal,
)
from npc_director.governance.content_review import ContentReviewError
from npc_director.state.content_store import ContentQuotaError, ContentStore
from npc_director.state.episode_store import EpisodeStore
from tests.test_content_review import policy, publish, reviewed
from tests.test_episode_service import Adapter, complete, make_service, request


@pytest.fixture
def clock(monkeypatch):
    now = [datetime.now(UTC)]
    monkeypatch.setattr(content_module, "utc_now", lambda: now[0])
    monkeypatch.setattr(episode_module, "utc_now", lambda: now[0])
    return now


def temporary_content(deadline, *, kind="fact", statement="北门临时关闭", **changes):
    return reviewed(
        content_kind=kind,
        scope=NarrativeScopeDecision(scope="action"),
        key="temporary-gate-status",
        summary=statement,
        facts=[ContentFact(fact_key="gate-status", statement=statement)],
        visibility="public",
        expires_at=deadline,
        **changes,
    )


def test_knowledge_expiry_rejects_naive_time_and_accepts_an_explicit_offset():
    with pytest.raises(ValidationError, match="knowledge expiry must include its timezone"):
        KnowledgeClaim(content_id="gate-status", expires_at="2030-01-01T12:00:00")
    claim = KnowledgeClaim(content_id="gate-status", expires_at="2030-01-01T12:00:00+08:00")
    assert claim.expires_at == datetime(2030, 1, 1, 4, tzinfo=UTC)


@pytest.mark.parametrize("kind", ["fact", "event", "background"])
def test_expiry_filters_content_and_npc_knowledge_at_the_boundary(tmp_path, clock, kind):
    store = ContentStore(tmp_path / "state.db")
    knowledge = EpisodeStore(store.database)
    deadline = clock[0] + timedelta(hours=1)
    staged = store.stage_reviewed(
        "game-a", "episode-1", "turn-1", "mechanic", temporary_content(deadline, kind=kind)
    )
    publish(store)
    for npc_id in ("mechanic", "other"):
        knowledge.grant_knowledge(
            "game-a",
            npc_id,
            KnowledgeClaim(
                content_id=staged.content_id,
                text="北门临时关闭",
                shareable=True,
                expires_at=deadline,
            ),
            source_event_id="heard-gate-status",
        )
    clock[0] = deadline - timedelta(microseconds=1)
    assert store.get_published_facts("game-a")
    assert store.visible_context("game-a", "mechanic")
    assert store.visible_context("game-a", "other", known_content_ids=[staged.content_id])
    assert knowledge.get_context("game-a", "other")["knowledge"]

    clock[0] = deadline
    assert store.list_published("game-a") == []
    assert store.get_published_facts("game-a") == []
    assert store.visible_context("game-a", "mechanic") == []
    assert store.visible_context("game-a", "other", known_content_ids=[staged.content_id]) == []
    assert knowledge.get_context("game-a", "mechanic")["knowledge"] == []
    assert knowledge.get_context("game-a", "other")["knowledge"] == []


@pytest.mark.parametrize("was_published", [False, True])
def test_expired_temporary_goal_can_be_replaced_without_using_quest_quota(
    tmp_path, clock, was_published
):
    store = ContentStore(tmp_path / "state.db")
    deadline = clock[0] + timedelta(hours=1)
    old = store.stage_reviewed(
        "game-a", "episode-1", "turn-1", "mechanic", temporary_content(deadline)
    )
    if was_published:
        publish(store)
    clock[0] = deadline
    replacement = store.stage_reviewed(
        "game-a",
        "episode-1",
        "turn-2",
        "mechanic",
        temporary_content(deadline + timedelta(hours=1), statement="北门已经重新开放"),
    )
    assert replacement.content_id != old.content_id
    assert store.get_staged_for_turn("game-a", "turn-1") == []
    assert store.list_published("game-a") == []
    assert store.quota_usage("game-a", "episode-1") == {"reserved": 0, "consumed": 0}
    publish(store, turn_id="turn-2")
    assert [fact.statement for fact in store.get_published_facts("game-a")] == ["北门已经重新开放"]

    store.stage_reviewed("game-a", "episode-1", "quest-turn", "mechanic", reviewed())
    publish(store, turn_id="quest-turn")
    clock[0] = deadline + timedelta(hours=2)
    assert store.get_published_facts("game-a") == []
    assert len(store.list_quests("game-a")) == 1
    assert store.quota_usage("game-a", "episode-1") == {"reserved": 0, "consumed": 1}
    with pytest.raises(ContentQuotaError):
        store.stage_reviewed(
            "game-a", "episode-1", "another-quest", "mechanic", reviewed(key="another-goal")
        )


def test_expiry_at_publication_rolls_back_the_turn_and_reserved_quota_can_be_reused(
    tmp_path, clock
):
    store = ContentStore(tmp_path / "state.db")
    deadline = clock[0] + timedelta(hours=1)
    store.stage_reviewed(
        "game-a", "episode-1", "turn-1", "mechanic", temporary_content(deadline)
    )
    store.stage_reviewed("game-a", "episode-1", "turn-1", "mechanic", reviewed())
    clock[0] = deadline
    with pytest.raises(ContentReviewError, match="expired before delivery"):
        publish(store)
    assert store.list_published("game-a") == []
    assert store.list_quests("game-a") == []
    assert len(store.get_staged_for_turn("game-a", "turn-1")) == 2
    assert store.quota_usage("game-a", "episode-1") == {"reserved": 1, "consumed": 0}

    assert store.discard_turn("game-a", "turn-1") == 2
    assert store.quota_usage("game-a", "episode-1") == {"reserved": 0, "consumed": 0}
    store.stage_reviewed("game-a", "episode-1", "turn-2", "mechanic", reviewed())
    publish(store, turn_id="turn-2")
    assert len(store.list_quests("game-a")) == 1
    assert store.quota_usage("game-a", "episode-1") == {"reserved": 0, "consumed": 1}


@pytest.mark.parametrize("epistemic_status", ["world_fact", "belief", "claim"])
@pytest.mark.asyncio
async def test_published_summary_cannot_prove_commitment_completion(tmp_path, epistemic_status):
    service, fixture = make_service(tmp_path)
    adapter = Adapter()
    staged = []

    class PublishingExecutor:
        async def generate(self, source, *, repair_feedback=None):
            result = await fixture.generate(source)
            if not staged:
                content = reviewed(
                    content_kind="fact",
                    scope=NarrativeScopeDecision(scope="action"),
                    summary="记录核对已完成。",
                    facts=[
                        ContentFact(
                            fact_key="record-claim",
                            statement="有人说记录已经核对。",
                            epistemic_status=epistemic_status,
                            source_npc_id=source.npc_id,
                            deceptive=epistemic_status == "claim",
                            persona_basis="不愿承认疏忽",
                            motive="拖延真正的核对",
                        )
                    ],
                    visibility="public",
                    content_policy=policy(session_id=source.session_id).model_copy(
                        update={"npc_id": source.npc_id}
                    ),
                )
                staged.append(
                    service.episodes.content_store.stage_reviewed(
                        source.session_id, source.episode_id, source.turn_id, source.npc_id, content
                    )
                )
                result.content_candidates = list(staged)
            else:
                result.execution_trace = ExecutionTrace(
                    analysis=TurnAnalysis(
                        intent="lore_question",
                        objective="回应核对进度",
                        goals=[
                            TurnGoal(
                                id="check-records",
                                description="核对记录",
                                completion_basis="observed_event",
                                evidence_refs=[staged[0].content_id],
                            )
                        ],
                    )
                )
                result.dialogue_state_delta = DialogueStateDelta(
                    resolved_commitments=["核对记录后再回复"]
                )
            return result

    service.executor = PublishingExecutor()
    first = await service.run_turn(request(), adapter=adapter)
    assert first.status is TurnStatus.READY_TO_EMIT
    await complete(service, adapter.directives[-1])
    known = service.episodes.store.get_context("session-v2", "elder_maren")["knowledge"]
    assert len(known) == 1
    assert known[0]["content_id"] == staged[0].content_id
    assert known[0]["epistemic_status"] == "reported"
    assert known[0]["source_npc_id"] == "elder_maren"
    assert service.episodes.store.get_context("session-v2", "village_guard")["knowledge"] == []
    facts = service.episodes.content_store.get_published_facts("session-v2")
    assert len(facts) == (1 if epistemic_status == "world_fact" else 0)

    second = await service.run_turn(request(turn="follow-up"), adapter=adapter)
    assert second.status is TurnStatus.READY_TO_EMIT
    await complete(service, adapter.directives[-1])
    state = service.episodes.store.get_context("session-v2", "elder_maren")["dialogue_state"]
    assert state["commitments"][0]["status"] == "open"
