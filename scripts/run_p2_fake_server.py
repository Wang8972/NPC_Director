from __future__ import annotations

import argparse
import asyncio
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pydantic import ValidationError
from websockets.asyncio.server import ServerConnection, serve
from websockets.exceptions import ConnectionClosed

from npc_director.contracts import UNITY_MESSAGE_ADAPTER, ErrorMessage, ErrorPayload
from npc_director.prototype.fake_director import PrototypeFakeDirectorSession

MAX_MESSAGE_CHARS = 128_000


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="P2 deterministic Fake Director WebSocket backend (no API key required)"
    )
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8766)
    parser.add_argument("--session-id", default="p2-fake-001")
    parser.add_argument(
        "--database",
        type=Path,
        default=Path("artifacts/prototype-p2/p2-state.sqlite3"),
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("artifacts/prototype-p2/p2-report.json"),
    )
    parser.add_argument(
        "--keep-state",
        action="store_true",
        help="Keep an existing session instead of starting from the frozen initial state.",
    )
    return parser.parse_args()


def write_report(path: Path, session: PrototypeFakeDirectorSession) -> None:
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
    args.database.parent.mkdir(parents=True, exist_ok=True)
    session = PrototypeFakeDirectorSession(
        args.database,
        args.session_id,
        reset_on_start=not args.keep_state,
    )
    connection_lock = asyncio.Lock()

    async def handler(websocket: ServerConnection) -> None:
        if connection_lock.locked():
            error = ErrorMessage(
                message_id="error:duplicate_connection",
                payload=ErrorPayload(
                    code="duplicate_connection",
                    message="P2 permits one Unity socket for the session.",
                ),
            )
            await websocket.send(error.model_dump_json())
            await websocket.close(code=1008, reason="duplicate session connection")
            return
        async with connection_lock:
            print(f"[P2_SERVER] Unity connected session={args.session_id}")
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
                        responses = session.handle(message)
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
                    except Exception as error:  # preserve a useful manual-test failure
                        responses = [
                            ErrorMessage(
                                message_id="error:p2_internal_error",
                                payload=ErrorPayload(
                                    code="p2_internal_error",
                                    message=f"{type(error).__name__}: {error}",
                                ),
                            )
                        ]
                    await send_messages(websocket, responses)
                    write_report(args.output, session)
                    report = session.report()
                    print(
                        f"[P2_EVENT] status={report['status']} "
                        f"objective={report['current_objective_state']} "
                        f"interactions={report['interaction_types_seen']}"
                    )
            except ConnectionClosed as error:
                print(
                    f"[P2_SERVER] Unity connection closed "
                    f"code={error.code} reason={error.reason or 'none'}"
                )
            finally:
                write_report(args.output, session)
                print("[P2_SERVER] Unity disconnected; state and report saved")

    write_report(args.output, session)
    try:
        async with serve(handler, args.host, args.port):
            print(
                f"[P2_SERVER] waiting at ws://{args.host}:{args.port} "
                f"session={args.session_id} no_api_key=true"
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
        print("[P2_SERVER] stopped")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
