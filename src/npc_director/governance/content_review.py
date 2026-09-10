"""Deterministic gates after an independent model reviews narrative quality."""

from __future__ import annotations

import re
import unicodedata
from datetime import UTC, datetime

from npc_director.contracts.content import (
    ContentCandidate,
    ContentNeed,
    ContentPolicy,
    ContentReview,
    NarrativeScopeDecision,
    ObjectiveEvent,
    ObjectiveRef,
    ObjectiveStep,
    ReviewedContent,
)


class ContentReviewError(ValueError):
    def __init__(self, reasons: list[str] | str) -> None:
        self.reasons = [reasons] if isinstance(reasons, str) else reasons
        super().__init__("; ".join(self.reasons))


def semantic_key(value: str) -> str:
    """Canonicalize a supplied goal key; semantic equivalence is reviewed separately."""
    normalized = unicodedata.normalize("NFKC", value).casefold()
    return re.sub(r"[\W_]+", "", normalized, flags=re.UNICODE)


def should_author_content(need: ContentNeed, policy: ContentPolicy) -> bool:
    return need.requires_author and need.content_kind in policy.allowed_kinds


_REVISION_GUIDANCE = {
    "align_requested_scope": (
        "need_id、content_kind、scope.scope和scope.parent_objective须与need逐项一致；"
        "不能通过改为另一个目标、支线或父任务来绕过审核。"
    ),
    "use_allowed_actions": (
        "required_actions与steps.action只能逐字使用policy.allowed_actions内的程序ID；"
        "删除不需要的动作，不猜测替代ID，也不把自然语言描述当作能力。"
    ),
    "use_allowed_rewards": (
        "reward_types只能逐字引用policy.allowed_reward_types；没有必要的回报就留空，"
        "不能新增奖励或声称奖励已发放。"
    ),
    "use_available_sources": (
        "source_refs只能引用确实支持候选且出现在policy.available_lore_refs中的来源；"
        "作者context或公开policy已有材料也可作为依据，不凭空编造或无关引用补齐来源。"
    ),
    "use_registered_objectives": (
        "父目标只能引用policy.objective_refs或existing_quests中的原始ID及版本；"
        "新支线内部引用使用本candidate_id、quest_id=null、version=0。"
    ),
    "ground_in_author_context": (
        "逐项核对所指字段的事实前提，只使用作者已有context与policy能支持的材料；"
        "删除没有依据的断言，或改为尚待核实的问题。不要推测未公开的正确答案，"
        "也不要把候选提到的路线、人物、状态或选择称作已经存在且已登记。"
    ),
    "limit_to_supported_effects": (
        "将目标、步骤完成条件和结果统一限定为policy能力实际可执行的效果。"
        "对话或消息可询问、确认或记录意愿，不能代表已完成实物交付；"
        "接受意愿与实际接收分开，拒绝时尊重边界并结束询问。"
        "quest_transition不授权新路线或任意世界状态；缺少已登记效果时删除该效果，"
        "保留获准范围内有意义的对话。候选只定义未来条件，发布不等于接受或完成。"
    ),
    "clarify_independent_value": (
        "逐项说明独立目标、成立的人物动机、可拒绝性、完成条件、有意义结果与不可充分合并的理由；"
        "父任务必要步骤不能成为支线，不能靠新障碍、奖励或无依据剧情补足独立性。"
    ),
}

_INDEX = r"(?:0|[1-9][0-9]*)"
_SCOPE_PROSE = (
    r"/scope/(?:reason|independent_goal|character_motivation|completion_condition|"
    rf"merge_insufficient_reason|meaningful_outcomes(?:/{_INDEX})?)"
)
_NARRATIVE_PATH = (
    rf"(?:/title|/summary|{_SCOPE_PROSE}|/facts(?:/{_INDEX}(?:/"
    rf"(?:statement|persona_basis|motive))?)?|/steps/{_INDEX}"
    rf"(?:/(?:description|completion_condition))?|/events/{_INDEX}"
    rf"(?:/(?:description|choices(?:/{_INDEX})?|consequences(?:/{_INDEX})?))?)"
)
_ACTION_PATH = rf"(?:/required_actions(?:/{_INDEX})?|/steps/{_INDEX}/action)"
_REVISION_PATHS = {
    "align_requested_scope": r"/(?:need_id|content_kind|scope/(?:scope|parent_objective))",
    "use_allowed_actions": _ACTION_PATH,
    "use_allowed_rewards": rf"/reward_types(?:/{_INDEX})?",
    "use_available_sources": rf"/source_refs(?:/{_INDEX})?",
    "use_registered_objectives": (
        rf"(?:/scope/parent_objective|/(?:steps|events)/{_INDEX}/objective)"
    ),
    "ground_in_author_context": _NARRATIVE_PATH,
    "limit_to_supported_effects": rf"(?:{_NARRATIVE_PATH}|{_ACTION_PATH})",
    "clarify_independent_value": (
        rf"(?:{_SCOPE_PROSE}|/scope/(?:can_decline|necessary_for_parent))"
    ),
}


def _revision_path_exists(document: dict, path: str) -> bool:
    """Only schema fields and in-range array indices can become Author feedback."""
    value = document
    for part in path.removeprefix("/").split("/"):
        if isinstance(value, dict) and part in value:
            value = value[part]
        elif isinstance(value, list) and part.isascii() and part.isdecimal():
            index = int(part)
            if index >= len(value):
                return False
            value = value[index]
        else:
            return False
    return True


def build_content_revision_feedback(
    need: ContentNeed,
    candidate: ContentCandidate,
    review: ContentReview,
    public_policy: ContentPolicy,
) -> str:
    """Compile bounded review signals; never forward privileged Reviewer prose.

    Pass the exact policy already visible to the Author, not the enriched review
    policy. Only fixed edit codes and validated paths into the Author's own
    candidate cross this boundary. Neither private facts nor proposed replacement
    values can enter feedback. Public capability errors are derived independently
    so a mistaken Reviewer cannot invent a missing/alternative capability ID.
    """
    edits: dict[str, set[str]] = {}
    document = candidate.model_dump(mode="json")

    def add(code: str, path: str) -> None:
        edits.setdefault(code, set()).add(path)

    if candidate.need_id != need.need_id:
        add("align_requested_scope", "/need_id")
    if candidate.content_kind != need.content_kind:
        add("align_requested_scope", "/content_kind")
    if candidate.scope.scope != need.scope.scope:
        add("align_requested_scope", "/scope/scope")
    if candidate.scope.parent_objective != need.scope.parent_objective:
        add("align_requested_scope", "/scope/parent_objective")
    for index, action in enumerate(candidate.required_actions):
        if action not in public_policy.allowed_actions:
            add("use_allowed_actions", f"/required_actions/{index}")
    for index, step in enumerate(candidate.steps):
        if step.action and step.action not in public_policy.allowed_actions:
            add("use_allowed_actions", f"/steps/{index}/action")
    for index, reward in enumerate(candidate.reward_types):
        if reward not in public_policy.allowed_reward_types:
            add("use_allowed_rewards", f"/reward_types/{index}")
    for index, ref in enumerate(candidate.source_refs):
        if ref not in public_policy.available_lore_refs:
            add("use_available_sources", f"/source_refs/{index}")

    if review.action == "revise" and review.candidate_id == candidate.candidate_id:
        for edit in review.revision_edits:
            # Syntax/capability corrections need an actual public mismatch.
            # A Reviewer can misread the list or have richer private context.
            if edit.code in {"align_requested_scope", "use_allowed_actions", "use_allowed_rewards"}:
                continue
            pattern = _REVISION_PATHS.get(edit.code)
            if pattern is None:
                continue
            for path in edit.field_paths:
                if len(path) <= 160 and re.fullmatch(pattern, path) and _revision_path_exists(
                    document, path
                ):
                    add(edit.code, path)

    lines = [
        "进行一次定向修订后重新提交独立审核；这不是批准或世界事实更新。",
        "保留candidate_id和objective_key，need_id、content_kind、scope.scope与"
        "scope.parent_objective严格按need；保留成立的人物动机和独立可拒绝目标，"
        "不为修订扩展剧情、权限或奖励。",
    ]
    if edits:
        for code, paths in edits.items():
            lines.append(f"[{code}] {', '.join(sorted(paths))}：{_REVISION_GUIDANCE[code]}")
    else:
        # Legacy reviews have no bounded edit codes. Their free text remains
        # private even when it appears helpful; the Author rechecks public input.
        lines.append(
            "复核候选的事实前提、可执行效果和独立价值，只依据作者已有context与policy；"
            "修正未获支持的表述，不推测审核器掌握但未公开的世界信息。"
        )
    return "\n".join(lines)


def validate_objective_ref(ref: ObjectiveRef, policy: ContentPolicy) -> None:
    available = [*policy.objective_refs, *(quest.ref for quest in policy.existing_quests)]
    if not any(item == ref for item in available):
        raise ContentReviewError(
            f"unavailable or stale objective reference: {ref.key}@{ref.version}",
        )


def _check_independence(scope: NarrativeScopeDecision) -> list[str]:
    failures: list[str] = []
    for field in (
        "independent_goal",
        "character_motivation",
        "completion_condition",
        "merge_insufficient_reason",
    ):
        if not getattr(scope, field).strip():
            failures.append(f"side quest lacks {field}")
    if not any(outcome.strip() for outcome in scope.meaningful_outcomes):
        failures.append("side quest lacks meaningful outcomes")
    if not scope.can_decline:
        failures.append("side quest must be independently declinable")
    if scope.necessary_for_parent:
        failures.append("a prerequisite for the parent is a step, not a new side quest")
    return failures


def bind_candidate_objectives(
    candidate: ContentCandidate, policy: ContentPolicy
) -> ContentCandidate:
    """Compile temporary references inside a new quest into its own namespace.

    These names cannot grant access to any existing objective. Known external
    references and nonzero versions are deliberately left for strict rejection.
    """
    if candidate.scope.scope != "side_quest":
        return candidate
    existing = {ref.key for ref in policy.objective_refs}
    existing.update(quest.ref.key for quest in policy.existing_quests)
    result = candidate.model_copy(deep=True)
    for item in [*result.steps, *result.events]:
        if item.objective.version == 0 and item.objective.key not in existing:
            item.objective = ObjectiveRef(objective_id=candidate.candidate_id)
    return result


def validate_content_review(
    need: ContentNeed,
    candidate: ContentCandidate,
    review: ContentReview,
    policy: ContentPolicy,
) -> ReviewedContent:
    """Validate and materialize only reviewed effects. Never expand permissions here.

    Semantic consistency is assessed by the independent Reviewer. This gate adds
    exact capability/reference checks, deterministic canonical-fact protection,
    task granularity requirements, and strips quest effects on attach/merge.
    """
    submitted = candidate
    candidate = bind_candidate_objectives(candidate, policy)
    failures: list[str] = []
    if not should_author_content(need, policy):
        failures.append("content creation is unnecessary, unchecked, or not authorized")
    if candidate.need_id != need.need_id or candidate.candidate_id != review.candidate_id:
        failures.append("candidate, need and review identities do not match")
    if candidate.content_kind not in policy.allowed_kinds:
        failures.append("content kind is not authorized by server policy")
    if candidate.content_kind != need.content_kind:
        failures.append("candidate changes the requested content kind")
    if candidate.expires_at is not None:
        if candidate.content_kind == "quest":
            failures.append("quests use their explicit lifecycle, not content expiration")
        if candidate.expires_at <= datetime.now(UTC):
            failures.append("temporary content already expired")
    if (
        candidate.scope.scope != need.scope.scope
        or candidate.scope.parent_objective != need.scope.parent_objective
    ):
        failures.append("author changed the planned content scope or parent")
    if review.action not in {"approve", "attach", "merge"}:
        failures.append(f"review is not approved: {review.action}")
    if not (review.setting_consistent and review.persona_consistent and review.meaningful):
        failures.append("independent review did not confirm setting, persona and meaning")
    if not semantic_key(candidate.objective_key):
        failures.append("objective key must identify the semantic goal")
    if not set(candidate.required_actions).issubset(policy.allowed_actions):
        failures.append("candidate requires an unregistered action")
    if not set(candidate.reward_types).issubset(policy.allowed_reward_types):
        failures.append("candidate requires an unregistered reward type")
    if not set(candidate.source_refs).issubset(policy.available_lore_refs):
        failures.append("candidate cites unavailable evidence")
    scope = review.final_scope or candidate.scope
    if review.action == "approve":
        if (
            scope.scope != candidate.scope.scope
            or scope.parent_objective != candidate.scope.parent_objective
            or scope.can_decline != candidate.scope.can_decline
            or scope.necessary_for_parent != candidate.scope.necessary_for_parent
        ):
            failures.append("approve must not silently change candidate scope")
        # Reviewer prose is justification, not permission to rewrite an approved
        # definition. Preserve all original candidate semantics on approve.
        scope = candidate.scope
    if review.action in {"attach", "merge"}:
        if "event" not in policy.allowed_kinds:
            failures.append("parent event creation is not authorized by server policy")
        if scope.scope not in {"step", "task_event"}:
            failures.append("attach and merge require a parent step or task event")
        if scope.parent_objective is None:
            failures.append("attach and merge require a parent objective")
    if review.action == "merge":
        if review.merge_into is None or review.merge_into != scope.parent_objective:
            failures.append("merge must name the final parent objective and version")
        elif not any(quest.ref == review.merge_into for quest in policy.existing_quests):
            failures.append("merge target is not an existing quest")
    if review.action != "merge" and review.merge_into is not None:
        failures.append("merge target is only valid for a merge decision")
    if scope.scope in {"step", "task_event"} and scope.parent_objective is None:
        failures.append("task steps and events require a stable parent objective")
    if scope.parent_objective is not None:
        try:
            validate_objective_ref(scope.parent_objective, policy)
        except ContentReviewError as exc:
            failures.extend(exc.reasons)
    if scope.scope == "side_quest":
        if candidate.content_kind != "quest":
            failures.append("backgrounds, facts and events are not independent quests")
        failures.extend(_check_independence(scope))
        duplicates = [
            quest
            for quest in policy.existing_quests
            if semantic_key(quest.objective_key) == semantic_key(candidate.objective_key)
        ]
        if duplicates:
            failures.append("existing quest already covers this goal; merge or reuse it")
    if (
        candidate.content_kind == "quest"
        and scope.scope != "side_quest"
        and review.action not in {"attach", "merge"}
    ):
        failures.append("a quest without independent value must be attached or merged")
    facts_by_key = {fact.fact_key: fact for fact in policy.canonical_facts}
    seen_facts: set[str] = set()
    for fact in candidate.facts:
        if fact.fact_key in seen_facts:
            failures.append("duplicate fact keys in candidate")
        seen_facts.add(fact.fact_key)
        canonical = facts_by_key.get(fact.fact_key)
        if (
            canonical is not None
            and fact.epistemic_status == "world_fact"
            and fact.statement.strip() != canonical.statement.strip()
        ):
            failures.append(f"candidate contradicts canonical fact {fact.fact_key}")
        if fact.deceptive and fact.source_npc_id != policy.npc_id:
            failures.append("a character cannot author another NPC's private deceptive claim")
    for step in candidate.steps:
        if step.action and step.action not in policy.allowed_actions:
            failures.append(f"step {step.step_id} requires an unregistered action")
    if len({step.step_id for step in candidate.steps}) != len(candidate.steps):
        failures.append("duplicate step identifiers")
    if len({event.event_id for event in candidate.events}) != len(candidate.events):
        failures.append("duplicate event identifiers")
    for item in [*candidate.steps, *candidate.events]:
        is_local = (
            scope.scope == "side_quest"
            and item.objective.objective_id == candidate.candidate_id
            and item.objective.quest_id is None
            and item.objective.version == 0
        )
        if scope.scope == "side_quest" and not is_local:
            failures.append("new quest steps must target their own runtime-assigned objective")
        if not is_local and review.action not in {"attach", "merge"}:
            try:
                validate_objective_ref(item.objective, policy)
            except ContentReviewError as exc:
                failures.extend(exc.reasons)
            if scope.parent_objective is not None and item.objective != scope.parent_objective:
                failures.append("nested content must belong to its approved parent")
    step_ids = {step.step_id for step in candidate.steps}
    completed: set[str] = set()
    pending = list(candidate.steps)
    while pending:
        ready = [step for step in pending if set(step.depends_on).issubset(completed)]
        if not ready:
            failures.append("steps contain a cycle or unknown dependency")
            break
        for step in ready:
            if not set(step.depends_on).issubset(step_ids):
                failures.append("step references an unavailable dependency")
            completed.add(step.step_id)
            pending.remove(step)
    if failures:
        raise ContentReviewError(failures)
    normalized = candidate.model_copy(deep=True)
    normalized.scope = scope.model_copy(deep=True)
    if review.action in {"attach", "merge"}:
        assert scope.parent_objective is not None
        normalized.content_kind = "event"
        normalized.reward_types = []
        normalized.steps = [
            step.model_copy(update={"objective": scope.parent_objective}, deep=True)
            for step in normalized.steps
        ]
        normalized.events = [
            event.model_copy(update={"objective": scope.parent_objective}, deep=True)
            for event in normalized.events
        ]
    if scope.parent_objective is not None and not normalized.steps and not normalized.events:
        if scope.scope == "step":
            normalized.steps = [
                ObjectiveStep(
                    step_id=f"{candidate.candidate_id}:step"[:120],
                    objective=scope.parent_objective,
                    description=candidate.summary[:1_000],
                    completion_condition=scope.completion_condition,
                )
            ]
        elif scope.scope == "task_event":
            normalized.events = [
                ObjectiveEvent(
                    event_id=f"{candidate.candidate_id}:event"[:120],
                    objective=scope.parent_objective,
                    description=candidate.summary[:1_000],
                )
            ]
    return ReviewedContent(
        need=need,
        candidate=normalized,
        submitted_candidate=submitted,
        review=review,
        policy=policy,
    )
