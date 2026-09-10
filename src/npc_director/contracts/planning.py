"""Internal planning artifacts. None of these extend the 1.0 performance wire format."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from npc_director.contracts.content import ContentNeed
from npc_director.contracts.enums import Intent
from npc_director.contracts.routing import RouteDecision


class PlanningContract(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SpeechAct(PlanningContract):
    kind: str = Field(min_length=1, max_length=60)
    meaning: str = Field(min_length=1, max_length=500)
    target_id: str | None = None
    condition: str | None = None
    resolved: bool = True


class TurnGoal(PlanningContract):
    id: str = Field(min_length=1, max_length=80)
    description: str = Field(min_length=1, max_length=500)
    completion_condition: str = Field(default="", max_length=500)
    depends_on: list[str] = Field(default_factory=list, max_length=8)
    parent_quest_id: str | None = None
    blocked_reason: str | None = None
    kind: Literal["respond", "action", "investigate", "collaborate", "content"] = "respond"
    status: Literal["pending", "waiting_for_player", "waiting_for_npc", "completed"] = "pending"
    completion_basis: Literal["none", "this_reply", "observed_event"] = "none"
    evidence_refs: list[str] = Field(default_factory=list, max_length=8)


class KnowledgeNeed(PlanningContract):
    question: str = Field(min_length=1, max_length=500)
    kind: Literal["request_ambiguity", "fact_unknown", "evidence_conflict", "capability_missing"]
    required_for_goal: str | None = None
    known_source: str | None = None


class CollaborationRequest(PlanningContract):
    target_npc_id: str = Field(min_length=1, max_length=80)
    purpose: str = Field(min_length=1, max_length=500)
    text: str = Field(min_length=1, max_length=1000)
    claims: list[str] = Field(default_factory=list, max_length=8)
    claim_refs: list[str] = Field(default_factory=list, max_length=8)
    speech_act: Literal["ask", "inform", "propose", "accept", "refuse"] = "ask"


OperationKind = Literal["lore", "narrative", "negotiate", "consult_npc", "author_content", "replan"]


class OperationRequest(PlanningContract):
    id: str = Field(min_length=1, max_length=80, pattern=r"^[a-zA-Z0-9_.:-]+$")
    kind: OperationKind
    objective: str = Field(default="", max_length=500)
    depends_on: list[str] = Field(default_factory=list, max_length=16)
    goal_ids: list[str] = Field(default_factory=list, max_length=8)
    queries: list[str] = Field(default_factory=list, max_length=4)


class TurnAnalysis(RouteDecision):
    """A primary legacy intent is a summary, never the whole interpretation."""

    speech_acts: list[SpeechAct] = Field(default_factory=list, max_length=8)
    goals: list[TurnGoal] = Field(default_factory=list, max_length=8)
    knowledge_needs: list[KnowledgeNeed] = Field(default_factory=list, max_length=8)
    operations: list[OperationRequest] = Field(default_factory=list, max_length=16)
    collaboration_requests: list[CollaborationRequest] = Field(default_factory=list, max_length=3)
    content_need: ContentNeed | None = None
    clarification_question: str | None = Field(default=None, max_length=500)
    disclosure_strategy: Literal["truthful", "withhold", "mislead", "lie"] = "truthful"
    disclosure_motive: str | None = Field(default=None, max_length=500)
    proposed_commitments: list[str] = Field(default_factory=list, max_length=8)
    resolved_commitments: list[str] = Field(default_factory=list, max_length=8)
    resolved_goal_ids: list[str] = Field(default_factory=list, max_length=8)
    referent_updates: list[SpeechAct] = Field(default_factory=list, max_length=8)

    def legacy_route(self) -> RouteDecision:
        return RouteDecision.model_validate(
            self.model_dump(include=set(RouteDecision.model_fields))
        )


class PlanNode(PlanningContract):
    id: str
    kind: Literal[
        "lore",
        "narrative",
        "negotiate",
        "consult_npc",
        "author_content",
        "replan",
        "screenwriter",
        "performance",
        "quality",
    ]
    depends_on: list[str] = Field(default_factory=list)
    objective: str = ""
    goal_ids: list[str] = Field(default_factory=list)
    queries: list[str] = Field(default_factory=list, max_length=4)


class ExecutionPlan(PlanningContract):
    revision: int = Field(default=0, ge=0)
    primary_intent: Intent
    nodes: list[PlanNode] = Field(max_length=32)
    deferred_nodes: list[PlanNode] = Field(default_factory=list, max_length=32)

    @model_validator(mode="after")
    def closed_acyclic_graph(self) -> ExecutionPlan:
        ids = [node.id for node in self.nodes]
        if len(ids) != len(set(ids)):
            raise ValueError("plan node ids must be unique")
        remaining = {node.id: set(node.depends_on) for node in self.nodes}
        if any(deps - set(ids) for deps in remaining.values()):
            raise ValueError("plan references an unknown dependency")
        done: set[str] = set()
        while remaining:
            ready = {key for key, deps in remaining.items() if deps <= done}
            if not ready:
                raise ValueError("plan dependency cycle")
            done.update(ready)
            remaining = {key: deps for key, deps in remaining.items() if key not in ready}
        return self


class NegotiationOutcome(PlanningContract):
    status: Literal["proposed", "counteroffer", "agreed", "refused", "needs_information"]
    terms: list[str] = Field(default_factory=list, max_length=8)
    unresolved_issues: list[str] = Field(default_factory=list, max_length=8)
    response_obligations: list[str] = Field(default_factory=list, max_length=8)
    evidence_refs: list[str] = Field(default_factory=list, max_length=8)
    rationale: str = Field(default="", max_length=800)


class QualityIssue(PlanningContract):
    target: Literal["analysis", "lore", "narrative", "negotiation", "dialogue", "performance"]
    code: str = Field(min_length=1, max_length=80)
    explanation: str = Field(min_length=1, max_length=1000)
    blocking: bool = True


class QualityVerdict(PlanningContract):
    passed: bool
    naturalness: int = Field(default=3, ge=1, le=5)
    persona_consistency: int = Field(default=3, ge=1, le=5)
    response_coverage: int = Field(default=3, ge=1, le=5)
    issues: list[QualityIssue] = Field(default_factory=list, max_length=12)


class NodeTrace(PlanningContract):
    node_id: str
    role: str
    entry_kind: Literal["operation", "model_call"] = "operation"
    attempt: int = Field(default=1, ge=1)
    status: Literal["started", "completed", "failed", "reused", "blocked"]
    input_digest: str = ""
    output: dict[str, Any] | None = None
    error: str | None = None
    model_calls: int = 0
    latency_ms: float = 0


class ExecutionTrace(PlanningContract):
    schema_version: Literal["2.0"] = "2.0"
    analysis: TurnAnalysis | None = None
    plans: list[ExecutionPlan] = Field(default_factory=list)
    nodes: list[NodeTrace] = Field(default_factory=list)
    model_calls: int = 0
    repairs: int = 0
    revisions: int = 0
    stop_reason: str = "completed"
    quality: QualityVerdict | None = None


class DialogueStateDelta(PlanningContract):
    used_fact_refs: list[str] = Field(default_factory=list, max_length=16)
    reply_outcome: Literal["resolved", "partial", "pending", "refused"] = "partial"
    pending_questions: list[str] = Field(default_factory=list, max_length=8)
    open_goals: list[TurnGoal] = Field(default_factory=list, max_length=8)
    addressed_act_kinds: list[str] = Field(default_factory=list, max_length=8)
    disclosure_strategy: str = "truthful"
    # Only a completed delivery may promote these into remembered commitments.
    proposed_commitments: list[str] = Field(default_factory=list, max_length=8)
    resolved_commitments: list[str] = Field(default_factory=list, max_length=8)
    resolved_goal_ids: list[str] = Field(default_factory=list, max_length=8)
    referent_updates: list[SpeechAct] = Field(default_factory=list, max_length=8)
