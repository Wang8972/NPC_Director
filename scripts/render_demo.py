from __future__ import annotations

import asyncio
from pathlib import Path

from npc_director.contracts import PerformanceDirective
from npc_director.unity_adapter import ConsoleEngineAdapter, HtmlEngineAdapter


def demo_directive() -> PerformanceDirective:
    return PerformanceDirective.model_validate(
        {
            "schema_version": "1.0",
            "session_id": "demo-session",
            "turn_id": "demo-session:1",
            "npc_id": "elder_maren",
            "dialogue": {
                "text": "你终于回来了……我还以为再也见不到你。",
                "voice_style": "soft_restrained",
            },
            "emotion": {
                "coarse": "joy",
                "primary": "relieved",
                "secondary": "melancholic",
                "intensity": 0.7,
                "valence": 0.2,
                "arousal": 0.5,
            },
            "face_cues": [
                {
                    "preset": "relieved_smile",
                    "intensity": 0.65,
                    "start_ms": 0,
                    "duration_ms": 2200,
                }
            ],
            "body_cues": [
                {
                    "action": "step_forward",
                    "layer": "full_body",
                    "priority": 60,
                    "start_ms": 200,
                },
                {
                    "action": "small_nod",
                    "layer": "upper_body",
                    "priority": 40,
                    "start_ms": 900,
                },
            ],
            "gaze": {"target": "player_head", "mode": "soft_focus"},
            "interrupt_policy": "allow_higher_priority",
            "confidence": 0.84,
            "evidence": {"lore_refs": ["event:war_of_ash"]},
            "runtime_meta": {
                "specialists_called": ["baseline"],
                "prompt_versions": ["manual-demo-v1"],
                "model": None,
                "trace_id": "manual-demo",
                "response_id": None,
            },
        }
    )


async def main() -> None:
    directive = demo_directive()
    await ConsoleEngineAdapter().emit(directive)
    ack = await HtmlEngineAdapter(Path("artifacts")).emit(directive)
    print(f"\nHTML timeline: {ack.detail}")


if __name__ == "__main__":
    asyncio.run(main())
