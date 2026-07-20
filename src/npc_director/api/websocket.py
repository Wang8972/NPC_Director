from __future__ import annotations

from typing import Protocol

from fastapi import WebSocket, WebSocketDisconnect
from pydantic import ValidationError

from npc_director.contracts import (
    UNITY_MESSAGE_ADAPTER,
    ApprovalRecord,
    EngineEvent,
    ErrorMessage,
    ErrorPayload,
    PerformanceDirective,
    PerformanceEventMessage,
    TurnExecutionResult,
    TurnRequest,
    TurnRequestMessage,
)
from npc_director.unity_adapter import WebSocketEngineAdapter, WebSocketHub

MAX_MESSAGE_CHARS = 128_000


class TurnService(Protocol):
    async def run_turn(
        self,
        request: TurnRequest,
        *,
        adapter: WebSocketEngineAdapter,
    ) -> TurnExecutionResult: ...

    async def process_engine_event(self, event: EngineEvent) -> TurnExecutionResult | None: ...

    async def get_approval(self, approval_id: str) -> ApprovalRecord | None: ...

    async def resolve_approval(
        self,
        approval_id: str,
        *,
        action: str,
        reviewer: str,
        comment: str | None,
        edited_directive: PerformanceDirective | None,
        adapter: WebSocketEngineAdapter,
    ) -> TurnExecutionResult: ...


async def send_error(
    websocket: WebSocket,
    *,
    message_id: str,
    code: str,
    message: str,
    turn_id: str | None = None,
) -> None:
    payload = ErrorMessage(
        message_id=message_id,
        payload=ErrorPayload(code=code, message=message, turn_id=turn_id),
    )
    await websocket.send_text(payload.model_dump_json())


async def handle_unity_socket(
    websocket: WebSocket,
    *,
    session_id: str,
    service: TurnService,
    hub: WebSocketHub,
    adapter: WebSocketEngineAdapter,
) -> None:
    await websocket.accept()
    await hub.register(session_id, websocket)
    try:
        dispatcher = getattr(service, "dispatch_outbox", None)
        if callable(dispatcher):
            await dispatcher(adapter, session_id=session_id)
        while True:
            raw_message = await websocket.receive_text()
            if len(raw_message) > MAX_MESSAGE_CHARS:
                await send_error(
                    websocket,
                    message_id="error:message_too_large",
                    code="message_too_large",
                    message="message exceeds protocol size limit",
                )
                continue
            try:
                message = UNITY_MESSAGE_ADAPTER.validate_json(raw_message)
            except ValidationError as exc:
                await send_error(
                    websocket,
                    message_id="error:invalid_message",
                    code="invalid_message",
                    message=str(exc),
                )
                continue

            if isinstance(message, TurnRequestMessage):
                request = message.payload
                if request.session_id != session_id:
                    await send_error(
                        websocket,
                        message_id=f"error:{message.message_id}",
                        code="session_mismatch",
                        message="payload session_id does not match websocket path",
                        turn_id=request.turn_id,
                    )
                    continue
                try:
                    result = await service.run_turn(request, adapter=adapter)
                except Exception:
                    await send_error(
                        websocket,
                        message_id=f"error:{message.message_id}",
                        code="turn_failed",
                        message="turn processing failed",
                        turn_id=request.turn_id,
                    )
                    continue
                if result.status.value == "pending_approval":
                    await send_error(
                        websocket,
                        message_id=f"status:{message.message_id}",
                        code="pending_approval",
                        message=result.approval_id or "approval required",
                        turn_id=result.turn_id,
                    )
                elif result.status.value == "failed":
                    await send_error(
                        websocket,
                        message_id=f"error:{message.message_id}",
                        code="turn_failed",
                        message="turn failed governance checks",
                        turn_id=result.turn_id,
                    )
                continue

            if isinstance(message, PerformanceEventMessage):
                event = message.payload
                if event.session_id != session_id:
                    await send_error(
                        websocket,
                        message_id=f"error:{message.message_id}",
                        code="session_mismatch",
                        message="event session_id does not match websocket path",
                        turn_id=event.turn_id,
                    )
                    continue
                try:
                    await service.process_engine_event(event)
                except Exception:
                    await send_error(
                        websocket,
                        message_id=f"error:{message.message_id}",
                        code="event_rejected",
                        message="engine event rejected",
                        turn_id=event.turn_id,
                    )
                continue

            await send_error(
                websocket,
                message_id=f"error:{message.message_id}",
                code="unsupported_direction",
                message="message type is server-to-client only",
            )
    except WebSocketDisconnect:
        pass
    finally:
        await hub.unregister(session_id, websocket)
