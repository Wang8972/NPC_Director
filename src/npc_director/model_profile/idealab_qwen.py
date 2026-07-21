from __future__ import annotations

from npc_director.model_profile.base import ModelProfile
from npc_director.model_profile.default import PassthroughPromptAdapter
from npc_director.model_profile.idealab_deepseek import (
    IdealabGatewayAdapter,
    IdealabRetryPolicy,
    LightTouchNormalizer,
)

IDEALAB_QWEN_PROFILE_NAME = "idealab_qwen"


class IdealabQwenPromptAdapter(PassthroughPromptAdapter):
    """No prompt patches yet (live-probed 2025-07: qwen3.7-max shows the same
    tools + structured output gateway defect as deepseek, so it relies on the
    executor's two-phase generation instead of prompt-level enforcement)."""

    @property
    def version_tag(self) -> str | None:
        return "idealab-qwen-v1"


def build_idealab_qwen_profile() -> ModelProfile:
    return ModelProfile(
        name=IDEALAB_QWEN_PROFILE_NAME,
        gateway=IdealabGatewayAdapter(),
        retry=IdealabRetryPolicy(),
        prompts=IdealabQwenPromptAdapter(),
        normalizer=LightTouchNormalizer(),
    )
