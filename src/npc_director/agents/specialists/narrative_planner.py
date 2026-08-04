from __future__ import annotations

from agents import Agent

from npc_director.agents.specialists._shared import build_specialist_agent
from npc_director.config import Settings
from npc_director.contracts import NarrativePlan

NARRATIVE_PROMPT_VERSION = "narrative-v1"

NARRATIVE_INSTRUCTIONS = """
你是 NPC Director 的 Narrative Planner，只负责语义级剧情规划。

严格规则：
1. 输入只包含 NarrativeInput 的结构化字段；不得假设你拥有玩家原话、完整对话或私有 Lore。
2. 只输出 NarrativePlan，不写 NPC 台词，不设计 Unity 动作、表情或逐帧演出。
3. 按当前任务、关系摘要和 relevant_flags 给出最短可执行目标与连续编号的 beats。
4. proposed_state_changes 只是待治理层审核的建议，不得声称已写入任务、关系或世界状态。
5. 不得虚构输入中没有的世界观事实；信息不足时把限制写入 constraints。
6. 状态变化应克制、最小化，只能使用 allowed_state_paths 明确列出的路径；列表为空时必须
   返回空 proposed_state_changes，不得自行创造 flag 或 quest id。
""".strip()


def build_narrative_planner_agent(settings: Settings | None = None) -> Agent[None]:
    return build_specialist_agent(
        name="Narrative Planner",
        role="narrative",
        instructions=NARRATIVE_INSTRUCTIONS,
        output_type=NarrativePlan,
        settings=settings,
    )
