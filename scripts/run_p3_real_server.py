from __future__ import annotations

import argparse
import asyncio
import dataclasses
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pydantic import ValidationError
from websockets.asyncio.server import ServerConnection, serve
from websockets.exceptions import ConnectionClosed

from npc_director.config import Settings
from npc_director.contracts import UNITY_MESSAGE_ADAPTER, ErrorMessage, ErrorPayload
from npc_director.prototype.real_director import PrototypeRealDirectorSession

MAX_MESSAGE_CHARS = 128_000


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="P3 Real NPC Director WebSocket backend"
    )
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8767)
    parser.add_argument("--session-id", default="p3-real-001")
    parser.add_argument("--model", default=None)
    parser.add_argument("--model-profile", default=None)
    parser.add_argument("--timeout-seconds", type=float, default=None)
    parser.add_argument(
        "--database",
        type=Path,
        default=Path("artifacts/prototype-p3/p3-state.sqlite3"),
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("artifacts/prototype-p3/p3-report.json"),
    )
    parser.add_argument(
        "--keep-state",
        action="store_true",
        help="Keep an existing session instead of starting from the frozen initial state.",
    )
    return parser.parse_args()


def settings_from_args(args: argparse.Namespace) -> Settings:
    settings = Settings.from_env()
    updates: dict[str, Any] = {}
    if args.model:
        updates["model"] = args.model
        updates["director_model"] = args.model
    if args.model_profile:
        updates["model_profile"] = args.model_profile
    if args.timeout_seconds is not None:
        updates["timeout_seconds"] = args.timeout_seconds
    resolved = dataclasses.replace(settings, **updates)
    resolved.validate()
    return resolved


def write_report(path: Path, session: PrototypeRealDirectorSession) -> None:
    report = session.report()
    report["recorded_at"] = datetime.now(UTC).isoformat()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


async def send_messages(websocket: ServerConnection, messages: list[Any]) -> None:
    for message in messages:
        await websocket.send(message.model_dump_json())


async def run_server(args: argparse.Namespace) -> None:
    settings = settings_from_args(args)
    args.database.parent.mkdir(parents=True, exist_ok=True)
    session = PrototypeRealDirectorSession(
        args.database,
        args.session_id,
        settings=settings,
        reset_on_start=not args.keep_state,
    )
    connection_lock = asyncio.Lock()

    async def handler(websocket: ServerConnection) -> None:
        if connection_lock.locked():
            error = ErrorMessage(
                message_id="error:duplicate_connection",
                payload=ErrorPayload(
                    code="duplicate_connection",
                    message="P3 permits one Unity socket for the session.",
                ),
            )
            await websocket.send(error.model_dump_json())
            await websocket.close(code=1008, reason="duplicate session connection")
            return
        async with connection_lock:
            print(f"[P3_SERVER] Unity connected session={args.session_id}")
            await send_messages(websocket, session.initial_messages())
            try:
                async for raw in websocket:
                    if not isinstance(raw, str) or len(raw) > MAX_MESSAGE_CHARS:
                        error = ErrorMessage(
                            message_id="error:message_too_large",
                            payload=ErrorPayload(
                                code="message_too_large",
                                message="message exceeds protocol size limit",
                            ),
                        )
                        await websocket.send(error.model_dump_json())
                        continue
                    try:
                        message = UNITY_MESSAGE_ADAPTER.validate_json(raw)
                        responses = await session.handle_async(message)
                    except ValidationError as error:
                        responses = [
                            ErrorMessage(
                                message_id="error:invalid_message",
                                payload=ErrorPayload(
                                    code="invalid_message",
                                    message=str(error),
                                ),
                            )
                        ]
                    except Exception as error:  # retain actionable live-model failure details
                        responses = [
                            ErrorMessage(
                                message_id="error:p3_internal_error",
                                payload=ErrorPayload(
                                    code="p3_internal_error",
                                    message=f"{type(error).__name__}: {error}",
                                ),
                            )
                        ]
                    await send_messages(websocket, responses)
                    write_report(args.output, session)
                    report = session.report()
                    print(
                        f"[P3_EVENT] status={report['status']} "
                        f"objective={report['current_objective_state']} "
                        f"models={report['models']} calls={report['model_call_count']}"
                    )
            except ConnectionClosed as error:
                print(
                    f"[P3_SERVER] Unity connection closed "
                    f"code={error.code} reason={error.reason or 'none'}"
                )
            finally:
                write_report(args.output, session)
                print("[P3_SERVER] Unity disconnected; state and report saved")

    write_report(args.output, session)
    try:
        async with serve(handler, args.host, args.port):
            model = settings.model_for("director") or "agents-sdk-default"
            print(
                f"[P3_SERVER] waiting at ws://{args.host}:{args.port} "
                f"session={args.session_id} mode=real model={model}"
            )
            await asyncio.Future()
    finally:
        write_report(args.output, session)
        session.close()


def main() -> int:
    args = parse_args()
    try:
        asyncio.run(run_server(args))
    except KeyboardInterrupt:
        print("[P3_SERVER] stopped")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
