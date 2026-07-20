from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Literal

from fastapi import FastAPI, HTTPException, WebSocket
from pydantic import BaseModel, ConfigDict, Field

from npc_director import __version__
from npc_director.api.websocket import TurnService, handle_unity_socket
from npc_director.contracts import PerformanceDirective
from npc_director.unity_adapter import WebSocketEngineAdapter, WebSocketHub


class ApprovalResolutionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action: Literal["approve", "reject", "edit"]
    reviewer: str = Field(min_length=1, max_length=120)
    comment: str | None = Field(default=None, max_length=1_000)
    edited_directive: PerformanceDirective | None = None


def create_app(
    service: TurnService | None = None,
    *,
    hub: WebSocketHub | None = None,
) -> FastAPI:
    resolved_hub = hub or WebSocketHub()
    adapter = WebSocketEngineAdapter(resolved_hub)
    if service is None:
        from npc_director.orchestration.service import build_default_service

        service = build_default_service()

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        recover = getattr(service, "recover_incomplete_events", None)
        if callable(recover):
            await recover()
        yield

    app = FastAPI(title="NPC Director", version=__version__, lifespan=lifespan)
    app.state.turn_service = service
    app.state.websocket_hub = resolved_hub
    app.state.engine_adapter = adapter

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.websocket("/ws/{session_id}")
    async def unity_websocket(websocket: WebSocket, session_id: str) -> None:
        await handle_unity_socket(
            websocket,
            session_id=session_id,
            service=service,
            hub=resolved_hub,
            adapter=adapter,
        )

    @app.get("/approvals/{approval_id}")
    async def get_approval(approval_id: str):
        approval = await service.get_approval(approval_id)
        if approval is None:
            raise HTTPException(status_code=404, detail="approval not found")
        return approval

    @app.post("/approvals/{approval_id}")
    async def resolve_approval(approval_id: str, request: ApprovalResolutionRequest):
        try:
            return await service.resolve_approval(
                approval_id,
                action=request.action,
                reviewer=request.reviewer,
                comment=request.comment,
                edited_directive=request.edited_directive,
                adapter=adapter,
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="approval not found") from exc
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    return app
