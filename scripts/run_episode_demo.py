"""Headless collaboration, reviewed side-quest offer, and follow-up demonstration.

Recorded mode is a fixture demonstration, not model quality evidence.
"""

from __future__ import annotations

import asyncio
import json

from eval.episode_runner import EpisodeEvalCase, EpisodeEvalTurn, run_episode_suite
from scripts.run_episode_eval import eval_settings, parser, report_path


def demo_case() -> EpisodeEvalCase:
    return EpisodeEvalCase(
        id="cooperation_review_demo",
        title="核实护送条件并提出可拒绝的旧信支线",
        tags=["demo", "multi_npc", "content_review", "continuity"],
        goal="各人独立核实护送条件；介绍旧信支线，等待玩家自己决定；后续记住尚未接受。",
        setup=(
            "玛伦协调护送，守卫负责核实路况，伊欧娜决定自己的同行条件。"
            "玛伦另有一封故人的旧信，希望玩家询问家属是否愿意接过。"
            "此事与护送独立，可拒绝，且仅需现有对话和任务状态能力。"
        ),
        initial_quests={"herbalist_escort": "offered"},
        collaborate_with=["village_guard", "herbalist_iona"],
        content_mode="short_quest",
        turns=[
            EpisodeEvalTurn(
                input="请大家分别说说护送条件。玛伦，你那封旧信的事也先说说，我还没决定。",
                fixture_reply=(
                    "守卫先核实路况，伊欧娜说说自己的准备。"
                    "另有一封旧信，想托你问家属是否愿接；这事你可以不接。"
                ),
                fixture_followup="路况仍待守卫核实；伊奥娜的同行条件也保留着。旧信委托等你决定。",
                intent="negotiation",
                negotiate=True,
                needs_lore=True,
                acts=["consult", "conditional_request"],
            ),
            EpisodeEvalTurn(
                input="旧信先让我想想。现在护送条件里，哪些还没确认？",
                fixture_reply="旧信的事等你决定。护送路况还需核实，不能先当作安全。",
            ),
            EpisodeEvalTurn(
                input="对，记住我只是听了旧信委托，还没接受。",
                fixture_reply="记着，你还没有接受那件委托。",
            ),
        ],
        expected={
            "min_new_quests": 1,
            "max_new_quests": 1,
            "author_calls": "some",
            "published_scope": "side_quest",
            "minimum_speakers": 3,
        },
    )


async def main() -> int:
    arguments = parser()
    arguments.description = __doc__
    arguments.set_defaults(repeats=1)
    args = arguments.parse_args()
    path = args.output or report_path(args.mode, prefix="demo")
    report = await run_episode_suite(
        [demo_case()],
        repeats=args.repeats,
        mode=args.mode,
        settings=eval_settings(args),
        transport=args.transport,
        judge_model=args.judge_model,
        output_path=path,
    )
    for item in report["results"][0]["transcript"]:
        print(f"{item['role']} [{item['npc_id']}]: {item['text']}")
    print(
        json.dumps(
            {"report": str(path), "summary": report["summary"]}, ensure_ascii=False, indent=2
        )
    )
    passed = (
        report["summary"]["meets_live_acceptance"]
        if args.mode == "live"
        else report["summary"]["structural_passes"] == report["summary"]["runs"]
    )
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
