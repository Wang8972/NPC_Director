from __future__ import annotations

from agents import Agent
from agents.tool import Tool
from pydantic import BaseModel

from npc_director.config import Settings


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
    kwargs: dict[str, object] = {
        "name": name,
        "instructions": instructions,
        "output_type": output_type,
        "tools": list(tools or []),
    }
    model = resolved.model_for(role)
    if model:
        kwargs["model"] = model
    return Agent(**kwargs)
