"""Internal content contracts; generated prose is never an authority to mutate state."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from npc_director.contracts.plan import StateChangeProposal

NarrativeScope = Literal["action", "step", "task_event", "side_quest"]
ContentKind = Literal["quest", "event", "background", "fact"]
ReviewAction = Literal["approve", "attach", "merge", "revise", "reject"]
ContentRevisionCode = Literal[
    "align_requested_scope",
    "use_allowed_actions",
    "use_allowed_rewards",
    "use_available_sources",
    "use_registered_objectives",
    "ground_in_author_context",
    "limit_to_supported_effects",
    "clarify_independent_value",
]


class ContentContract(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ObjectiveRef(ContentContract):
    objective_id: str = Field(min_length=1, max_length=120)
    quest_id: str | None = Field(default=None, max_length=80)
    version: int = Field(default=0, ge=0)

    @property
    def key(self) -> str:
        return self.quest_id or self.objective_id


class NarrativeScopeDecision(ContentContract):
    scope: NarrativeScope = "action"
    parent_objective: ObjectiveRef | None = None
    reason: str = Field(default="", max_length=1_000)
    independent_goal: str = Field(default="", max_length=500)
    character_motivation: str = Field(default="", max_length=500)
    completion_condition: str = Field(default="", max_length=500)
    meaningful_outcomes: list[str] = Field(default_factory=list, max_length=8)
    can_decline: bool = False
    necessary_for_parent: bool = False
    merge_insufficient_reason: str = Field(default="", max_length=500)


class ObjectiveStep(ContentContract):
    step_id: str = Field(min_length=1, max_length=120)
    objective: ObjectiveRef
    description: str = Field(min_length=1, max_length=1_000)
    action: str = Field(
        default="",
        max_length=100,
        description="Canonical capability ID from policy.allowed_actions, never prose.",
    )
    completion_condition: str = Field(default="", max_length=500)
    depends_on: list[str] = Field(default_factory=list, max_length=16)


class ObjectiveEvent(ContentContract):
    event_id: str = Field(min_length=1, max_length=120)
    objective: ObjectiveRef
    description: str = Field(min_length=1, max_length=1_000)
    choices: list[str] = Field(default_factory=list, max_length=8)
    consequences: list[str] = Field(default_factory=list, max_length=8)


class ContentFact(ContentContract):
    fact_key: str = Field(min_length=1, max_length=120)
    statement: str = Field(min_length=1, max_length=1_000)
    epistemic_status: Literal["world_fact", "belief", "claim"] = "world_fact"
    source_npc_id: str | None = Field(default=None, max_length=80)
    deceptive: bool = False
    persona_basis: str = Field(default="", max_length=500)
    motive: str = Field(default="", max_length=500)

    @model_validator(mode="after")
    def deceptive_claims_are_not_facts(self) -> ContentFact:
        if self.deceptive and (
            self.epistemic_status != "claim"
            or not self.source_npc_id
            or not self.persona_basis.strip()
            or not self.motive.strip()
        ):
            raise ValueError("deception requires a sourced claim, persona basis and motive")
        return self


class ContentNeed(ContentContract):
    need_id: str = Field(min_length=1, max_length=120)
    purpose: str = Field(min_length=1, max_length=1_000)
    content_kind: ContentKind = "event"
    scope: NarrativeScopeDecision = Field(default_factory=NarrativeScopeDecision)
    motivation: str = Field(default="", max_length=500)
    reuse_checked: bool = False
    existing_content_sufficient: bool = False
    existing_content_refs: list[str] = Field(default_factory=list, max_length=32)
    allowed_kinds: list[ContentKind] = Field(default_factory=list, max_length=4)

    @property
    def requires_author(self) -> bool:
        return (
            self.reuse_checked
            and not self.existing_content_sufficient
            and self.content_kind in self.allowed_kinds
        )


class ExistingQuest(ContentContract):
    ref: ObjectiveRef
    objective_key: str = Field(min_length=1, max_length=240)
    summary: str = Field(default="", max_length=1_000)
    status: str = Field(default="offered", max_length=40)


class ContentPolicy(ContentContract):
    """Server-owned authorization snapshot, passed to models only as input."""

    session_id: str = Field(min_length=1, max_length=120)
    npc_id: str = Field(min_length=1, max_length=80)
    catalog_version: str = Field(default="1", max_length=80)
    policy_digest: str = Field(default="", max_length=128)
    allowed_kinds: list[ContentKind] = Field(default_factory=list, max_length=4)
    allowed_actions: list[str] = Field(default_factory=list, max_length=64)
    allowed_reward_types: list[str] = Field(default_factory=list, max_length=32)
    objective_refs: list[ObjectiveRef] = Field(default_factory=list, max_length=128)
    existing_quests: list[ExistingQuest] = Field(default_factory=list, max_length=128)
    canonical_facts: list[ContentFact] = Field(default_factory=list, max_length=128)
    hard_constraints: list[str] = Field(default_factory=list, max_length=32)
    available_lore_refs: list[str] = Field(default_factory=list, max_length=128)
    max_new_quests: int = Field(default=1, ge=0, le=32)


class ContentCandidate(ContentContract):
    candidate_id: str = Field(min_length=1, max_length=120)
    need_id: str = Field(min_length=1, max_length=120)
    content_kind: ContentKind
    scope: NarrativeScopeDecision
    title: str = Field(min_length=1, max_length=200)
    summary: str = Field(min_length=1, max_length=2_000)
    objective_key: str = Field(min_length=1, max_length=240)
    facts: list[ContentFact] = Field(default_factory=list, max_length=16)
    steps: list[ObjectiveStep] = Field(default_factory=list, max_length=16)
    events: list[ObjectiveEvent] = Field(default_factory=list, max_length=8)
    required_actions: list[str] = Field(
        default_factory=list,
        max_length=32,
        description="Exact IDs from policy.allowed_actions; never natural-language steps.",
    )
    reward_types: list[str] = Field(
        default_factory=list,
        max_length=8,
        description="Exact IDs from policy.allowed_reward_types; empty when no reward is required.",
    )
    source_refs: list[str] = Field(default_factory=list, max_length=32)
    visibility: Literal["private", "public"] = "private"
    expires_at: datetime | None = Field(
        default=None,
        description="Optional UTC expiry for temporary facts or events; null for durable content.",
    )

    @model_validator(mode="after")
    def expiry_has_timezone(self):
        if self.expires_at is not None and self.expires_at.tzinfo is None:
            raise ValueError("content expiry must include its timezone")
        return self


class ContentRevisionEdit(ContentContract):
    """A bounded review signal, never a channel for privileged replacement prose."""

    code: ContentRevisionCode
    field_paths: list[Annotated[str, Field(min_length=1, max_length=160)]] = Field(
        min_length=1,
        max_length=16,
        description=(
            "JSON pointers into the submitted candidate, e.g. /scope/completion_condition "
            "or /steps/0/description. Do not include private facts, replacement values, "
            "policy/context paths, or instructions. Runtime validates every path."
        ),
    )


class ContentReview(ContentContract):
    candidate_id: str = Field(min_length=1, max_length=120)
    action: ReviewAction
    final_scope: NarrativeScopeDecision | None = None
    merge_into: ObjectiveRef | None = None
    reasons: list[str] = Field(default_factory=list, max_length=12)
    revision_instructions: str = Field(default="", max_length=2_000)
    revision_edits: list[ContentRevisionEdit] = Field(
        default_factory=list,
        max_length=12,
        description=(
            "For revise, provide all concrete fixes using only supported codes and candidate "
            "field paths. Only these bounded signals can reach the Author; free-text reasons "
            "and revision_instructions are privileged review records."
        ),
    )
    setting_consistent: bool = False
    persona_consistent: bool = False
    meaningful: bool = False


class ContentAuthorInput(ContentContract):
    context: dict[str, Any] = Field(default_factory=dict)
    need: ContentNeed
    policy: ContentPolicy
    revision_feedback: str | None = None
    candidate: ContentCandidate | None = None


class ContentReviewerInput(ContentContract):
    context: dict[str, Any] = Field(default_factory=dict)
    need: ContentNeed
    candidate: ContentCandidate
    policy: ContentPolicy


class ReviewedContent(ContentContract):
    """Runtime-validated artifact. Revalidated by ContentStore before staging."""

    need: ContentNeed
    candidate: ContentCandidate
    submitted_candidate: ContentCandidate | None = None
    review: ContentReview
    policy: ContentPolicy


class StagedContent(ContentContract):
    content_id: str
    session_id: str
    episode_id: str
    turn_id: str
    npc_id: str
    status: Literal["staged", "published", "discarded"] = "staged"
    reviewed: ReviewedContent
    quest_id: str | None = None
    allowed_state_paths: list[str] = Field(default_factory=list)
    proposed_state_changes: StateChangeProposal = Field(default_factory=StateChangeProposal)
    policy_digest: str = ""
    created_at: str = ""
    published_at: str | None = None

    @property
    def candidate(self) -> ContentCandidate:
        candidate = self.reviewed.candidate.model_copy(deep=True)
        if self.quest_id is not None:
            ref = ObjectiveRef(objective_id=self.quest_id, quest_id=self.quest_id)
            for item in [*candidate.steps, *candidate.events]:
                if item.objective.objective_id == candidate.candidate_id:
                    item.objective = ref
        return candidate


class PublishedQuest(ContentContract):
    quest_id: str
    session_id: str
    objective_key: str
    content_id: str
    status: Literal["offered", "accepted", "active", "completed", "failed", "declined"]
    version: int = Field(default=0, ge=0)
