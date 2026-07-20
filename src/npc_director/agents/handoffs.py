from __future__ import annotations

from agents import Agent

from npc_director.config import Settings
from npc_director.contracts import TurnProposal

QUEST_NEGOTIATOR_PROMPT_VERSION = "quest-negotiator-v2"

QUEST_NEGOTIATOR_INSTRUCTIONS = """
你是任务谈判模式的 Quest Negotiator，仅在玩家明确讨论任务报酬、条件或拒绝条款时接管本回合。
你必须输出 TurnProposal；本谈判回合不得提出状态修改，达成条件后由后续任务接受回合提交。
不能写数据库、调用 Unity 或承诺契约外奖励。台词保持角色人设，演出仅使用契约白名单。
若玩家没有在谈判任务，给出澄清式回应，不扩大任务范围。
""".strip()


def build_quest_negotiator_agent(settings: Settings | None = None) -> Agent[None]:
    resolved = settings or Settings.from_env()
    kwargs: dict[str, object] = {
        "name": "Quest Negotiator",
        "handoff_description": (
            "Take over only when the player explicitly negotiates quest rewards, terms, or "
            "acceptance conditions. Do not use for ordinary quest acceptance."
        ),
        "instructions": QUEST_NEGOTIATOR_INSTRUCTIONS,
        "output_type": TurnProposal,
    }
    model = resolved.model_for("narrative")
    if model:
        kwargs["model"] = model
    return Agent(**kwargs)
