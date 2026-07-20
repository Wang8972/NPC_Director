from __future__ import annotations

import asyncio
from typing import Protocol

from npc_director.contracts import (
    EngineEmitReceipt,
    PerformanceDirective,
    PerformancePlanMessage,
)
from npc_director.contracts.protocol import PerformancePlanPayload
from npc_director.unity_adapter.base import build_idempotency_key


class TextWebSocket(Protocol):
    async def send_text(self, data: str) -> None: ...


class WebSocketHub:
    def __init__(self) -> None:
        self._connections: dict[str, TextWebSocket] = {}
        self._lock = asyncio.Lock()

    async def register(self, session_id: str, websocket: TextWebSocket) -> None:
        async with self._lock:
            self._connections[session_id] = websocket

    async def unregister(self, session_id: str, websocket: TextWebSocket) -> None:
        async with self._lock:
            if self._connections.get(session_id) is websocket:
                self._connections.pop(session_id, None)

    async def send(self, session_id: str, payload: str) -> bool:
        async with self._lock:
            websocket = self._connections.get(session_id)
        if websocket is None:
            return False
        await websocket.send_text(payload)
        return True

    async def is_connected(self, session_id: str) -> bool:
        async with self._lock:
            return session_id in self._connections


class WebSocketEngineAdapter:
    def __init__(self, hub: WebSocketHub) -> None:
        self.hub = hub

    async def emit(self, directive: PerformanceDirective) -> EngineEmitReceipt:
        idempotency_key = build_idempotency_key(directive)
        message = PerformancePlanMessage(
            message_id=f"plan:{idempotency_key}",
            payload=PerformancePlanPayload(
                directive=directive,
                idempotency_key=idempotency_key,
            ),
        )
        sent = await self.hub.send(directive.session_id, message.model_dump_json())
        if not sent:
            return EngineEmitReceipt(
                turn_id=directive.turn_id,
                idempotency_key=idempotency_key,
                status="queued",
                detail="Unity session is not connected",
            )

        return EngineEmitReceipt(
            turn_id=directive.turn_id,
            idempotency_key=idempotency_key,
            status="sent",
        )
