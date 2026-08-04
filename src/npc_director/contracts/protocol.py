from __future__ import annotations

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


class StateSnapshotPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    session_id: str
    scene_id: Literal["prototype_gate_repair"]
    world_version: int = Field(ge=0)
    objective_state: str
    object_states: list[PrototypeObjectStatePayload]
    item_locations: list[PrototypeItemLocationPayload]
    route_flags: PrototypeRouteFlagsPayload


class StateSnapshotMessage(ProtocolMessage):
    type: Literal["state.snapshot"] = "state.snapshot"
    payload: StateSnapshotPayload


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
    | StateSnapshotMessage
    | ErrorMessage,
    Field(discriminator="type"),
]
UNITY_MESSAGE_ADAPTER = TypeAdapter(UnityMessage)
