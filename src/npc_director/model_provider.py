from __future__ import annotations

from agents import RunConfig

from npc_director.config import Settings
from npc_director.model_profile import get_active_profile


def build_run_config(settings: Settings | None = None) -> RunConfig:
    """Thin facade kept for existing call sites; delegates to the active model profile."""
    return get_active_profile(settings).build_run_config()
