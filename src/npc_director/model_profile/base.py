from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from agents import RunConfig

from npc_director.contracts import TurnProposal


class GatewayAdapter(Protocol):
    """Adapts the Agents SDK to a specific OpenAI-compatible gateway."""

    def configure(self) -> None:
        """Apply process-wide SDK settings (API flavor, tracing). Must be idempotent."""
        ...

    def build_run_config(self) -> RunConfig: ...


class RetryPolicy(Protocol):
    """Classifies model-call failures and paces retries for one model/gateway."""

    @property
    def max_attempts(self) -> int: ...

    def is_retryable(self, exc: Exception) -> bool: ...

    def backoff_seconds(self, attempt: int) -> float: ...


class PromptAdapter(Protocol):
    """Customizes agent instructions for one model without touching the base prompts."""

    @property
    def version_tag(self) -> str | None:
        """Suffix appended to prompt_versions when instructions are customized."""
        ...

    def director_instructions(self, base: str) -> str: ...

    def baseline_instructions(self, base: str) -> str: ...

    def specialist_instructions(self, role: str, base: str) -> str: ...


class ProposalNormalizer(Protocol):
    """Model-output touch-up applied before governance checks; must not bypass them."""

    def normalize(self, proposal: TurnProposal) -> TurnProposal: ...


@dataclass(frozen=True, slots=True)
class ModelProfile:
    """Aggregates every model-specific customization point behind one object."""

    name: str
    gateway: GatewayAdapter
    retry: RetryPolicy
    prompts: PromptAdapter
    normalizer: ProposalNormalizer

    def build_run_config(self) -> RunConfig:
        return self.gateway.build_run_config()
