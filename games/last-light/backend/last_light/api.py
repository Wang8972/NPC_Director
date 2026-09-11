"""Local authoritative HTTP adapter for the Unity player and mock client.

No request can submit a world snapshot or promote a player's assertion to fact.
AI jobs and physical execution have different completion acknowledgements.
"""
from __future__ import annotations

import asyncio
import json
import os
import re
import shutil
import tempfile
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Literal

from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from . import __version__
from .engine import WorldEngine
from .repository import Repository
from .director import DirectorUnavailable, TokenBudgetExceeded
from .director_contracts import PerformanceEventRequest


class Request(BaseModel):
    model_config = ConfigDict(extra="forbid")


class NewSession(Request):
    mode: Literal["live", "rehearsal"] = "live"


class RevisionRequest(Request):
    expected_revision: int = Field(ge=0)


class MoveRequest(RevisionRequest):
    room_id: str = Field(min_length=1, max_length=40)


class InspectRequest(RevisionRequest):
    target_id: str = Field(min_length=1, max_length=80)


class StepRequest(Request):
    id: str = ""
    action_id: str = Field(min_length=1, max_length=80)
    actor_id: str = ""
    target_id: str = ""
    helpers: list[str] = Field(default_factory=list, max_length=4)
    depends_on: list[str] = Field(default_factory=list, max_length=12)
    # Shared display DTO fields are accepted for roundtripping, never trusted as input.
    status: str = ""
    reason: str = ""
    duration: int = 0


class PlanRequest(RevisionRequest):
    title: str = Field(default="", max_length=200)
    steps: list[StepRequest] = Field(min_length=1, max_length=12)


class PlanIdRequest(RevisionRequest):
    plan_id: str = Field(min_length=1, max_length=120)


class CompleteRequest(RevisionRequest):
    execution_id: str = Field(min_length=1, max_length=160)


class TalkRequest(RevisionRequest):
    npc_id: Literal["lin", "zhou", "chen", "xu"]
    text: str = Field(default="", max_length=2000)
    topic_id: str = Field(default="", max_length=100)
    audience: list[str] = Field(default_factory=list, max_length=4)


class AckRequest(Request):
    line_id: str = Field(min_length=1, max_length=240)


class EmptyRequest(Request):
    pass


def default_data_dir() -> Path:
    explicit = os.getenv("LAST_LIGHT_DATA_DIR")
    if explicit:
        return Path(explicit).expanduser().resolve()
    if os.name == "nt":
        return Path(os.getenv("LOCALAPPDATA", str(Path.home()))) / "LastLight" / "saves"
    return Path.home() / "Library" / "Application Support" / "LastLight" / "saves"


def create_app(data_dir: Path | str | None = None, director_factory=None) -> FastAPI:
    root = Path(data_dir or default_data_dir())
    root.mkdir(parents=True, exist_ok=True)
    repo = Repository(root / "world")
    engines: dict[str, WorldEngine] = {}
    locks: dict[str, asyncio.Lock] = {}
    completion_receipts: dict[tuple[str, str], bool] = {}

    def engine(sid: str) -> WorldEngine:
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,100}", sid):
            raise HTTPException(400, "Invalid session ID")
        if sid not in engines:
            try:
                engines[sid] = repo.get(sid)
            except (ValueError, KeyError, FileNotFoundError) as exc:
                raise HTTPException(404, "Session not found") from exc
        return engines[sid]

    def persist(sid: str) -> None:
        repo.save(engine(sid))

    if director_factory is None:
        from .director import DirectorBridge
        director_factory = DirectorBridge
    bridge = director_factory(root, engine, persist)
    @asynccontextmanager
    async def lifespan(_app):
        yield
        if hasattr(bridge, "close"):
            await bridge.close()

    app = FastAPI(title="Last Light / 余灯", version=__version__, lifespan=lifespan)
    app.state.repository, app.state.engines, app.state.bridge = repo, engines, bridge
    app.state.data_dir = root

    def lock(sid: str) -> asyncio.Lock:
        return locks.setdefault(sid, asyncio.Lock())

    def active(sid: str) -> bool:
        return bool(bridge.has_active_job(sid)) if hasattr(bridge, "has_active_job") else False

    def reply(sid: str, result: dict | None = None, job: dict | None = None) -> dict:
        payload = dict(result or {})
        payload.setdefault("ok", True)
        payload.setdefault("error", "")
        payload["session_id"] = sid
        payload.setdefault("view", engine(sid).view())
        if hasattr(bridge, "present_view") and payload.get("view") is not None:
            payload["view"] = bridge.present_view(sid, payload["view"])
        payload["job"] = job if job is not None else (
            bridge.get_active_job(sid) if hasattr(bridge, "get_active_job") else None)
        return payload

    def check(sid: str, revision: int, *, idle: bool = True) -> WorldEngine:
        world = engine(sid)
        if world.state["revision"] != revision:
            raise HTTPException(409, "局势已经更新，请按最新状态重新安排。")
        if idle and active(sid):
            raise HTTPException(409, "请先读完当前回应，或取消这次协商。")
        return world

    async def world_changed(sid: str, result: dict) -> dict:
        persist(sid)
        job = None
        if engine(sid).state.get("mode") == "live":
            await bridge.sync_world(sid)
            if hasattr(bridge, "get_active_job"):
                job = bridge.get_active_job(sid)
        return reply(sid, result, job)

    @app.exception_handler(ValueError)
    async def value_error(_request, exc):
        return JSONResponse(status_code=400, content={"ok": False, "error": str(exc), "view": None, "job": None})

    @app.exception_handler(DirectorUnavailable)
    @app.exception_handler(TokenBudgetExceeded)
    async def director_unavailable(_request, exc):
        return JSONResponse(status_code=503, content={"ok": False, "error": str(exc), "view": None, "job": None})

    @app.exception_handler(HTTPException)
    async def http_error(_request, exc):
        return JSONResponse(status_code=exc.status_code, content={"ok": False, "error": str(exc.detail), "view": None, "job": None})

    @app.get("/health")
    async def health():
        info = bridge.available()
        ready = bool(info.get("ready", info.get("available", info.get("ok", False))))
        return {"ok": True, "app_id": "last-light", "version": __version__, "director_ready": ready, "director": info,
                "error": "", "message": "真实 AI" if ready else "服务已就绪；AI 连接尚未配置，可使用离线演练。"}

    @app.get("/sessions")
    async def sessions():
        return {"ok": True, "sessions": repo.list_sessions()}

    @app.post("/sessions")
    async def new_session(request: NewSession):
        world = repo.create(mode=request.mode)
        sid = world.state["session_id"]
        engines[sid] = world
        return reply(sid)

    @app.get("/sessions/{sid}")
    async def get_session(sid: str):
        return reply(sid)

    @app.post("/sessions/{sid}/move")
    async def move(sid: str, request: MoveRequest):
        async with lock(sid):
            result = check(sid, request.expected_revision).move(request.room_id)
            return await world_changed(sid, result)

    @app.post("/sessions/{sid}/inspect")
    async def inspect(sid: str, request: InspectRequest):
        async with lock(sid):
            result = check(sid, request.expected_revision).inspect(request.target_id)
            return await world_changed(sid, result)

    @app.post("/sessions/{sid}/plan")
    async def plan(sid: str, request: PlanRequest):
        async with lock(sid):
            result = check(sid, request.expected_revision).propose(
                [step.model_dump(include={"id", "action_id", "actor_id", "target_id", "helpers", "depends_on"})
                 for step in request.steps], request.title)
            persist(sid)
            return reply(sid, result)

    @app.post("/sessions/{sid}/begin")
    async def begin(sid: str, request: PlanIdRequest):
        async with lock(sid):
            result = check(sid, request.expected_revision).begin(request.plan_id)
            persist(sid)
            return reply(sid, result)

    @app.post("/sessions/{sid}/complete")
    async def complete(sid: str, request: CompleteRequest):
        async with lock(sid):
            world = engine(sid)
            key = (sid, request.execution_id)
            # On reconnect, ask the durable engine to acknowledge a previously completed batch.
            pending = world.view().get("execution")
            if key in completion_receipts or not pending or pending.get("id") != request.execution_id:
                result = world.complete(request.execution_id)
                return reply(sid, result)
            check(sid, request.expected_revision)
            result = world.complete(request.execution_id)
            if result.get("ok", True):
                completion_receipts[key] = True
            return await world_changed(sid, result)

    @app.post("/sessions/{sid}/cancel")
    async def cancel_plan(sid: str, request: PlanIdRequest):
        async with lock(sid):
            result = check(sid, request.expected_revision).cancel(request.plan_id)
            persist(sid)
            return reply(sid, result)

    @app.post("/sessions/{sid}/talk")
    async def talk(sid: str, request: TalkRequest):
        async with lock(sid):
            world = check(sid, request.expected_revision, idle=False)
            if world.state.get("ending"):
                raise HTTPException(409, "本次救援已经结束。可以查看后记或恢复检查点，不能继续创建新行动。")
            if not request.text.strip() and not request.topic_id:
                raise HTTPException(400, "请输入想说的话。")
            if world.view().get("execution"):
                raise HTTPException(409, "行动尚在执行，完成或取消后再交谈。")
            if world.state.get("mode") == "rehearsal":
                job = await bridge.start_rehearsal(sid, request.npc_id, request.text, request.topic_id)
                persist(sid)
                return reply(sid, job=job)
            await bridge.sync_world(sid)
            job = await bridge.start(sid, request.npc_id, request.text, request.audience)
            return reply(sid, job=job)

    @app.get("/sessions/{sid}/talk/{job_id}")
    async def get_job(sid: str, job_id: str):
        engine(sid)
        job = bridge.get_job(sid, job_id)
        return reply(sid, job=job)

    @app.post("/sessions/{sid}/talk/{job_id}/performance-events")
    async def performance_events(sid: str, job_id: str, request: PerformanceEventRequest):
        async with lock(sid):
            engine(sid)
            job = await bridge.performance_event(sid, job_id, request)
            persist(sid)
            response = reply(sid, job=job)
            response["delivery_protocol"] = "performance_events"
            return response

    @app.post("/sessions/{sid}/talk/{job_id}/ack")
    async def ack(sid: str, job_id: str, request: AckRequest):
        async with lock(sid):
            engine(sid)
            job = await bridge.acknowledge(sid, job_id, request.line_id)
            persist(sid)
            response = reply(sid, job=job)
            response.update(legacy=True, delivery_protocol="legacy_ack")
            return response

    @app.post("/sessions/{sid}/talk/{job_id}/cancel")
    async def cancel_job(sid: str, job_id: str):
        async with lock(sid):
            engine(sid)
            job = await bridge.cancel(sid, job_id)
            persist(sid)
            return reply(sid, job=job)

    @app.post("/sessions/{sid}/save")
    async def save(sid: str):
        async with lock(sid):
            world = engine(sid)
            if active(sid) or world.view().get("execution"):
                raise HTTPException(409, "请先完成或取消当前协商与执行，再保存检查点。")
            parent = root / "checkpoints"
            parent.mkdir(parents=True, exist_ok=True)
            temporary = Path(tempfile.mkdtemp(prefix=sid + "_", dir=parent))
            destination, previous = parent / sid, parent / (sid + "_previous")
            try:
                (temporary / "world.json").write_text(json.dumps(world.state, ensure_ascii=False), encoding="utf-8")
                await bridge.checkpoint(sid, temporary / "director")
                if previous.exists():
                    shutil.rmtree(previous)
                if destination.exists():
                    destination.rename(previous)
                temporary.rename(destination)
            except Exception:
                shutil.rmtree(temporary, ignore_errors=True)
                if not destination.exists() and previous.exists():
                    previous.rename(destination)
                raise
            persist(sid)
            return reply(sid)

    @app.post("/sessions/{sid}/restore")
    async def restore(sid: str):
        async with lock(sid):
            world = engine(sid)
            checkpoint = root / "checkpoints" / sid
            if not (checkpoint / "world.json").is_file():
                raise HTTPException(404, "这一局还没有手动检查点；当前进度已自动保存。")
            saved = json.loads((checkpoint / "world.json").read_text(encoding="utf-8"))
            # Validate before touching either store, then invalidate requests from the old timeline.
            restored = WorldEngine(state=saved)
            restored.state["revision"] = max(world.state["revision"], saved["revision"]) + 1
            await bridge.restore_checkpoint(sid, checkpoint / "director")
            engines[sid] = restored
            persist(sid)
            for key in list(completion_receipts):
                if key[0] == sid:
                    completion_receipts.pop(key)
            return reply(sid)

    return app


app = create_app()
