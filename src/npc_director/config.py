from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


def _optional_float(name: str) -> float | None:
    raw_value = os.getenv(name, "").strip()
    if not raw_value:
        return None
    value = float(raw_value)
    if value < 0:
        raise ValueError(f"{name} must be non-negative")
    return value


@dataclass(frozen=True, slots=True)
class Settings:
    model: str | None = None
    director_model: str | None = None
    narrative_model: str | None = None
    lore_model: str | None = None
    screenwriter_model: str | None = None
    performance_model: str | None = None
    judge_model: str | None = None
    fallback_model: str | None = None
    model_profile: str | None = None
    orchestration_mode: str = "bounded"
    timeout_seconds: float = 30.0
    max_turns: int = 4
    max_specialist_calls: int = 4
    max_handoffs: int = 1
    max_repair_attempts: int = 2
    max_concurrent_model_calls: int = 4
    model_retry_attempts: int = 3
    low_confidence_threshold: float = 0.55
    database_path: Path = Path("data/runtime/npc_director.db")
    lore_path: Path = Path("data/world/lore")
    character_path: Path = Path("data/characters")
    lore_top_k: int = 4
    lore_token_budget: int = 1_200
    context_history_limit: int = 8
    outbox_retry_limit: int = 5
    prompt_version: str = "baseline-v1"
    schema_version: str = "1.0"
    input_cost_per_million: float | None = None
    output_cost_per_million: float | None = None

    @classmethod
    def from_env(cls) -> Settings:
        model = os.getenv("NPC_DIRECTOR_MODEL", "").strip() or None
        timeout_seconds = float(os.getenv("NPC_DIRECTOR_TIMEOUT_SECONDS", "30"))
        max_turns = int(os.getenv("NPC_DIRECTOR_MAX_TURNS", "4"))
        if timeout_seconds <= 0:
            raise ValueError("NPC_DIRECTOR_TIMEOUT_SECONDS must be positive")
        if max_turns < 1:
            raise ValueError("NPC_DIRECTOR_MAX_TURNS must be at least 1")
        settings = cls(
            model=model,
            director_model=_optional_string("NPC_DIRECTOR_DIRECTOR_MODEL"),
            narrative_model=_optional_string("NPC_DIRECTOR_NARRATIVE_MODEL"),
            lore_model=_optional_string("NPC_DIRECTOR_LORE_MODEL"),
            screenwriter_model=_optional_string("NPC_DIRECTOR_SCREENWRITER_MODEL"),
            performance_model=_optional_string("NPC_DIRECTOR_PERFORMANCE_MODEL"),
            judge_model=_optional_string("NPC_DIRECTOR_JUDGE_MODEL"),
            fallback_model=_optional_string("NPC_DIRECTOR_FALLBACK_MODEL"),
            model_profile=_optional_string("NPC_DIRECTOR_MODEL_PROFILE"),
            orchestration_mode=(
                os.getenv("NPC_DIRECTOR_ORCHESTRATION_MODE", "bounded").strip().lower() or "bounded"
            ),
            timeout_seconds=timeout_seconds,
            max_turns=max_turns,
            max_specialist_calls=int(os.getenv("NPC_DIRECTOR_MAX_SPECIALIST_CALLS", "4")),
            max_handoffs=int(os.getenv("NPC_DIRECTOR_MAX_HANDOFFS", "1")),
            max_repair_attempts=int(os.getenv("NPC_DIRECTOR_MAX_REPAIR_ATTEMPTS", "2")),
            max_concurrent_model_calls=int(
                os.getenv("NPC_DIRECTOR_MAX_CONCURRENT_MODEL_CALLS", "4")
            ),
            model_retry_attempts=int(os.getenv("NPC_DIRECTOR_MODEL_RETRY_ATTEMPTS", "3")),
            low_confidence_threshold=float(
                os.getenv("NPC_DIRECTOR_LOW_CONFIDENCE_THRESHOLD", "0.55")
            ),
            database_path=Path(
                os.getenv("NPC_DIRECTOR_DATABASE_PATH", "data/runtime/npc_director.db")
            ),
            lore_path=Path(os.getenv("NPC_DIRECTOR_LORE_PATH", "data/world/lore")),
            character_path=Path(os.getenv("NPC_DIRECTOR_CHARACTER_PATH", "data/characters")),
            lore_top_k=int(os.getenv("NPC_DIRECTOR_LORE_TOP_K", "4")),
            lore_token_budget=int(os.getenv("NPC_DIRECTOR_LORE_TOKEN_BUDGET", "1200")),
            context_history_limit=int(os.getenv("NPC_DIRECTOR_CONTEXT_HISTORY_LIMIT", "8")),
            outbox_retry_limit=int(os.getenv("NPC_DIRECTOR_OUTBOX_RETRY_LIMIT", "5")),
            input_cost_per_million=_optional_float("NPC_DIRECTOR_INPUT_COST_PER_MILLION"),
            output_cost_per_million=_optional_float("NPC_DIRECTOR_OUTPUT_COST_PER_MILLION"),
        )
        settings.validate()
        return settings

    def validate(self) -> None:
        if self.orchestration_mode not in {"bounded", "react"}:
            raise ValueError("NPC_DIRECTOR_ORCHESTRATION_MODE must be 'bounded' or 'react'")
        if self.model_profile is not None:
            from npc_director.model_profile.registry import PROFILE_NAMES

            if self.model_profile not in PROFILE_NAMES:
                raise ValueError(
                    "NPC_DIRECTOR_MODEL_PROFILE must be one of "
                    f"{sorted(PROFILE_NAMES)}, got {self.model_profile!r}"
                )
        if not 1 <= self.max_specialist_calls <= 8:
            raise ValueError("NPC_DIRECTOR_MAX_SPECIALIST_CALLS must be between 1 and 8")
        if not 0 <= self.max_handoffs <= 2:
            raise ValueError("NPC_DIRECTOR_MAX_HANDOFFS must be between 0 and 2")
        if not 0 <= self.max_repair_attempts <= 4:
            raise ValueError("NPC_DIRECTOR_MAX_REPAIR_ATTEMPTS must be between 0 and 4")
        if self.max_concurrent_model_calls < 1:
            raise ValueError("NPC_DIRECTOR_MAX_CONCURRENT_MODEL_CALLS must be positive")
        if not 1 <= self.model_retry_attempts <= 5:
            raise ValueError("NPC_DIRECTOR_MODEL_RETRY_ATTEMPTS must be between 1 and 5")
        if not 0 <= self.low_confidence_threshold <= 1:
            raise ValueError("NPC_DIRECTOR_LOW_CONFIDENCE_THRESHOLD must be between 0 and 1")
        if self.lore_top_k < 1 or self.lore_token_budget < 100:
            raise ValueError("Lore retrieval limits are invalid")
        if self.context_history_limit < 1 or self.outbox_retry_limit < 1:
            raise ValueError("History and outbox limits must be positive")

    def model_for(self, role: str) -> str | None:
        role_models = {
            "director": self.director_model,
            "narrative": self.narrative_model,
            "lore": self.lore_model,
            "screenwriter": self.screenwriter_model,
            "performance": self.performance_model,
            "judge": self.judge_model,
        }
        if role not in role_models:
            raise ValueError(f"unknown model role: {role}")
        return role_models[role] or self.model

    def estimate_cost(self, input_tokens: int, output_tokens: int) -> float | None:
        if self.input_cost_per_million is None or self.output_cost_per_million is None:
            return None
        return (
            input_tokens * self.input_cost_per_million
            + output_tokens * self.output_cost_per_million
        ) / 1_000_000


def _optional_string(name: str) -> str | None:
    return os.getenv(name, "").strip() or None
