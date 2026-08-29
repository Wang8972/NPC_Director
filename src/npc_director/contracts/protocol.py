from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, model_validator

from npc_director.contracts.performance import PerformanceDirective
from npc_director.contracts.state import TurnRequest
from npc_director.contracts.workflow import EngineEvent


class ProtocolMessage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    message_id: str = Field(min_length=1, max_length=160)


class TurnRequestMessage(ProtocolMessage):
    type: Literal["turn.request"] = "turn.request"
    payload: TurnRequest


class PerformancePlanPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    directive: PerformanceDirective
    idempotency_key: str


class PerformancePlanMessage(ProtocolMessage):
    type: Literal["performance.plan"] = "performance.plan"
    payload: PerformancePlanPayload


class PerformanceEventMessage(ProtocolMessage):
    type: Literal[
        "performance.ack",
        "performance.started",
        "performance.completed",
        "performance.interrupted",
        "performance.error",
    ]
    payload: EngineEvent

    @model_validator(mode="after")
    def event_type_matches_message_type(self) -> PerformanceEventMessage:
        expected = f"performance.{self.payload.event_type.value}"
        if self.type != expected:
            raise ValueError(f"message type must be {expected!r} for this event")
        return self


class SceneObserveRequestPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    session_id: str = Field(min_length=1, max_length=120)
    request_id: str = Field(min_length=1, max_length=160)
    object_id: str = Field(min_length=1, max_length=80)
    expected_world_version: int = Field(ge=0)


class SceneObserveRequestMessage(ProtocolMessage):
    type: Literal["scene.observe.request"] = "scene.observe.request"
    payload: SceneObserveRequestPayload


class SceneActionCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["1.0"] = "1.0"
    session_id: str = Field(min_length=1, max_length=120)
    turn_id: str = Field(min_length=1, max_length=120)
    action_id: str = Field(min_length=1, max_length=160)
    actor_id: str = Field(min_length=1, max_length=80)
    action_type: str = Field(min_length=1, max_length=80)
    object_id: str | None = None
    item_id: str | None = None
    target_id: str | None = None
    target_npc_id: str | None = None
    operation: str | None = None
    basis_world_version: int = Field(ge=0)
    basis_npc_versions: dict[str, int] = Field(default_factory=dict)


class SceneActionPlanPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action: SceneActionCommand
    pre_commit_directive: PerformanceDirective
    idempotency_key: str = Field(min_length=1, max_length=160)


class SceneActionPlanMessage(ProtocolMessage):
    type: Literal["scene.action.plan"] = "scene.action.plan"
    payload: SceneActionPlanPayload


class SceneActionEventPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    session_id: str = Field(min_length=1, max_length=120)
    turn_id: str = Field(min_length=1, max_length=120)
    action_id: str = Field(min_length=1, max_length=160)
    idempotency_key: str = Field(min_length=1, max_length=160)
    event_type: Literal["ack", "started", "completed", "interrupted", "error"]
    detail: str | None = None
    occurred_at: datetime | None = None


class SceneActionEventMessage(ProtocolMessage):
    type: Literal[
        "scene.action.ack",
        "scene.action.started",
        "scene.action.completed",
        "scene.action.interrupted",
        "scene.action.error",
    ]
    payload: SceneActionEventPayload

    @model_validator(mode="after")
    def event_type_matches_message_type(self) -> SceneActionEventMessage:
        expected = f"scene.action.{self.payload.event_type}"
        if self.type != expected:
            raise ValueError(f"message type must be {expected!r} for this event")
        return self


class PrototypeObjectStatePayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    object_id: str
    state: str


class PrototypeItemLocationPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    item_id: str
    location_id: str


class PrototypeRouteFlagsPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    fuse_route: Literal["none", "cooperation", "procedure"] = "none"
    crate_c12_authorized: bool = False
    control_cabinet_authorized: bool = False


class PrototypePendingActionPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action_id: str
    actor_id: str
    action_type: str
    basis_world_version: int = Field(ge=0)


class StateSnapshotPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    session_id: str
    scene_id: Literal["prototype_gate_repair"]
    world_version: int = Field(ge=0)
    objective_state: str
    object_states: list[PrototypeObjectStatePayload]
    item_locations: list[PrototypeItemLocationPayload]
    discovered_fact_ids: list[str]
    route_flags: PrototypeRouteFlagsPayload
    pending_action: PrototypePendingActionPayload | None = None


class StateSnapshotMessage(ProtocolMessage):
    type: Literal["state.snapshot"] = "state.snapshot"
    payload: StateSnapshotPayload


class WorldEventPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    session_id: str = Field(min_length=1, max_length=120)
    event_id: str = Field(min_length=1, max_length=160)
    event_type: Literal[
        "observation_committed",
        "action_committed",
        "action_rejected",
        "action_cancelled",
        "session_reset",
    ]
    world_version: int = Field(ge=0)
    summary: str = Field(min_length=1, max_length=600)
    revealed_fact_ids: list[str] = Field(default_factory=list)


class WorldEventMessage(ProtocolMessage):
    type: Literal["world.event"] = "world.event"
    payload: WorldEventPayload


class PrototypeResetRequestPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    session_id: str = Field(min_length=1, max_length=120)
    reset_token: str = Field(min_length=1, max_length=160)


class PrototypeResetRequestMessage(ProtocolMessage):
    type: Literal["prototype.reset.request"] = "prototype.reset.request"
    payload: PrototypeResetRequestPayload


class ErrorPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str
    message: str
    turn_id: str | None = None


class ErrorMessage(ProtocolMessage):
    type: Literal["error"] = "error"
    payload: ErrorPayload


UnityMessage = Annotated[
    TurnRequestMessage
    | PerformancePlanMessage
    | PerformanceEventMessage
    | SceneObserveRequestMessage
    | SceneActionPlanMessage
    | SceneActionEventMessage
    | StateSnapshotMessage
    | WorldEventMessage
    | PrototypeResetRequestMessage
    | ErrorMessage,
    Field(discriminator="type"),
]
UNITY_MESSAGE_ADAPTER = TypeAdapter(UnityMessage)
