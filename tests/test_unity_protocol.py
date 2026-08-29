from __future__ import annotations

from dataclasses import dataclass, field

from fastapi.testclient import TestClient

from npc_director import __version__
from npc_director.api.app import create_app
from npc_director.contracts import (
    UNITY_MESSAGE_ADAPTER,
    ApprovalRecord,
    EngineEvent,
    PerformanceDirective,
    TurnExecutionResult,
    TurnStatus,
)


def directive(turn_id: str = "s1:1") -> PerformanceDirective:
    return PerformanceDirective.model_validate(
        {
            "session_id": "s1",
            "turn_id": turn_id,
            "npc_id": "elder_maren",
            "dialogue": {"text": "欢迎回来。"},
            "emotion": {"coarse": "joy", "primary": "warm"},
            "face_cues": [{"preset": "happy"}],
            "body_cues": [{"action": "small_nod"}],
            "runtime_meta": {
                "specialists_called": ["screenwriter", "performance"],
                "prompt_versions": ["director-v1"],
            },
        }
    )


@dataclass
class FakeTurnService:
    events: list[EngineEvent] = field(default_factory=list)

    async def run_turn(self, request, *, adapter):
        planned = directive(request.turn_id)
        receipt = await adapter.emit(planned)
        return TurnExecutionResult(
            turn_id=request.turn_id,
            status=TurnStatus.EMITTED if receipt.status == "sent" else TurnStatus.READY_TO_EMIT,
            directive=planned,
            idempotency_key=receipt.idempotency_key,
        )

    async def process_engine_event(self, event):
        self.events.append(event)
        return TurnExecutionResult(turn_id=event.turn_id, status=TurnStatus.COMPLETED)

    async def get_approval(self, approval_id: str) -> ApprovalRecord | None:
        return None

    async def resolve_approval(self, *args, **kwargs):
        raise KeyError(args[0])


def turn_request_message() -> dict:
    return {
        "message_id": "request-1",
        "type": "turn.request",
        "payload": {
            "session_id": "s1",
            "turn_id": "s1:1",
            "npc_id": "elder_maren",
            "player_input": "你好",
            "scene": {"location": "village_gate"},
            "character_core": "沉稳克制的长老",
        },
    }


def test_health_endpoint() -> None:
    app = create_app(FakeTurnService())
    client = TestClient(app)

    assert client.get("/health").json() == {"status": "ok"}
    assert app.version == __version__


def test_websocket_turn_and_engine_feedback_round_trip() -> None:
    service = FakeTurnService()
    client = TestClient(create_app(service))

    with client.websocket_connect("/ws/s1") as socket:
        socket.send_json(turn_request_message())
        plan = UNITY_MESSAGE_ADAPTER.validate_json(socket.receive_text())
        assert plan.type == "performance.plan"
        key = plan.payload.idempotency_key

        socket.send_json(
            {
                "message_id": "event-1",
                "type": "performance.completed",
                "payload": {
                    "session_id": "s1",
                    "turn_id": "s1:1",
                    "idempotency_key": key,
                    "event_type": "completed",
                },
            }
        )

    assert [event.event_type.value for event in service.events] == ["completed"]


def test_websocket_rejects_session_mismatch() -> None:
    client = TestClient(create_app(FakeTurnService()))
    message = turn_request_message()
    message["payload"]["session_id"] = "other"

    with client.websocket_connect("/ws/s1") as socket:
        socket.send_json(message)
        error = UNITY_MESSAGE_ADAPTER.validate_json(socket.receive_text())

    assert error.type == "error"
    assert error.payload.code == "session_mismatch"


def test_protocol_rejects_event_type_mismatch() -> None:
    message = {
        "message_id": "event-1",
        "type": "performance.ack",
        "payload": {
            "session_id": "s1",
            "turn_id": "s1:1",
            "idempotency_key": "key",
            "event_type": "completed",
        },
    }

    try:
        UNITY_MESSAGE_ADAPTER.validate_python(message)
    except ValueError as exc:
        assert "message type must be" in str(exc)
    else:
        raise AssertionError("mismatched event type was accepted")


def test_protocol_accepts_strict_prototype_state_snapshot() -> None:
    message = {
        "message_id": "snapshot-1",
        "type": "state.snapshot",
        "payload": {
            "session_id": "s1",
            "scene_id": "prototype_gate_repair",
            "world_version": 3,
            "objective_state": "prototype_success",
            "object_states": [
                {"object_id": "gate_console", "state": "online"},
                {"object_id": "generator", "state": "running"},
                {"object_id": "control_cabinet", "state": "restart_complete"},
                {"object_id": "cargo_crate_c12", "state": "sealed_anomaly"},
                {"object_id": "manifest_board", "state": "readable"},
                {"object_id": "alarm_lamp", "state": "solid_green"},
            ],
            "item_locations": [{"item_id": "spare_fuse", "location_id": "generator"}],
            "discovered_fact_ids": ["fact_fuse_installed", "fact_gate_restarted"],
            "route_flags": {
                "fuse_route": "cooperation",
                "crate_c12_authorized": False,
                "control_cabinet_authorized": True,
            },
            "pending_action": None,
        },
    }

    parsed = UNITY_MESSAGE_ADAPTER.validate_python(message)

    assert parsed.type == "state.snapshot"
    assert parsed.payload.world_version == 3
    assert len(parsed.payload.object_states) == 6


def test_protocol_accepts_scene_action_lifecycle_and_rejects_type_mismatch() -> None:
    event = {
        "message_id": "scene-event-1",
        "type": "scene.action.completed",
        "payload": {
            "session_id": "s1",
            "turn_id": "s1:1",
            "action_id": "s1:1:a1",
            "idempotency_key": "key",
            "event_type": "completed",
        },
    }
    parsed = UNITY_MESSAGE_ADAPTER.validate_python(event)
    assert parsed.payload.action_id == "s1:1:a1"

    event["type"] = "scene.action.started"
    try:
        UNITY_MESSAGE_ADAPTER.validate_python(event)
    except ValueError as exc:
        assert "message type must be" in str(exc)
    else:
        raise AssertionError("mismatched scene action event type was accepted")


def test_protocol_accepts_observe_reset_and_committed_world_event() -> None:
    messages = [
        {
            "message_id": "observe-1",
            "type": "scene.observe.request",
            "payload": {
                "session_id": "s1",
                "request_id": "observe-request-1",
                "object_id": "gate_console",
                "expected_world_version": 0,
            },
        },
        {
            "message_id": "reset-1",
            "type": "prototype.reset.request",
            "payload": {"session_id": "s1", "reset_token": "p2-reset-1"},
        },
        {
            "message_id": "world-1",
            "type": "world.event",
            "payload": {
                "session_id": "s1",
                "event_id": "event-1",
                "event_type": "action_committed",
                "world_version": 1,
                "summary": "committed",
                "revealed_fact_ids": ["fact_console_e17"],
            },
        },
    ]
    assert [UNITY_MESSAGE_ADAPTER.validate_python(item).type for item in messages] == [
        "scene.observe.request",
        "prototype.reset.request",
        "world.event",
    ]
