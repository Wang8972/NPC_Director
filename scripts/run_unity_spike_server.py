from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from websockets.asyncio.server import ServerConnection, serve

NPC_IDS = (
    "guard_captain_maren",
    "mechanic_lia",
    "porter_finn",
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Fake WebSocket backend for Unity Spike S1")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--session-id", default="spike-unity-001")
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("artifacts/prototype-spikes/unity-s1-report.json"),
    )
    return parser.parse_args()


def performance_plan(session_id: str, npc_id: str, index: int) -> dict[str, Any]:
    turn_id = f"{session_id}:s1:{index:02d}"
    key = hashlib.sha256(f"{session_id}:{turn_id}:{npc_id}".encode()).hexdigest()
    return {
        "message_id": f"s1-plan:{index:02d}",
        "type": "performance.plan",
        "payload": {
            "directive": {
                "schema_version": "1.0",
                "session_id": session_id,
                "turn_id": turn_id,
                "npc_id": npc_id,
                "dialogue": {
                    "text": f"S1 route check {index:02d} for {npc_id}",
                    "language": "en",
                    "voice_style": "neutral",
                },
                "emotion": {
                    "coarse": "neutral",
                    "primary": "calm",
                    "secondary": None,
                    "intensity": 0.5,
                    "valence": 0.0,
                    "arousal": 0.0,
                },
                "face_cues": [],
                "body_cues": [],
                "gaze": {"target": "player_head", "mode": "direct"},
                "interrupt_policy": "allow_any",
                "confidence": 1.0,
                "evidence": {"lore_refs": []},
                "runtime_meta": {
                    "specialists_called": ["baseline"],
                    "prompt_versions": ["unity-s1-fixture-v1"],
                    "model": "fake-unity-spike",
                    "trace_id": f"s1-trace-{index:02d}",
                    "response_id": f"s1-response-{index:02d}",
                },
            },
            "idempotency_key": key,
        },
    }


async def wait_for_terminal(
    websocket: ServerConnection,
    turn_id: str,
    *,
    timeout_seconds: float = 15,
) -> dict[str, Any]:
    while True:
        raw = await asyncio.wait_for(websocket.recv(), timeout=timeout_seconds)
        message = json.loads(raw)
        payload = message.get("payload") or {}
        if payload.get("turn_id") != turn_id:
            continue
        if message.get("type") in {"performance.completed", "performance.error"}:
            return message


async def run_server(args: argparse.Namespace) -> dict[str, Any]:
    done = asyncio.Event()
    connections = 0
    report: dict[str, Any] = {
        "spike": "S1",
        "status": "fail",
        "session_id": args.session_id,
        "connection_count": 0,
        "legal_completed": 0,
        "route_counts": {npc_id: 0 for npc_id in NPC_IDS},
        "unknown_npc_rejected": False,
        "errors": [],
    }

    async def handler(websocket: ServerConnection) -> None:
        nonlocal connections
        connections += 1
        report["connection_count"] = connections
        if connections > 1:
            report["errors"].append("more than one session socket connected")
        print(f"[S1_SERVER] Unity connected; connection_count={connections}")
        try:
            index = 0
            for _ in range(10):
                for npc_id in NPC_IDS:
                    index += 1
                    plan = performance_plan(args.session_id, npc_id, index)
                    await websocket.send(json.dumps(plan, separators=(",", ":")))
                    terminal = await wait_for_terminal(
                        websocket,
                        plan["payload"]["directive"]["turn_id"],
                    )
                    if terminal["type"] != "performance.completed":
                        report["errors"].append(
                            f"legal plan failed: {npc_id} index={index} terminal={terminal['type']}"
                        )
                        continue
                    report["legal_completed"] += 1
                    report["route_counts"][npc_id] += 1
                    print(f"[S1_SERVER] completed {index:02d}/30 npc_id={npc_id}")

            unknown = performance_plan(args.session_id, "unknown_npc", 31)
            await websocket.send(json.dumps(unknown, separators=(",", ":")))
            terminal = await wait_for_terminal(
                websocket,
                unknown["payload"]["directive"]["turn_id"],
            )
            detail = str((terminal.get("payload") or {}).get("detail") or "")
            report["unknown_npc_rejected"] = (
                terminal.get("type") == "performance.error" and "unknown npc_id" in detail
            )
        except Exception as error:  # noqa: BLE001 - evidence report must retain runtime failures
            report["errors"].append(f"{type(error).__name__}: {error}")
        finally:
            passed = (
                report["connection_count"] == 1
                and report["legal_completed"] == 30
                and all(value == 10 for value in report["route_counts"].values())
                and report["unknown_npc_rejected"]
                and not report["errors"]
            )
            report["status"] = "pass" if passed else "fail"
            report["recorded_at"] = datetime.now(UTC).isoformat()
            print(
                f"[S1_SUMMARY] {report['status'].upper()} "
                f"legal={report['legal_completed']}/30 routes={report['route_counts']} "
                f"unknown_rejected={report['unknown_npc_rejected']} "
                f"connections={report['connection_count']}"
            )
            done.set()

    async with serve(handler, args.host, args.port):
        print(f"[S1_SERVER] waiting at ws://{args.host}:{args.port}")
        await done.wait()
    return report


def main() -> int:
    args = parse_args()
    report = asyncio.run(run_server(args))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return 0 if report["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
