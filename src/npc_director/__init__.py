"""NPC Director package."""

import os

__version__ = "0.3.0"


def _configure_agents_sdk_from_env() -> None:
    """Apply optional Agents SDK overrides for OpenAI-compatible gateways.

    Explicit env override; the preferred path is a model profile
    (npc_director.model_profile), whose gateway adapter honors these variables.
    """
    api = os.getenv("NPC_DIRECTOR_OPENAI_API", "").strip()
    disable_tracing = os.getenv("NPC_DIRECTOR_DISABLE_TRACING", "").strip().lower()
    if not api and disable_tracing not in {"1", "true", "yes"}:
        return
    from agents import set_default_openai_api, set_tracing_disabled

    if api in {"chat_completions", "responses"}:
        set_default_openai_api(api)  # type: ignore[arg-type]
    if disable_tracing in {"1", "true", "yes"}:
        set_tracing_disabled(True)


_configure_agents_sdk_from_env()
