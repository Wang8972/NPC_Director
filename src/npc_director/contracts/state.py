from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from npc_director.contracts.performance import PerformanceDirective
from npc_director.contracts.plan import TurnPlan


class ContractModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SceneSnapshot(ContractModel):
    location: str = Field(min_length=1, max_length=120)
    tension: float = Field(default=0, ge=0, le=1)
    nearby_entities: list[str] = Field(default_factory=list, max_length=20)
    animator_state: str = Field(default="idle", max_length=120)
    active_actions: list[str] = Field(default_factory=list, max_length=8)
    catalog_version: str = Field(default="m0-v1", max_length=40)
    metadata: dict[str, Any] = Field(default_factory=dict)


class TurnRequest(ContractModel):
    session_id: str = Field(min_length=1, max_length=120)
    turn_id: str = Field(min_length=1, max_length=120)
    npc_id: str = Field(min_length=1, max_length=80, pattern=r"^[a-zA-Z0-9_.:-]+$")
    player_input: str = Field(min_length=1, max_length=2_000)
    scene: SceneSnapshot
    character_core: str = Field(min_length=1, max_length=2_000)
    recent_history: list[str] = Field(default_factory=list, max_length=12)
    world_state_summary: str = Field(default="", max_length=2_000)


class NPCDomainState(ContractModel):
    npc_id: str
    relationship: dict[str, int] = Field(default_factory=dict)
    world_flags: dict[str, bool] = Field(default_factory=dict)
    quests: dict[str, str] = Field(default_factory=dict)
    npc_state: dict[str, Any] = Field(default_factory=dict)
    version: int = Field(default=0, ge=0)


class NPCSessionState(ContractModel):
    session_id: str
    npc_id: str
    turn_index: int = Field(default=0, ge=0)
    history_summary: str = Field(default="", max_length=6_000)
    memory_refs: list[str] = Field(default_factory=list, max_length=50)


class GenerationMetrics(ContractModel):
    model: str | None = None
    latency_ms: float = Field(ge=0)
    input_tokens: int = Field(default=0, ge=0)
    output_tokens: int = Field(default=0, ge=0)
    total_tokens: int = Field(default=0, ge=0)
    estimated_cost_usd: float | None = Field(default=None, ge=0)


class TurnRunResult(ContractModel):
    plan: TurnPlan
    directive: PerformanceDirective
    metrics: GenerationMetrics


class EngineAck(ContractModel):
    turn_id: str
    idempotency_key: str
    status: Literal["ack", "completed", "interrupted", "error"]
    detail: str | None = None
