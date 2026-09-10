"""Server-owned identities and durable state for event-driven NPC episodes.

These contracts are internal. They do not change the Unity wire protocol.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from npc_director.contracts.state import SceneSnapshot


def _now() -> datetime:
    return datetime.now(UTC)


class EpisodeContract(BaseModel):
    model_config = ConfigDict(extra="forbid")


class EpisodeBudget(EpisodeContract):
    max_model_calls: int = Field(default=32, ge=0, le=100)
    max_npc_turns: int = Field(default=6, ge=0, le=20)
    max_participants: int = Field(default=4, ge=1, le=20)
    max_new_quests: int = Field(default=1, ge=0, le=10)
    max_plan_revisions: int = Field(default=2, ge=0, le=10)
    max_repairs: int = Field(default=1, ge=0, le=10)
    max_nodes: int = Field(default=32, ge=0, le=200)
    max_total_tokens: int = Field(default=96_000, ge=0)
    max_active_seconds: float = Field(default=180, ge=0)


class KnowledgeClaim(EpisodeContract):
    content_id: str = Field(min_length=1, max_length=160)
    text: str = Field(default="", max_length=2_000)
    epistemic_status: Literal["observed", "verified", "reported", "rumor"] = "reported"
    source_event_id: str | None = Field(default=None, max_length=160)
    shareable: bool = False
    source_npc_id: str | None = None
    expires_at: datetime | None = None

    @model_validator(mode="after")
    def expiry_has_timezone(self) -> KnowledgeClaim:
        if self.expires_at is not None and self.expires_at.tzinfo is None:
            raise ValueError("knowledge expiry must include its timezone")
        return self


class NpcMessage(EpisodeContract):
    speaker_id: str = Field(min_length=1, max_length=80)
    target_npc_id: str = Field(min_length=1, max_length=80)
    text: str = Field(min_length=1, max_length=2_000)
    purpose: str = Field(default="", max_length=500)
    claims: list[KnowledgeClaim] = Field(default_factory=list, max_length=20)
    audience: list[str] = Field(default_factory=list, max_length=20)
    message_kind: Literal["ask", "inform", "propose", "accept", "refuse", "reply"] = "inform"
    reply_requested: bool = False
    in_reply_to: str | None = None
    evidence_fingerprint: str = ""


class EpisodeRequest(EpisodeContract):
    event_id: str = Field(min_length=1, max_length=160)
    session_id: str = Field(min_length=1, max_length=120)
    npc_id: str = Field(min_length=1, max_length=80)
    origin: Literal["player", "npc", "world_event"] = "player"
    text: str = Field(min_length=1, max_length=2_000)
    scene: SceneSnapshot
    speaker_id: str = Field(default="player", min_length=1, max_length=80)
    participants: list[str] = Field(default_factory=list, max_length=20)
    source_event_id: str | None = Field(default=None, max_length=160)
    claims: list[KnowledgeClaim] = Field(default_factory=list, max_length=20)

    @model_validator(mode="after")
    def player_cannot_publish_claims(self) -> EpisodeRequest:
        if self.origin == "player" and self.claims:
            raise ValueError("player input cannot supply authoritative knowledge claims")
        return self


class EpisodeRecord(EpisodeContract):
    id: str = Field(min_length=1, max_length=120)
    session_id: str = Field(min_length=1, max_length=120)
    request: EpisodeRequest
    status: Literal[
        "running",
        "waiting_for_completion",
        "waiting_for_player",
        "waiting_for_event",
        "waiting_for_approval",
        "completed",
        "cancelled",
        "failed",
        "unsupported",
        "budget_exhausted",
        "no_progress",
    ] = "running"
    budget: EpisodeBudget = Field(default_factory=EpisodeBudget)
    used_model_calls: int = Field(default=0, ge=0)
    used_npc_turns: int = Field(default=0, ge=0)
    used_nodes: int = Field(default=0, ge=0)
    used_tokens: int = Field(default=0, ge=0)
    reserved_tokens: int = Field(default=0, ge=0)
    active_seconds: float = Field(default=0, ge=0)
    used_plan_revisions: int = Field(default=0, ge=0)
    used_repairs: int = Field(default=0, ge=0)
    reserved_quests: int = Field(default=0, ge=0)
    published_quests: int = Field(default=0, ge=0)
    revision: int = Field(default=0, ge=0)
    epoch: int = Field(default=0, ge=0)
    active_turn_id: str | None = Field(default=None, max_length=120)
    stop_reason: str | None = Field(default=None, max_length=1_000)
    artifacts: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=_now)
    updated_at: datetime = Field(default_factory=_now)

    @property
    def episode_id(self) -> str:
        return self.id

    def remaining_budget(self) -> dict[str, int | float]:
        return {
            "remaining_model_calls": max(0, self.budget.max_model_calls - self.used_model_calls),
            "remaining_npc_turns": max(0, self.budget.max_npc_turns - self.used_npc_turns),
            "remaining_nodes": max(0, self.budget.max_nodes - self.used_nodes),
            "remaining_total_tokens": max(
                0, self.budget.max_total_tokens - self.used_tokens - self.reserved_tokens
            ),
            "remaining_active_seconds": max(
                0, self.budget.max_active_seconds - self.active_seconds
            ),
            "remaining_plan_revisions": max(
                0, self.budget.max_plan_revisions - self.used_plan_revisions
            ),
            "remaining_repairs": max(0, self.budget.max_repairs - self.used_repairs),
            "remaining_new_quests": max(
                0, self.budget.max_new_quests - self.reserved_quests - self.published_quests
            ),
        }


class DialogueEvent(EpisodeContract):
    event_id: str = Field(min_length=1, max_length=160)
    session_id: str = Field(min_length=1, max_length=120)
    turn_id: str = Field(min_length=1, max_length=120)
    speaker_id: str = Field(min_length=1, max_length=80)
    audience: list[str] = Field(default_factory=list, max_length=20)
    text: str = Field(min_length=1, max_length=4_000)
    origin: Literal["player", "npc", "world_event"] = "npc"
    status: Literal["received", "completed", "interrupted"] = "completed"
    episode_id: str | None = Field(default=None, max_length=120)
    claims: list[KnowledgeClaim] = Field(default_factory=list, max_length=20)
    occurred_at: datetime = Field(default_factory=_now)


class DialogueState(EpisodeContract):
    session_id: str
    npc_id: str
    topic: str = ""
    referents: dict[str, str] = Field(default_factory=dict)
    open_questions: list[str] = Field(default_factory=list)
    pending_intents: list[dict[str, Any]] = Field(default_factory=list)
    commitments: list[dict[str, Any]] = Field(default_factory=list)
    emotion: dict[str, Any] = Field(default_factory=dict)
    recent_expressions: list[str] = Field(default_factory=list)
    version: int = Field(default=0, ge=0)


class EpisodeJob(EpisodeContract):
    job_id: str
    episode_id: str
    session_id: str
    turn_id: str
    message: NpcMessage
    parent_turn_id: str | None = None
    source_event_id: str | None = None
    dedupe_key: str
    status: Literal[
        "queued", "claimed", "waiting", "pending_approval", "completed", "cancelled", "failed"
    ] = "queued"
    epoch: int = Field(default=0, ge=0)
    claimed_by: str | None = None
    lease_until: datetime | None = None
    created_at: datetime = Field(default_factory=_now)


class NodeLedgerRecord(EpisodeContract):
    episode_id: str
    node_id: str
    kind: str
    status: Literal["running", "completed", "failed", "skipped"] = "running"
    input_digest: str
    output: dict[str, Any] = Field(default_factory=dict)
    model_calls: int = Field(default=0, ge=0)
    error: str | None = None
    created_at: datetime = Field(default_factory=_now)
    updated_at: datetime = Field(default_factory=_now)
