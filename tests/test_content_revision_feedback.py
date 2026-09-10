"""Repair regressions captured before the bounded reviewer feedback channel existed."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from npc_director.contracts.content import (
    ContentCandidate,
    ContentNeed,
    ContentPolicy,
    ContentReview,
    ContentRevisionEdit,
)
from npc_director.contracts.planning import TurnAnalysis
from npc_director.governance.content_review import (
    ContentReviewError,
    build_content_revision_feedback,
    validate_content_review,
)

CAPTURED = json.loads(
    (Path(__file__).parent / "fixtures" / "content_revision_failures.json").read_text()
)["cases"]
SECRET = "PRIVATE_REVIEW_CANON_ONLY_8247"


def captured_bundle(case_id):
    captured = CAPTURED[case_id]
    candidate = ContentCandidate.model_validate(captured["candidate"])
    need = ContentNeed(
        need_id=candidate.need_id,
        purpose="补充明确空缺的任务定义或父任务遭遇",
        content_kind=candidate.content_kind,
        scope=candidate.scope,
        reuse_checked=True,
        allowed_kinds=[candidate.content_kind],
    )
    policy = ContentPolicy(
        session_id="feedback-regression",
        npc_id="elder_maren",
        allowed_kinds=["quest", "event"],
        allowed_actions=["dialogue", "npc_message", "quest_transition"],
        allowed_reward_types=["relationship"],
        objective_refs=[candidate.scope.parent_objective]
        if candidate.scope.parent_objective
        else [],
    )
    review = ContentReview.model_validate(captured["review"])
    return need, candidate, review, policy


def targeted_review(case_id, review):
    # These are the new v2 schema signals for the original captured problems;
    # the fixture itself remains an unchanged record of the failed live run.
    if case_id == "meaningful_short_quest":
        edits = [
            ContentRevisionEdit(
                code="limit_to_supported_effects",
                field_paths=[
                    "/scope/independent_goal",
                    "/scope/completion_condition",
                    "/scope/meaningful_outcomes/0",
                    "/steps/0/description",
                    "/steps/0/completion_condition",
                ],
            )
        ]
    else:
        edits = [
            ContentRevisionEdit(
                code="ground_in_author_context",
                field_paths=["/summary", "/events/0/description", "/steps/0/description"],
            ),
            ContentRevisionEdit(
                code="limit_to_supported_effects",
                field_paths=["/steps/1", "/events/0/consequences", "/required_actions/1"],
            ),
        ]
    return review.model_copy(update={"revision_edits": edits})


def repaired_candidate(case_id, candidate):
    repaired = candidate.model_copy(deep=True)
    repaired.required_actions = ["dialogue"]
    if case_id == "meaningful_short_quest":
        repaired.scope.independent_goal = "确认家属是否愿意接收旧信，并尊重其决定。"
        repaired.scope.completion_condition = (
            "家属明确表达愿意接收或拒绝；仅记录意愿，拒绝后停止询问。"
        )
        repaired.scope.meaningful_outcomes = [
            "确认家属接收意愿，后续安排另行处理。",
            "家属拒绝时尊重边界并结束询问。",
        ]
        repaired.summary = "玛伦请求玩家确认家属是否愿意接收旧信；拒绝后立即结束询问。"
        repaired.steps[0].description = repaired.scope.independent_goal
        repaired.steps[0].completion_condition = repaired.scope.completion_condition
    else:
        repaired.scope.independent_goal = "护送途中核实方向信息。"
        repaired.scope.completion_condition = "完成问路交谈，说明已确认与仍待核实的信息。"
        repaired.scope.meaningful_outcomes = ["获得方向线索。", "信息不足时选择继续核实。"]
        repaired.summary = "护送途中可以询问方向；根据所得信息决定是否继续核实。"
        repaired.steps = repaired.steps[:1]
        repaired.steps[0].description = "向路人询问方向，不预设存在已登记的路线选择。"
        repaired.steps[0].completion_condition = repaired.scope.completion_condition
        repaired.events[0].description = repaired.summary
        repaired.events[0].choices = ["询问方向。", "信息不足时继续核实。"]
        repaired.events[0].consequences = ["只记录方向信息，不改变护送路线状态。"]
    return repaired


@pytest.mark.parametrize("case_id", CAPTURED)
def test_captured_retry_repeated_the_completion_problem(case_id):
    captured = CAPTURED[case_id]
    assert captured["review"]["action"] == captured["retry_review"]["action"] == "revise"
    assert (
        captured["candidate"]["scope"]["completion_condition"]
        == captured["retry_candidate"]["scope"]["completion_condition"]
    )
    need, candidate, review, policy = captured_bundle(case_id)
    review = targeted_review(case_id, review)
    feedback = build_content_revision_feedback(need, candidate, review, policy)
    for edit in review.revision_edits:
        assert f"[{edit.code}]" in feedback
        assert all(path in feedback for path in edit.field_paths)
    assert review.revision_instructions not in feedback
    assert "quest_transition不授权新路线" in feedback
    assert "接受意愿与实际接收分开" in feedback


def test_free_text_review_and_private_replacement_scope_never_enter_feedback():
    need, candidate, review, policy = captured_bundle("meaningful_short_quest")
    review = targeted_review("meaningful_short_quest", review).model_copy(
        update={
            "reasons": [SECRET],
            "revision_instructions": f"请把结果改成{SECRET}",
            "final_scope": candidate.scope.model_copy(update={"reason": SECRET}),
        }
    )
    feedback = build_content_revision_feedback(need, candidate, review, policy)
    assert SECRET not in feedback
    assert "[limit_to_supported_effects]" in feedback
    assert "/scope/completion_condition" in feedback


@pytest.mark.parametrize(
    "invalid_path",
    [
        f"/policy/canonical_facts/{SECRET}",
        f"/scope/{SECRET}",
        f"/summary\n{SECRET}",
        "/steps/99/description",
        "/steps/-1/description",
        "/steps/00/description",
        "/steps/0/description/extra",
        "/steps/0/action",  # Not a narrative field for ground_in_author_context.
        "/facts/0/statement",  # This captured candidate has no facts.
        "/summary~1private",
    ],
)
def test_feedback_discards_paths_outside_the_candidate_or_edit_kind(invalid_path):
    need, candidate, review, policy = captured_bundle("meaningful_short_quest")
    review = review.model_copy(
        update={
            "revision_edits": [
                ContentRevisionEdit(
                    code="ground_in_author_context",
                    field_paths=[invalid_path, "/summary"],
                ),
            ],
        }
    )
    feedback = build_content_revision_feedback(need, candidate, review, policy)
    assert "[ground_in_author_context] /summary：" in feedback
    assert invalid_path not in feedback
    assert SECRET not in feedback


def test_revision_schema_cannot_carry_arbitrary_codes_or_replacement_text():
    with pytest.raises(ValidationError):
        ContentRevisionEdit(code=SECRET, field_paths=["/summary"])
    with pytest.raises(ValidationError):
        ContentRevisionEdit.model_validate(
            {
                "code": "ground_in_author_context",
                "field_paths": ["/summary"],
                "replacement": SECRET,
            }
        )


def test_review_for_another_candidate_does_not_supply_repair_directives():
    need, candidate, review, policy = captured_bundle("meaningful_short_quest")
    review = targeted_review("meaningful_short_quest", review).model_copy(
        update={"candidate_id": "unrelated-candidate"}
    )
    feedback = build_content_revision_feedback(need, candidate, review, policy)
    assert "[limit_to_supported_effects]" not in feedback


def test_false_capability_complaint_cannot_override_the_public_policy():
    need, candidate, review, policy = captured_bundle("meaningful_short_quest")
    # Captured reviewers incorrectly alternated between treating dialogue as
    # valid and requiring npc_message. Both are explicitly allowed here.
    review = review.model_copy(
        update={
            "revision_instructions": "dialogue不合法，请改成SECRET_ACTION",
            "revision_edits": [
                ContentRevisionEdit(
                    code="use_allowed_actions", field_paths=["/steps/0/action"]
                ),
            ],
        }
    )
    feedback = build_content_revision_feedback(need, candidate, review, policy)
    assert "[use_allowed_actions]" not in feedback
    assert "SECRET_ACTION" not in feedback


def test_public_interface_errors_are_repaired_even_when_reviewer_misses_them():
    need, candidate, review, policy = captured_bundle("meaningful_short_quest")
    candidate = candidate.model_copy(deep=True)
    candidate.required_actions = ["invented_action"]
    candidate.steps[0].action = "invented_action"
    candidate.reward_types = ["invented_reward"]
    candidate.source_refs = ["invented_source"]
    candidate.need_id = "wrong-need"
    review = review.model_copy(update={"action": "approve", "revision_instructions": SECRET})
    feedback = build_content_revision_feedback(need, candidate, review, policy)
    assert "[align_requested_scope] /need_id：" in feedback
    assert "[use_allowed_actions] /required_actions/0, /steps/0/action：" in feedback
    assert "[use_allowed_rewards] /reward_types/0：" in feedback
    assert "[use_available_sources] /source_refs/0：" in feedback
    assert "invented_" not in feedback
    assert SECRET not in feedback


@pytest.mark.parametrize("case_id", CAPTURED)
def test_feedback_does_not_approve_content_or_weaken_side_quest_criteria(case_id):
    need, candidate, review, policy = captured_bundle(case_id)
    review = targeted_review(case_id, review)
    revised = repaired_candidate(case_id, candidate)
    with pytest.raises(ContentReviewError, match="not approved"):
        validate_content_review(need, revised, review, policy)
    approval = review.model_copy(update={"action": "approve", "revision_edits": []})
    admitted = validate_content_review(need, revised, approval, policy)
    assert admitted.candidate.scope.scope == candidate.scope.scope
    if case_id == "meaningful_short_quest":
        revised.scope.can_decline = False
        with pytest.raises(ContentReviewError, match="independently declinable"):
            validate_content_review(need, revised, approval, policy)


@pytest.mark.asyncio
@pytest.mark.parametrize("case_id", CAPTURED)
async def test_targeted_feedback_reaches_author_and_revised_content_is_reviewed_before_staging(
    case_id, tmp_path, monkeypatch
):
    import npc_director.agents.content_author as author_module
    import npc_director.agents.content_reviewer as reviewer_module
    from npc_director.state.content_store import ContentStore
    from tests.test_bounded_executor import WRITER, director_input
    from tests.test_dynamic_planning import make_executor, successful_outputs

    need, candidate, review, policy = captured_bundle(case_id)
    review = targeted_review(case_id, review).model_copy(
        update={"reasons": [SECRET], "revision_instructions": SECRET}
    )
    revised = repaired_candidate(case_id, candidate)
    approval = review.model_copy(
        update={"action": "approve", "revision_edits": [], "revision_instructions": ""}
    )
    author, reviewer = object(), object()
    monkeypatch.setattr(author_module, "build_content_author_agent", lambda _: author)
    monkeypatch.setattr(reviewer_module, "build_content_reviewer_agent", lambda _: reviewer)
    outputs = successful_outputs(
        TurnAnalysis(intent="other", objective=need.purpose, content_need=need, confidence=1)
    )
    outputs.update({author: [candidate, revised], reviewer: [review, approval]})
    executor, calls = make_executor(outputs)
    executor.content_store = ContentStore(tmp_path / "content.sqlite")
    executor.review_context_provider = lambda _: {
        "canonical_facts": [{"fact_key": "private-truth", "statement": SECRET}],
    }
    source = director_input()
    policy = policy.model_copy(update={"npc_id": source.npc_id, "session_id": source.session_id})
    for ref in policy.objective_refs:
        executor.content_store.register_objective(source.session_id, ref)
    source = source.model_copy(update={"content_policy": policy.model_dump(mode="json")})
    result = await executor.generate(source)

    author_inputs = [
        json.loads(payload.split("\n", 1)[1]) for actor, payload, _ in calls if actor is author
    ]
    assert len(author_inputs) == 2
    assert author_inputs[0]["revision_feedback"] is None
    assert "[limit_to_supported_effects]" in author_inputs[1]["revision_feedback"]
    assert author_inputs[1]["candidate"]["candidate_id"] == candidate.candidate_id
    review_inputs = [
        json.loads(payload.split("\n", 1)[1]) for actor, payload, _ in calls if actor is reviewer
    ]
    assert len(review_inputs) == 2
    assert review_inputs[1]["candidate"] == revised.model_dump(mode="json")
    assert any(SECRET in payload for actor, payload, _ in calls if actor is reviewer)
    assert all(SECRET not in payload for actor, payload, _ in calls if actor in {author, WRITER})
    assert result.execution_trace.stop_reason == "completed", [
        node.error for node in result.execution_trace.nodes if node.error
    ]
    assert result.execution_trace.repairs == 1
    assert len(result.content_candidates) == 1
    staged = result.content_candidates[0]
    assert staged["status"] == "staged"
    assert staged["reviewed"]["candidate"] == revised.model_dump(mode="json")
    assert executor.content_store.list_quests(source.session_id) == []
