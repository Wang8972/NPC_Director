from __future__ import annotations

import os

from agents import RunConfig

from npc_director.contracts import TurnProposal
from npc_director.model_profile.base import ModelProfile, is_allocation_quota_error
from npc_director.model_profile.default import (
    PassthroughPromptAdapter,
    TypedRetryPolicy,
    shared_multi_provider,
)

IDEALAB_DEEPSEEK_PROFILE_NAME = "idealab_deepseek"

# idealab gateway throttling surfaces as BadRequestError(400) with these markers,
# so type-based classification alone would never retry it.
_THROTTLING_MARKERS = ("MPE-429", "Throttling", "限流")

# Known limitation (live-probed 2025-07): with tools + structured output (output_type)
# combined, deepseek-v4-pro via idealab skips tool calls and emits the final JSON
# directly; with plain-text output the same model calls tools normally. The gateway
# adapter therefore reports supports_tools_with_structured_output=False. The legacy
# ReAct executor then uses two-phase generation (plain-text orchestration + structured
# summarization); production bounded orchestration avoids this tool/output combination.
_DIRECTOR_ADDENDUM = """
针对当前模型的强制路由纪律（在上述规则基础上必须执行）：
A. 每个回合都必须真实调用工具，至少依次调用 screenwriter 和 performance_specialist；
   禁止不调用任何工具就直接给出最终答复。
B. 玩家询问世界观事实（历史、事件、人物、地点、传闻）时，必须先调用 lore_specialist
   获取证据，再调用 screenwriter。
C. 任务接受、关键选择等需要状态变化的回合，必须先调用 narrative_planner。
""".strip()

_EMOTION_CONVENTIONS = """
情绪根据当前角色、关系、记忆和本句具体语气决定；intent只是功能摘要，不决定情绪。
允许隐忍、混合情绪以及同一意图在不同人物上的不同表达，仅使用契约已有枚举。
""".strip()

_DIALOGUE_GROUNDING = """
台词必须直接回应玩家话语中的关键名词（地名、事件、人物、任务对象），并在不违背证据的
前提下复述关键事实词（如时间、地点、任务目的地），不要空泛应答。
""".strip()


class IdealabGatewayAdapter:
    """idealab gateway only speaks chat/completions and cannot receive traces."""

    def configure(self) -> None:
        from agents import set_default_openai_api, set_tracing_disabled

        # Explicit env hooks (npc_director.__init__) stay authoritative when set.
        if not os.getenv("NPC_DIRECTOR_OPENAI_API", "").strip():
            set_default_openai_api("chat_completions")
        if not os.getenv("NPC_DIRECTOR_DISABLE_TRACING", "").strip():
            set_tracing_disabled(True)

    def build_run_config(self) -> RunConfig:
        return RunConfig(model_provider=shared_multi_provider())

    @property
    def supports_tools_with_structured_output(self) -> bool:
        # Live-probed gateway defect: structured output suppresses tool calls.
        return False


class IdealabRetryPolicy(TypedRetryPolicy):
    """Adds text-marker detection for throttling returned as non-429 status codes."""

    def __init__(self, *, max_attempts: int = 6) -> None:
        super().__init__(max_attempts=max_attempts)

    def is_retryable(self, exc: Exception) -> bool:
        if is_allocation_quota_error(exc):
            return False
        if super().is_retryable(exc):
            return True
        text = str(exc)
        return any(marker in text for marker in _THROTTLING_MARKERS)

    def backoff_seconds(self, attempt: int) -> float:
        # Quota windows on the gateway recover slowly; back off in long steps.
        return 20.0 * (attempt + 1)


class IdealabDeepseekPromptAdapter(PassthroughPromptAdapter):
    @property
    def version_tag(self) -> str | None:
        return "idealab-deepseek-v1"

    def director_instructions(self, base: str) -> str:
        return f"{base}\n\n{_DIRECTOR_ADDENDUM}\n\n{_DIALOGUE_GROUNDING}"

    def baseline_instructions(self, base: str) -> str:
        return f"{base}\n\n补充纪律：\n{_DIALOGUE_GROUNDING}\n{_EMOTION_CONVENTIONS}"

    def specialist_instructions(self, role: str, base: str) -> str:
        if role != "screenwriter":
            return base
        return f"{base}\n\n补充纪律：\n{_DIALOGUE_GROUNDING}\n{_EMOTION_CONVENTIONS}"


class LightTouchNormalizer:
    """Deterministic touch-up only; never rewrites meaning or bypasses governance."""

    _QUOTE_PAIRS = (("「", "」"), ("『", "』"), ("“", "”"), ('"', '"'))

    def normalize(self, proposal: TurnProposal) -> TurnProposal:
        performance = proposal.performance
        text = self._clean_dialogue(performance.dialogue.text)
        face_cues = sorted(performance.face_cues, key=lambda cue: cue.start_ms)
        body_cues = sorted(performance.body_cues, key=lambda cue: cue.start_ms)
        if (
            text == performance.dialogue.text
            and face_cues == performance.face_cues
            and body_cues == performance.body_cues
        ):
            return proposal
        return proposal.model_copy(
            update={
                "performance": performance.model_copy(
                    update={
                        "dialogue": performance.dialogue.model_copy(update={"text": text}),
                        "face_cues": face_cues,
                        "body_cues": body_cues,
                    }
                )
            }
        )

    def _clean_dialogue(self, text: str) -> str:
        cleaned = text.strip()
        for left, right in self._QUOTE_PAIRS:
            if len(cleaned) > 2 and cleaned.startswith(left) and cleaned.endswith(right):
                cleaned = cleaned[len(left) : -len(right)].strip()
        return cleaned or text


def build_idealab_deepseek_profile() -> ModelProfile:
    return ModelProfile(
        name=IDEALAB_DEEPSEEK_PROFILE_NAME,
        gateway=IdealabGatewayAdapter(),
        retry=IdealabRetryPolicy(),
        prompts=IdealabDeepseekPromptAdapter(),
        normalizer=LightTouchNormalizer(),
    )
