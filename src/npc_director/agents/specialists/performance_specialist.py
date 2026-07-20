from __future__ import annotations

from agents import Agent

from npc_director.agents.specialists._shared import build_specialist_agent
from npc_director.config import Settings
from npc_director.contracts import PerformanceOutput

PERFORMANCE_PROMPT_VERSION = "performance-v1"

PERFORMANCE_INSTRUCTIONS = """
你是 NPC Director 的 Performance Specialist，只负责把既定台词和情绪转成语义级演出。

严格规则：
1. 只输出 PerformanceOutput；不得改写台词含义、剧情目标或建议世界状态变化。
2. 你不会收到玩家原始输入、秘密 Lore、完整历史或数据库状态，不得猜测这些信息。
3. body_cues 只能使用 allowed_actions，face_cues 只能使用 allowed_faces。
4. 不得输出任意 Unity Clip、Animator State、BlendShape 名称或其他契约外参数。
5. cue 按 start_ms 升序排列，并让台词、情绪、表情、动作和凝视一致。
6. 输出只是 PerformanceDraft 包装，不得包含 session、turn、trace、response 等运行时字段。
""".strip()


def build_performance_specialist_agent(settings: Settings | None = None) -> Agent[None]:
    return build_specialist_agent(
        name="Performance Specialist",
        role="performance",
        instructions=PERFORMANCE_INSTRUCTIONS,
        output_type=PerformanceOutput,
        settings=settings,
    )
