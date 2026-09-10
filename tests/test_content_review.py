from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

import pytest
from pydantic import ValidationError

from npc_director.agents.content_author import build_content_author_agent
from npc_director.agents.content_reviewer import build_content_reviewer_agent
from npc_director.config import Settings
from npc_director.contracts.content import (
    ContentCandidate,
    ContentFact,
    ContentNeed,
    ContentPolicy,
    ContentReview,
    ExistingQuest,
    NarrativeScopeDecision,
    ObjectiveRef,
    ObjectiveStep,
)
from npc_director.governance.content_review import (
    ContentReviewError,
    should_author_content,
    validate_content_review,
)
from npc_director.state.content_store import (
    ContentQuotaError,
    ContentStore,
    DuplicateContentError,
)
from npc_director.state.errors import IdempotencyConflictError

PARENT = ObjectiveRef(objective_id="repair-generator", quest_id="repair", version=2)


def policy(**changes):
    return ContentPolicy(
        session_id=changes.pop("session_id", "game-a"),
        npc_id="mechanic",
        allowed_kinds=["quest", "event", "background", "fact"],
        allowed_actions=["take", "inspect", "return", "ask"],
        allowed_reward_types=["relationship"],
        objective_refs=changes.pop("objective_refs", [PARENT]),
        **changes,
    )


def independent_scope(**changes):
    return NarrativeScopeDecision(
        scope="side_quest",
        independent_goal="让失踪者的妹妹决定遗物的归属",
        character_motivation="妹妹担心兄长已被遗忘，希望知道遗物的来历",
        completion_condition="玩家询问妹妹意愿，并选择归还或保留遗物",
        meaningful_outcomes=["归还使妹妹获得慰藉", "保留则失去她的信任"],
        can_decline=True,
        merge_insufficient_reason="独立人物关系与维修目标无关，放弃不妨碍维修",
        **changes,
    )


def candidate_bundle(*, scope=None, content_kind="quest", key="return-keepsake", **changes):
    scope = scope or independent_scope()
    need = ContentNeed(
        need_id="need-" + key,
        purpose="为当前处境中成立的人物目标补充所需内容",
        content_kind=content_kind,
        scope=scope,
        motivation=scope.character_motivation,
        reuse_checked=True,
        allowed_kinds=[content_kind],
    )
    candidate = ContentCandidate(
        candidate_id="candidate-" + key,
        need_id=need.need_id,
        content_kind=content_kind,
        scope=scope,
        title="遗物的归属",
        summary=changes.pop("summary", "妹妹就在同一房间，玩家可以选择是否归还兄长的遗物。"),
        objective_key=key,
        **changes,
    )
    review = ContentReview(
        candidate_id=candidate.candidate_id,
        action="approve",
        setting_consistent=True,
        persona_consistent=True,
        meaningful=True,
    )
    return need, candidate, review


def reviewed(*, key="return-keepsake", content_policy=None, **changes):
    return validate_content_review(
        *candidate_bundle(key=key, **changes),
        content_policy or policy(),
    )


def publish(store, turn_id="turn-1", session_id="game-a", **kwargs):
    with store.transaction() as connection:
        return store.publish_turn_in_connection(connection, session_id, turn_id, **kwargs)


@pytest.mark.parametrize(
    "purpose,scope",
    [
        ("取5米外已有的扳手继续维修", "action"),
        ("到远处取保险丝，需要借钥匙并换乘两次", "step"),
        ("根据已有守卫排班选择潜入或谈判路线", "task_event"),
    ],
)
def test_existing_actions_and_branches_never_need_an_author(purpose, scope):
    need = ContentNeed(
        need_id="existing-content",
        purpose=purpose,
        content_kind="event",
        scope=NarrativeScopeDecision(scope=scope, parent_objective=PARENT),
        reuse_checked=True,
        existing_content_sufficient=True,
        allowed_kinds=["event"],
    )
    assert not should_author_content(need, policy())


def test_reuse_check_and_server_permission_precede_author():
    need, _, _ = candidate_bundle()
    assert should_author_content(need, policy())
    assert not should_author_content(need.model_copy(update={"reuse_checked": False}), policy())
    assert not should_author_content(need, policy().model_copy(update={"allowed_kinds": []}))


def test_new_encounter_is_published_as_parent_event_not_a_quest(tmp_path):
    scope = NarrativeScopeDecision(
        scope="task_event",
        parent_objective=PARENT,
        reason="阻塞维修路线的小事件",
    )
    content = reviewed(scope=scope, content_kind="event", key="maintenance-encounter")
    assert len(content.candidate.events) == 1
    assert content.candidate.events[0].objective == PARENT
    store = ContentStore(tmp_path / "content.db")
    store.register_objective("game-a", PARENT)
    staged = store.stage_reviewed("game-a", "episode-1", "turn-1", "mechanic", content)
    assert staged.quest_id is None and staged.allowed_state_paths == []
    publish(store)
    assert store.list_quests("game-a") == []
    assert store.quota_usage("game-a", "episode-1") == {"reserved": 0, "consumed": 0}


def test_meaningful_same_room_quest_is_allowed_and_starts_only_as_offered(tmp_path):
    store = ContentStore(tmp_path / "content.db")
    staged = store.stage_reviewed("game-a", "episode-1", "turn-1", "mechanic", reviewed())
    assert staged.allowed_state_paths == [f"quests.{staged.quest_id}.status"]
    assert staged.proposed_state_changes.quests[0].status == "offered"
    assert not store.list_quests("game-a")
    publish(store)
    assert store.list_quests("game-a")[0].status == "offered"
    with pytest.raises(ContentReviewError, match="invalid quest transition"):
        store.advance_quest("game-a", staged.quest_id, "bad-complete", "completed")
    accepted = store.advance_quest("game-a", staged.quest_id, "accept", "accepted")
    assert accepted.version == 1
    assert store.advance_quest("game-a", staged.quest_id, "accept", "accepted") == accepted
    completed = store.advance_quest("game-a", staged.quest_id, "complete", "completed")
    assert completed.status == "completed" and completed.version == 2


def test_parent_prerequisite_cannot_be_an_extra_side_quest():
    scope = independent_scope(necessary_for_parent=True, parent_objective=PARENT)
    with pytest.raises(ContentReviewError, match="prerequisite"):
        reviewed(scope=scope, summary="5米外拿取扳手是维修的必要前提")


@pytest.mark.parametrize(
    "missing_field",
    [
        "independent_goal",
        "character_motivation",
        "completion_condition",
        "merge_insufficient_reason",
    ],
)
def test_labels_rewards_and_length_cannot_replace_independent_value(missing_field):
    scope = independent_scope().model_copy(update={missing_field: ""})
    with pytest.raises(ContentReviewError, match=missing_field):
        reviewed(scope=scope, reward_types=["relationship"])


def test_duplicate_quest_merges_into_existing_target_and_strips_quest_rewards(tmp_path):
    existing = ExistingQuest(ref=PARENT, objective_key="return-keepsake", summary="已有寻物任务")
    content_policy = policy(existing_quests=[existing])
    need, candidate, review = candidate_bundle(reward_types=["relationship"])
    with pytest.raises(ContentReviewError, match="already covers"):
        validate_content_review(need, candidate, review, content_policy)
    final_scope = NarrativeScopeDecision(scope="task_event", parent_objective=PARENT)
    review = review.model_copy(
        update={
            "action": "merge",
            "final_scope": final_scope,
            "merge_into": PARENT,
        }
    )
    result = validate_content_review(need, candidate, review, content_policy)
    assert result.candidate.content_kind == "event"
    assert result.candidate.reward_types == []
    assert result.candidate.events[0].objective == PARENT
    store = ContentStore(tmp_path / "content.db")
    store.register_objective("game-a", PARENT)
    staged = store.stage_reviewed("game-a", "episode-1", "turn-1", "mechanic", result)
    assert staged.quest_id is None and staged.proposed_state_changes.quests == []


def test_reviewer_can_attach_a_small_errand_without_publishing_a_new_quest():
    need, candidate, review = candidate_bundle(summary="取旁边的扳手")
    scope = NarrativeScopeDecision(scope="step", parent_objective=PARENT)
    review = review.model_copy(update={"action": "attach", "final_scope": scope})
    result = validate_content_review(need, candidate, review, policy())
    assert result.candidate.scope.scope == "step"
    assert result.candidate.steps[0].description == "取旁边的扳手"


def test_unmotivated_revenge_story_is_rejected_by_independent_review():
    need, candidate, review = candidate_bundle(summary="机械师突然要求玩家替他复仇")
    review = review.model_copy(
        update={
            "action": "reject",
            "persona_consistent": False,
            "reasons": ["机械师没有复仇动机，维修委托不支持这一突转"],
        }
    )
    with pytest.raises(ContentReviewError, match="not approved"):
        validate_content_review(need, candidate, review, policy())


@pytest.mark.parametrize("kind", ["background", "fact"])
def test_backgrounds_and_temporary_facts_do_not_become_quests(tmp_path, kind):
    content = reviewed(
        content_kind=kind,
        scope=NarrativeScopeDecision(scope="action"),
        key="mechanic-childhood",
        facts=[ContentFact(fact_key="old_workshop", statement="他年少时在河边工坊学艺")],
    )
    store = ContentStore(tmp_path / "content.db")
    staged = store.stage_reviewed("game-a", "episode-1", "turn-1", "mechanic", content)
    assert staged.quest_id is None
    assert store.list_published("game-a") == []
    publish(store)
    assert store.list_quests("game-a") == []
    assert len(store.get_published_facts("game-a")) == 1


def test_staging_and_completed_transaction_are_idempotent(tmp_path):
    store = ContentStore(tmp_path / "content.db")
    first = store.stage_reviewed("game-a", "episode-1", "turn-1", "mechanic", reviewed())
    repeat = store.stage_reviewed("game-a", "episode-1", "turn-1", "mechanic", reviewed())
    assert first == repeat
    assert store.quota_usage("game-a", "episode-1")["reserved"] == 1
    publish(store)
    assert publish(store) == []
    assert len(store.list_quests("game-a")) == 1
    assert store.quota_usage("game-a", "episode-1") == {"reserved": 0, "consumed": 1}


def test_new_quest_quota_is_atomic_under_parallel_review(tmp_path):
    store = ContentStore(tmp_path / "content.db")

    def stage(index):
        try:
            return store.stage_reviewed(
                "game-a",
                "episode-1",
                f"turn-{index}",
                "mechanic",
                reviewed(key=f"independent-story-{index}"),
            )
        except ContentQuotaError:
            return None

    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(stage, range(4)))
    assert sum(result is not None for result in results) == 1
    assert store.quota_usage("game-a", "episode-1")["reserved"] == 1


def test_same_goal_across_candidates_is_deduplicated(tmp_path):
    store = ContentStore(tmp_path / "content.db")
    original = store.stage_reviewed("game-a", "episode-1", "turn-1", "mechanic", reviewed())
    with pytest.raises(DuplicateContentError) as caught:
        store.stage_reviewed(
            "game-a",
            "episode-2",
            "turn-2",
            "mechanic",
            reviewed(key="RETURN keepsake"),
        )
    assert caught.value.existing.content_id == original.content_id


def test_interrupted_turn_releases_reserved_quota_and_never_publishes(tmp_path):
    store = ContentStore(tmp_path / "content.db")
    store.stage_reviewed("game-a", "episode-1", "turn-1", "mechanic", reviewed())
    assert store.discard_turn("game-a", "turn-1") == 1
    assert store.discard_turn("game-a", "turn-1") == 0
    assert publish(store) == []
    assert store.list_published("game-a") == []
    assert store.quota_usage("game-a", "episode-1")["reserved"] == 0
    with pytest.raises(ContentReviewError, match="resurrected"):
        store.stage_reviewed("game-a", "episode-1", "turn-1", "mechanic", reviewed())
    store.stage_reviewed("game-a", "episode-1", "turn-2", "mechanic", reviewed())


def test_publication_rolls_back_with_parent_transaction(tmp_path):
    store = ContentStore(tmp_path / "content.db")
    store.stage_reviewed("game-a", "episode-1", "turn-1", "mechanic", reviewed())
    with (
        pytest.raises(RuntimeError, match="later commit failed"),
        store.transaction() as connection,
    ):
        store.publish_turn_in_connection(connection, "game-a", "turn-1")
        assert connection.execute("SELECT COUNT(*) FROM narrative_quests").fetchone()[0] == 1
        raise RuntimeError("later commit failed")
    assert store.list_quests("game-a") == []
    assert len(store.get_staged_for_turn("game-a", "turn-1")) == 1
    assert store.quota_usage("game-a", "episode-1")["reserved"] == 1
    publish(store)
    assert len(store.list_quests("game-a")) == 1


def test_stale_parent_reference_blocks_stage_and_completion(tmp_path):
    store = ContentStore(tmp_path / "content.db")
    scope = NarrativeScopeDecision(scope="task_event", parent_objective=PARENT)
    content = reviewed(scope=scope, content_kind="event")
    store.register_objective("game-a", PARENT)
    store.stage_reviewed("game-a", "episode-1", "turn-1", "mechanic", content)
    newer = PARENT.model_copy(update={"version": 3})
    store.register_objective("game-a", newer)
    with pytest.raises(ContentReviewError, match="stale parent"):
        publish(store)
    assert store.list_published("game-a") == []
    with pytest.raises(ContentReviewError, match="stale objective"):
        store.register_objective("game-a", PARENT)


def test_no_cross_instance_visibility_or_quota_leakage(tmp_path):
    store = ContentStore(tmp_path / "content.db")
    store.stage_reviewed("game-a", "episode-1", "turn-1", "mechanic", reviewed())
    other = reviewed(content_policy=policy(session_id="game-b"))
    store.stage_reviewed("game-b", "episode-1", "turn-1", "mechanic", other)
    publish(store)
    assert store.list_published("game-b") == []
    assert len(store.get_staged_for_turn("game-b", "turn-1")) == 1
    with pytest.raises(ContentReviewError, match="another instance"):
        store.stage_reviewed("game-b", "episode-2", "turn-2", "mechanic", reviewed())


def test_publication_does_not_automatically_grant_other_npcs_knowledge(tmp_path):
    store = ContentStore(tmp_path / "content.db")
    staged = store.stage_reviewed(
        "game-a",
        "episode-1",
        "turn-1",
        "mechanic",
        reviewed(visibility="public"),
    )
    publish(store)
    assert store.visible_context("game-a", "other") == []
    known = store.visible_context("game-a", "other", known_content_ids=[staged.content_id])
    assert len(known) == 1 and "reviewed" not in known[0]
    assert store.visible_context("game-b", "other", known_content_ids=[staged.content_id]) == []


def test_deception_is_sourced_claim_and_never_becomes_world_fact(tmp_path):
    with pytest.raises(ValidationError, match="deception requires"):
        ContentFact(fact_key="key", statement="我从未拿过钥匙", deceptive=True)
    claim = ContentFact(
        fact_key="key",
        statement="我从未拿过钥匙",
        epistemic_status="claim",
        source_npc_id="mechanic",
        deceptive=True,
        persona_basis="怕担责",
        motive="拖延调查",
    )
    content = reviewed(
        content_kind="fact",
        scope=NarrativeScopeDecision(scope="action"),
        facts=[claim],
        visibility="public",
    )
    store = ContentStore(tmp_path / "content.db")
    staged = store.stage_reviewed("game-a", "episode-1", "turn-1", "mechanic", content)
    publish(store)
    assert store.get_published_facts("game-a") == []
    visible = store.visible_context("game-a", "other", known_content_ids=[staged.content_id])
    received = visible[0]["facts"][0]
    assert received["epistemic_status"] == "claim" and received["source_npc_id"] == "mechanic"
    assert "deceptive" not in received and "motive" not in received


def test_canonical_facts_capabilities_and_post_review_tampering_are_blocked(tmp_path):
    fixed = ContentFact(fact_key="engine", statement="引擎停机")
    with pytest.raises(ContentReviewError, match="canonical fact"):
        reviewed(
            facts=[ContentFact(fact_key="engine", statement="引擎已启动")],
            content_policy=policy(canonical_facts=[fixed]),
        )
    with pytest.raises(ContentReviewError, match="unregistered action"):
        reviewed(required_actions=["spawn_gold"])
    with pytest.raises(ContentReviewError, match="unregistered reward"):
        reviewed(reward_types=["unlimited_money"])
    store = ContentStore(tmp_path / "content.db")
    content = reviewed()
    content.candidate.summary = "审核后偷偷改变的剧情"
    with pytest.raises(ContentReviewError, match="changed after review"):
        store.stage_reviewed("game-a", "episode-1", "turn-1", "mechanic", content)


def test_freezing_policy_is_idempotent_and_prevents_completion_under_new_authority(tmp_path):
    store = ContentStore(tmp_path / "content.db")
    store.stage_reviewed("game-a", "episode-1", "turn-1", "mechanic", reviewed())
    store.freeze_turn_policy("game-a", "turn-1", "final-policy")
    store.freeze_turn_policy("game-a", "turn-1", "final-policy")
    with pytest.raises(ContentReviewError, match="already frozen"):
        store.freeze_turn_policy("game-a", "turn-1", "expanded-policy")
    with pytest.raises(ContentReviewError, match="completion policy"):
        publish(store, expected_policy_digest="expanded-policy")
    assert store.list_published("game-a") == []
    publish(store, expected_policy_digest="final-policy")


def test_cyclic_or_unregistered_nested_actions_cannot_enter_published_content():
    ref = ObjectiveRef(objective_id="candidate-return-keepsake")
    steps = [
        ObjectiveStep(
            step_id="a",
            objective=ref,
            description="循环依赖",
            depends_on=["a"],
        )
    ]
    with pytest.raises(ContentReviewError, match="cycle"):
        reviewed(steps=steps)


def test_new_quest_steps_receive_runtime_refs_before_writer(tmp_path):
    ref = ObjectiveRef(objective_id="candidate-return-keepsake")
    content = reviewed(
        steps=[
            ObjectiveStep(
                step_id="ask-sister",
                objective=ref,
                description="询问妹妹意愿",
                action="ask",
            )
        ]
    )
    store = ContentStore(tmp_path / "content.db")
    staged = store.stage_reviewed("game-a", "episode-1", "turn-1", "mechanic", content)
    assert staged.candidate.steps[0].objective.quest_id == staged.quest_id
    assert staged.reviewed.submitted_candidate.steps[0].objective == ref
    publish(store)


def test_new_side_quest_cannot_write_steps_into_a_different_quest():
    with pytest.raises(ContentReviewError, match="own runtime-assigned objective"):
        reviewed(
            steps=[
                ObjectiveStep(
                    step_id="wrong-parent",
                    objective=PARENT,
                    description="悄悄改变维修任务",
                )
            ]
        )


def test_replayed_candidate_cannot_change_payload(tmp_path):
    store = ContentStore(tmp_path / "content.db")
    store.stage_reviewed("game-a", "episode-1", "turn-1", "mechanic", reviewed())
    with pytest.raises(IdempotencyConflictError):
        store.stage_reviewed(
            "game-a",
            "episode-1",
            "turn-1",
            "mechanic",
            reviewed(summary="不一致的新结果"),
        )


def test_content_agents_reuse_role_models_and_structured_output():
    settings = Settings(narrative_model="author-model", judge_model="reviewer-model")
    author = build_content_author_agent(settings)
    reviewer = build_content_reviewer_agent(settings)
    assert author.name != reviewer.name
    assert author.model == "author-model" and reviewer.model == "reviewer-model"
    assert author.output_type is ContentCandidate and reviewer.output_type is ContentReview
