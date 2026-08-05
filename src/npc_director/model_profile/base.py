from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from agents import RunConfig

from npc_director.contracts import TurnProposal

_ALLOCATION_QUOTA_MARKER = "throttling.allocationquota"


def is_allocation_quota_error(exc: BaseException) -> bool:
    """Return whether a failure says the gateway's allocation is exhausted.

    The idealab gateway may wrap this signal in a generic 400 exception, so
    classification must inspect the exception chain instead of relying on the
    HTTP status or concrete exception type.
    """

    current: BaseException | None = exc
    seen: set[int] = set()
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        if _ALLOCATION_QUOTA_MARKER in str(current).casefold():
            return True
        current = current.__cause__ or current.__context__
    return False


class GatewayAdapter(Protocol):
    """Adapts the Agents SDK to a specific OpenAI-compatible gateway."""

    def configure(self) -> None:
        """Apply process-wide SDK settings (API flavor, tracing). Must be idempotent."""
        ...

    def build_run_config(self) -> RunConfig: ...

    @property
    def supports_tools_with_structured_output(self) -> bool:
        """Whether legacy ReAct can combine tools with structured output.

        The bounded executor uses independent typed nodes and does not depend on
        this capability. The legacy executor uses it to select one- or two-phase
        generation for ablation compatibility.
        """
        ...


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
