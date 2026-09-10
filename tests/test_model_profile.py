from __future__ import annotations

import pytest

from npc_director.agents.baseline import BASELINE_INSTRUCTIONS
from npc_director.agents.director import DIRECTOR_INSTRUCTIONS
from npc_director.config import Settings
from npc_director.contracts import TurnProposal
from npc_director.model_profile import (
    DEFAULT_PROFILE_NAME,
    IDEALAB_DEEPSEEK_PROFILE_NAME,
    IDEALAB_QWEN_PROFILE_NAME,
    build_default_profile,
    build_idealab_deepseek_profile,
    build_idealab_qwen_profile,
    is_allocation_quota_error,
    resolve_profile_name,
)


def make_proposal(text: str = "谢谢你还记得。") -> TurnProposal:
    return TurnProposal.model_validate(
        {
            "plan": {
                "goal": "回应玩家",
                "intent": "gratitude",
                "required_specialists": ["baseline"],
            },
            "performance": {
                "dialogue": {"text": text, "voice_style": "warm"},
                "emotion": {"coarse": "joy", "primary": "grateful"},
                "face_cues": [{"preset": "relieved_smile", "start_ms": 0}],
                "body_cues": [{"action": "small_nod", "start_ms": 200}],
                "confidence": 0.8,
            },
        }
    )


def test_explicit_profile_name_wins_over_model_inference() -> None:
    settings = Settings(model="bailian/deepseek-v4-pro", model_profile="default")
    assert resolve_profile_name(settings) == DEFAULT_PROFILE_NAME


def test_bailian_deepseek_model_infers_idealab_profile() -> None:
    assert (
        resolve_profile_name(Settings(model="bailian/deepseek-v4-pro"))
        == IDEALAB_DEEPSEEK_PROFILE_NAME
    )
    assert (
        resolve_profile_name(Settings(director_model="bailian/deepseek-v4-pro"))
        == IDEALAB_DEEPSEEK_PROFILE_NAME
    )


def test_unrelated_model_resolves_default_profile() -> None:
    assert resolve_profile_name(Settings()) == DEFAULT_PROFILE_NAME
    assert resolve_profile_name(Settings(model="gpt-4.1-mini")) == DEFAULT_PROFILE_NAME


def test_qwen_model_infers_idealab_qwen_profile() -> None:
    assert resolve_profile_name(Settings(model="qwen3.7-max")) == IDEALAB_QWEN_PROFILE_NAME
    assert resolve_profile_name(Settings(director_model="qwen3.7-max")) == IDEALAB_QWEN_PROFILE_NAME


def test_idealab_qwen_profile_reuses_gateway_without_prompt_patches() -> None:
    profile = build_idealab_qwen_profile()
    assert profile.name == IDEALAB_QWEN_PROFILE_NAME
    assert profile.prompts.version_tag == "idealab-qwen-v1"
    # No prompt patches: instructions pass through untouched.
    assert profile.prompts.director_instructions(DIRECTOR_INSTRUCTIONS) == DIRECTOR_INSTRUCTIONS
    assert profile.prompts.baseline_instructions(BASELINE_INSTRUCTIONS) == BASELINE_INSTRUCTIONS
    # Idealab throttling retry semantics are shared with the deepseek profile.
    assert profile.retry.is_retryable(ValueError("Error code: 400 - MPE-429"))


def test_gateway_two_phase_flag_per_profile() -> None:
    assert build_default_profile().gateway.supports_tools_with_structured_output
    assert not build_idealab_deepseek_profile().gateway.supports_tools_with_structured_output
    assert not build_idealab_qwen_profile().gateway.supports_tools_with_structured_output


def test_settings_rejects_unknown_profile_name() -> None:
    with pytest.raises(ValueError, match="NPC_DIRECTOR_MODEL_PROFILE"):
        Settings(model_profile="no_such_profile").validate()


def test_default_prompts_are_passthrough() -> None:
    prompts = build_default_profile().prompts
    assert prompts.version_tag is None
    assert prompts.director_instructions(DIRECTOR_INSTRUCTIONS) == DIRECTOR_INSTRUCTIONS
    assert prompts.baseline_instructions(BASELINE_INSTRUCTIONS) == BASELINE_INSTRUCTIONS
    assert prompts.specialist_instructions("screenwriter", "base") == "base"


def test_idealab_prompts_extend_base_and_tag_versions() -> None:
    prompts = build_idealab_deepseek_profile().prompts
    assert prompts.version_tag == "idealab-deepseek-v1"
    director = prompts.director_instructions(DIRECTOR_INSTRUCTIONS)
    assert director.startswith(DIRECTOR_INSTRUCTIONS)
    assert "强制路由纪律" in director
    baseline = prompts.baseline_instructions(BASELINE_INSTRUCTIONS)
    assert baseline.startswith(BASELINE_INSTRUCTIONS)
    assert "intent只是功能摘要，不决定情绪" in baseline
    assert "intent只是功能摘要，不决定情绪" in prompts.specialist_instructions(
        "screenwriter", "base"
    )
    # Only the screenwriter prompt is customized; other specialists stay untouched.
    assert prompts.specialist_instructions("lore", "base") == "base"


def test_default_retry_only_matches_transient_exception_types() -> None:
    retry = build_default_profile().retry
    assert retry.is_retryable(TimeoutError())
    assert not retry.is_retryable(ValueError("MPE-429 Throttling.AllocationQuota"))


def test_idealab_retry_detects_throttling_text_markers() -> None:
    retry = build_idealab_deepseek_profile().retry
    assert retry.is_retryable(TimeoutError())
    assert retry.is_retryable(ValueError("Error code: 400 - MPE-429"))
    assert not retry.is_retryable(RuntimeError("Throttling.AllocationQuota"))
    assert not retry.is_retryable(ValueError("模型不存在"))
    assert retry.backoff_seconds(1) > retry.backoff_seconds(0)


def test_allocation_quota_detection_follows_exception_chain() -> None:
    cause = RuntimeError("Throttling.AllocationQuota: capacity exhausted")
    wrapped = ValueError("gateway request failed")
    wrapped.__cause__ = cause

    assert is_allocation_quota_error(wrapped)


def test_default_normalizer_is_identity() -> None:
    proposal = make_proposal()
    assert build_default_profile().normalizer.normalize(proposal) is proposal


def test_idealab_normalizer_strips_wrapping_quotes_and_whitespace() -> None:
    normalizer = build_idealab_deepseek_profile().normalizer
    normalized = normalizer.normalize(make_proposal(text="「谢谢你还记得。」 "))
    assert normalized.performance.dialogue.text == "谢谢你还记得。"
    # Untouched proposals pass through unchanged.
    clean = make_proposal()
    assert normalizer.normalize(clean) is clean
