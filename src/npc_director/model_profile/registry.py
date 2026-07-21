from __future__ import annotations

from collections.abc import Callable

from npc_director.config import Settings
from npc_director.model_profile.base import ModelProfile
from npc_director.model_profile.default import DEFAULT_PROFILE_NAME, build_default_profile
from npc_director.model_profile.idealab_deepseek import (
    IDEALAB_DEEPSEEK_PROFILE_NAME,
    build_idealab_deepseek_profile,
)
from npc_director.model_profile.idealab_qwen import (
    IDEALAB_QWEN_PROFILE_NAME,
    build_idealab_qwen_profile,
)

_PROFILE_BUILDERS: dict[str, Callable[[], ModelProfile]] = {
    DEFAULT_PROFILE_NAME: build_default_profile,
    IDEALAB_DEEPSEEK_PROFILE_NAME: build_idealab_deepseek_profile,
    IDEALAB_QWEN_PROFILE_NAME: build_idealab_qwen_profile,
}

PROFILE_NAMES = frozenset(_PROFILE_BUILDERS)

_INSTANCES: dict[str, ModelProfile] = {}
_CONFIGURED: set[str] = set()


def resolve_profile_name(settings: Settings) -> str:
    if settings.model_profile:
        return settings.model_profile
    for candidate in (settings.director_model, settings.model):
        if not candidate:
            continue
        if candidate.startswith("bailian/deepseek"):
            return IDEALAB_DEEPSEEK_PROFILE_NAME
        if candidate.startswith("qwen"):
            return IDEALAB_QWEN_PROFILE_NAME
    return DEFAULT_PROFILE_NAME


def get_active_profile(settings: Settings | None = None) -> ModelProfile:
    resolved = settings or Settings.from_env()
    name = resolve_profile_name(resolved)
    builder = _PROFILE_BUILDERS.get(name)
    if builder is None:
        raise ValueError(f"unknown model profile: {name}; expected one of {sorted(PROFILE_NAMES)}")
    profile = _INSTANCES.get(name)
    if profile is None:
        profile = builder()
        _INSTANCES[name] = profile
    if name not in _CONFIGURED:
        profile.gateway.configure()
        _CONFIGURED.add(name)
    return profile


def reset_profile_cache() -> None:
    """Testing hook: drop cached instances so gateway configure() runs again."""
    _INSTANCES.clear()
    _CONFIGURED.clear()
