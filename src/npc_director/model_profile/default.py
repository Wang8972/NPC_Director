from __future__ import annotations

from functools import lru_cache

from agents import RunConfig
from agents.models.multi_provider import MultiProvider
from openai import APIConnectionError, APITimeoutError, InternalServerError, RateLimitError

from npc_director.contracts import TurnProposal
from npc_director.model_profile.base import ModelProfile

DEFAULT_PROFILE_NAME = "default"

RETRYABLE_MODEL_ERRORS = (
    RateLimitError,
    InternalServerError,
    APITimeoutError,
    APIConnectionError,
    TimeoutError,
)


@lru_cache(maxsize=1)
def shared_multi_provider() -> MultiProvider:
    # Pass namespaced model IDs (e.g. "bailian/deepseek-v4-pro") through to
    # OpenAI-compatible gateways instead of failing on unknown prefixes.
    return MultiProvider(unknown_prefix_mode="model_id")


class DefaultGatewayAdapter:
    """Standard OpenAI endpoint; env hooks in npc_director.__init__ stay in charge."""

    def configure(self) -> None:
        return None

    def build_run_config(self) -> RunConfig:
        return RunConfig(model_provider=shared_multi_provider())


class TypedRetryPolicy:
    """Retries only well-known transient exception types (previous executor behavior)."""

    def __init__(self, *, max_attempts: int = 3) -> None:
        self._max_attempts = max_attempts

    @property
    def max_attempts(self) -> int:
        return self._max_attempts

    def is_retryable(self, exc: Exception) -> bool:
        return isinstance(exc, RETRYABLE_MODEL_ERRORS)

    def backoff_seconds(self, attempt: int) -> float:
        return min(0.5 * (2**attempt), 8.0)


class PassthroughPromptAdapter:
    """Keeps every base prompt untouched."""

    @property
    def version_tag(self) -> str | None:
        return None

    def director_instructions(self, base: str) -> str:
        return base

    def baseline_instructions(self, base: str) -> str:
        return base

    def specialist_instructions(self, role: str, base: str) -> str:
        return base


class IdentityNormalizer:
    def normalize(self, proposal: TurnProposal) -> TurnProposal:
        return proposal


def build_default_profile() -> ModelProfile:
    return ModelProfile(
        name=DEFAULT_PROFILE_NAME,
        gateway=DefaultGatewayAdapter(),
        retry=TypedRetryPolicy(),
        prompts=PassthroughPromptAdapter(),
        normalizer=IdentityNormalizer(),
    )
