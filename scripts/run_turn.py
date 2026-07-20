from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path

from npc_director.contracts import TurnRequest
from npc_director.orchestration import run_turn
from npc_director.unity_adapter import ConsoleEngineAdapter, HtmlEngineAdapter


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run one live NPC Director baseline turn")
    parser.add_argument("request", type=Path, help="Path to a TurnRequest JSON file")
    parser.add_argument("--html", action="store_true", help="Write an HTML timeline")
    return parser.parse_args()


async def main() -> None:
    args = parse_args()
    request = TurnRequest.model_validate_json(args.request.read_text(encoding="utf-8"))
    adapter = HtmlEngineAdapter(Path("artifacts")) if args.html else ConsoleEngineAdapter()
    result = await run_turn(request, adapter=adapter)
    print(json.dumps(result.model_dump(mode="json"), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
