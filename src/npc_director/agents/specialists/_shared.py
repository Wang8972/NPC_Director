from __future__ import annotations

from agents import Agent
from agents.tool import Tool
from pydantic import BaseModel

from npc_director.config import Settings
from npc_director.model_profile import get_active_profile


def build_specialist_agent(
    *,
    name: str,
    role: str,
    instructions: str,
    output_type: type[BaseModel],
    settings: Settings | None,
    tools: list[Tool] | None = None,
) -> Agent[None]:
    resolved = settings or Settings.from_env()
    profile = get_active_profile(resolved)
    kwargs: dict[str, object] = {
        "name": name,
        "instructions": profile.prompts.specialist_instructions(role, instructions),
        "output_type": output_type,
        "tools": list(tools or []),
    }
    model = resolved.model_for(role)
    if model:
        kwargs["model"] = model
    return Agent(**kwargs)
