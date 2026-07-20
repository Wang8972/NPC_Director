from __future__ import annotations

import argparse
import json
from pathlib import Path

from npc_director.config import Settings
from npc_director.contracts import extract_state_change_paths
from npc_director.state import TurnStore


def build_regression_case(database: Path, turn_id: str) -> dict:
    turn = TurnStore(database).require(turn_id)
    if turn.proposal is None:
        raise ValueError("turn has no proposal to convert")
    proposal = turn.proposal
    return {
        "id": turn.request.turn_id,
        "input": turn.request.model_dump(mode="json"),
        "expect": {
            "intent": proposal.plan.intent.value,
            "emotion": {
                "coarse": [proposal.performance.emotion.coarse.value],
                "primary": [proposal.performance.emotion.primary.value],
                "secondary": (
                    [proposal.performance.emotion.secondary.value]
                    if proposal.performance.emotion.secondary
                    else []
                ),
            },
            "allowed_actions": sorted({cue.action.value for cue in proposal.performance.body_cues}),
            "state_patch_allowlist": sorted(
                extract_state_change_paths(proposal.plan.proposed_state_changes)
            ),
            "required_text": [],
            "forbidden_text": [],
            "required_specialists": [item.value for item in turn.specialists_called],
            "optional_specialists": [],
            "forbidden_specialists": [],
            "required_handoff": turn.handoffs[0] if turn.handoffs else None,
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Convert a bad trace into a draft eval case")
    parser.add_argument("turn_id")
    parser.add_argument("--database", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    settings = Settings.from_env()
    database = args.database or settings.database_path
    case = build_regression_case(database, args.turn_id)
    existing_ids = set()
    if args.output.exists():
        existing_ids = {
            json.loads(line)["id"]
            for line in args.output.read_text(encoding="utf-8").splitlines()
            if line.strip()
        }
    if case["id"] in existing_ids:
        raise ValueError(f"case {case['id']!r} already exists")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(case, ensure_ascii=False) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
