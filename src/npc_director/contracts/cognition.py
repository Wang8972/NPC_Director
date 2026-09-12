"""Internal, owner-scoped cognition contracts; never part of the engine wire."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class CognitionContract(BaseModel):
    model_config = ConfigDict(extra="forbid")


OPERATIONS = ("lore", "narrative", "negotiate", "consult_npc", "author_content", "replan")


class BehaviorModeDefinition(CognitionContract):
    mode_id: str = Field(pattern=r"^[a-z][a-z0-9_]{0,39}$")
    purpose: str = Field(min_length=1, max_length=500)
    entry_conditions: list[str] = Field(default_factory=list, max_length=8)
    exit_conditions: list[str] = Field(default_factory=list, max_length=8)
    action_preferences: list[str] = Field(default_factory=list, max_length=8)
    allowed_operations: list[
        Literal["lore", "narrative", "negotiate", "consult_npc", "author_content", "replan"]
    ] = Field(default_factory=lambda: list(OPERATIONS))


def default_modes() -> list[BehaviorModeDefinition]:
    return [
        BehaviorModeDefinition(
            mode_id=key, purpose=purpose, entry_conditions=[entry], exit_conditions=[leave]
        )
        for key, purpose, entry, leave in (
            (
                "neutral",
                "开放回应，保持角色自身立场",
                "没有需要持续处理的冲突或目标",
                "出现有依据的新目标或冲突",
            ),
            (
                "guarded",
                "保留判断、保护边界，允许有条件合作",
                "收到威胁、矛盾证据或涉及已有顾虑",
                "新证据解除顾虑；不能仅因问候清空戒备",
            ),
            (
                "cooperative",
                "在已经确认的条件内主动协作",
                "有依据的同意或共同目标",
                "条件撤回、目标完成或出现新冲突",
            ),
            (
                "investigative",
                "针对明确的信息缺口查证",
                "存在影响当前目标的事实缺口或矛盾",
                "取得所需证据或调查被撤回",
            ),
            (
                "task_focused",
                "推进已接受目标的下一项合法步骤",
                "已有被接受且尚未完成的目标",
                "实际完成、撤回或出现需重规划的事件",
            ),
        )
    ]


class BehaviorState(CognitionContract):
    mode_id: str = "neutral"
    version: int = 0
    goal_id: str | None = None
    reason: str = "initial"
    evidence_refs: list[str] = Field(default_factory=list)
    source_turn_id: str | None = None


class BehaviorDecision(CognitionContract):
    mode_id: str = Field(min_length=1, max_length=40)
    reason: str = Field(min_length=1, max_length=600)
    reason_code: Literal[
        "continue",
        "new_evidence",
        "boundary",
        "goal_accepted",
        "goal_completed",
        "goal_cancelled",
        "evidence_conflict",
        "context_changed",
    ] = "continue"
    evidence_refs: list[str] = Field(default_factory=list, max_length=12)
    goal_id: str | None = Field(default=None, max_length=160)


class MemoryRecord(CognitionContract):
    memory_id: str
    session_id: str
    npc_id: str
    kind: Literal["experience", "commitment", "summary", "belief"]
    content: str = Field(min_length=1, max_length=2000)
    source_event_ids: list[str] = Field(default_factory=list)
    source_turn_ids: list[str] = Field(default_factory=list)
    source_memory_ids: list[str] = Field(default_factory=list)
    entity_ids: list[str] = Field(default_factory=list)
    goal_ids: list[str] = Field(default_factory=list)
    epistemic_status: Literal[
        "reported", "observed", "verified", "inferred", "legacy_unverified"
    ] = "reported"
    validity: Literal["active", "dormant", "superseded", "disputed", "expired"] = "active"
    importance: float = Field(default=0.5, ge=0, le=1)
    activation: float = Field(default=1, ge=0, le=1)
    pinned: bool = False
    pin_reasons: list[str] = Field(default_factory=list)
    version: int = 0
    created_seq: int = 0
    reinforced_seq: int = 0


class MemoryLink(CognitionContract):
    source_id: str
    target_id: str
    relation: Literal[
        "same_event", "same_entity", "same_goal", "supports", "contradicts", "supersedes"
    ]


class MemoryInsight(CognitionContract):
    kind: Literal["summary", "belief"]
    content: str = Field(min_length=1, max_length=1000)
    source_memory_ids: list[str] = Field(min_length=1, max_length=12)
    supersedes: list[str] = Field(default_factory=list, max_length=8)
    contradicts: list[str] = Field(default_factory=list, max_length=8)


class MemoryConsolidation(CognitionContract):
    insights: list[MemoryInsight] = Field(default_factory=list, max_length=4)
