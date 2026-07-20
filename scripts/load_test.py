from __future__ import annotations

import argparse
import asyncio
import json
import math
import tempfile
import time
from pathlib import Path

from npc_director.config import Settings
from npc_director.contracts import EngineEmitReceipt, TurnRequest
from npc_director.orchestration.context_adapter import DefaultContextBuilder
from npc_director.orchestration.service import NPCDirectorService
from npc_director.orchestration.testing import DeterministicDirectorExecutor
from npc_director.state import ApprovalStore, DomainStateStore, EventLog, OutboxStore, TurnStore
from npc_director.unity_adapter.base import build_idempotency_key


class NoopAdapter:
    async def emit(self, directive):
        return EngineEmitReceipt(
            turn_id=directive.turn_id,
            idempotency_key=build_idempotency_key(directive),
            status="sent",
        )


def percentile(values: list[float], quantile: float) -> float:
    ordered = sorted(values)
    index = max(0, math.ceil(len(ordered) * quantile) - 1)
    return ordered[index]


async def run_load_profile(
    *,
    turns: int = 100,
    concurrency: int = 10,
    database: Path | None = None,
) -> dict[str, float | int]:
    if turns < 1 or concurrency < 1:
        raise ValueError("turns and concurrency must be positive")
    if database is None:
        temporary = tempfile.TemporaryDirectory()
        database = Path(temporary.name) / "load.db"
    else:
        temporary = None
    settings = Settings(database_path=database)
    turn_store = TurnStore(database)
    service = NPCDirectorService(
        settings,
        executor=DeterministicDirectorExecutor(),
        context_builder=DefaultContextBuilder(),
        turn_store=turn_store,
        domain_store=DomainStateStore(database),
        event_log=EventLog(database),
        approval_store=ApprovalStore(database, turn_store=turn_store),
        outbox_store=OutboxStore(database),
    )
    semaphore = asyncio.Semaphore(concurrency)
    latencies: list[float] = []

    async def execute(index: int) -> None:
        request = TurnRequest.model_validate(
            {
                "session_id": f"load-{index % concurrency}",
                "turn_id": f"load-{index}",
                "npc_id": f"npc-{index}",
                "player_input": "你好",
                "scene": {"location": "load_test"},
                "character_core": "测试角色",
            }
        )
        async with semaphore:
            started = time.perf_counter()
            await service.run_turn(request, adapter=NoopAdapter())
            latencies.append((time.perf_counter() - started) * 1_000)

    started = time.perf_counter()
    await asyncio.gather(*(execute(index) for index in range(turns)))
    elapsed = time.perf_counter() - started
    report = {
        "turns": turns,
        "concurrency": concurrency,
        "elapsed_seconds": round(elapsed, 4),
        "throughput_per_second": round(turns / elapsed, 3),
        "average_ms": round(sum(latencies) / len(latencies), 3),
        "p50_ms": round(percentile(latencies, 0.5), 3),
        "p95_ms": round(percentile(latencies, 0.95), 3),
        "max_ms": round(max(latencies), 3),
    }
    if temporary is not None:
        temporary.cleanup()
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description="Offline NPC Director load profile")
    parser.add_argument("--turns", type=int, default=100)
    parser.add_argument("--concurrency", type=int, default=10)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    payload = json.dumps(
        asyncio.run(run_load_profile(turns=args.turns, concurrency=args.concurrency)),
        indent=2,
    )
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(payload + "\n", encoding="utf-8")
        print(args.output)
    else:
        print(payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
