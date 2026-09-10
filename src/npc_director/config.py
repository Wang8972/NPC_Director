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
    max_model_calls: int = 32
    max_execution_nodes: int = 32
    max_plan_revisions: int = 2
    max_output_tokens: int = 4096
    max_episode_participants: int = 4
    max_autonomous_turns: int = 6
    max_new_quests: int = 1
    max_total_tokens: int = 96_000
    max_node_repairs: int = 1
    planning_timeout_seconds: float = 180.0
    quality_review_enabled: bool = True
    inline_output_schema: bool | None = None
    prompt_json_schemas: tuple[str, ...] = ("NarrativePlan",)
    node_reasoning_effort: str = "low"
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
            max_model_calls=int(os.getenv("NPC_DIRECTOR_MAX_MODEL_CALLS", "32")),
            max_execution_nodes=int(os.getenv("NPC_DIRECTOR_MAX_EXECUTION_NODES", "32")),
            max_plan_revisions=int(os.getenv("NPC_DIRECTOR_MAX_PLAN_REVISIONS", "2")),
            max_output_tokens=int(os.getenv("NPC_DIRECTOR_MAX_OUTPUT_TOKENS", "4096")),
            max_episode_participants=int(os.getenv("NPC_DIRECTOR_MAX_EPISODE_PARTICIPANTS", "4")),
            max_autonomous_turns=int(os.getenv("NPC_DIRECTOR_MAX_AUTONOMOUS_TURNS", "6")),
            max_new_quests=int(os.getenv("NPC_DIRECTOR_MAX_NEW_QUESTS", "1")),
            max_total_tokens=int(os.getenv("NPC_DIRECTOR_MAX_TOTAL_TOKENS", "96000")),
            max_node_repairs=int(os.getenv("NPC_DIRECTOR_MAX_NODE_REPAIRS", "1")),
            planning_timeout_seconds=float(
                os.getenv("NPC_DIRECTOR_PLANNING_TIMEOUT_SECONDS", "180")
            ),
            quality_review_enabled=os.getenv("NPC_DIRECTOR_QUALITY_REVIEW", "true").lower()
            not in {"0", "false", "no"},
            inline_output_schema=(
                None
                if os.getenv("NPC_DIRECTOR_INLINE_OUTPUT_SCHEMA", "auto").lower() == "auto"
                else os.getenv("NPC_DIRECTOR_INLINE_OUTPUT_SCHEMA", "true").lower()
                not in {"0", "false", "no"}
            ),
            prompt_json_schemas=tuple(
                name.strip()
                for name in os.getenv("NPC_DIRECTOR_PROMPT_JSON_SCHEMAS", "NarrativePlan").split(
                    ","
                )
                if name.strip()
            ),
            node_reasoning_effort=os.getenv("NPC_DIRECTOR_NODE_REASONING_EFFORT", "low"),
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
        if self.node_reasoning_effort not in {"low", "medium", "high"}:
            raise ValueError("node reasoning effort must be low, medium or high")
        if not 1 <= self.max_episode_participants <= 20:
            raise ValueError("episode participants must be between 1 and 20")
        if not 0 <= self.max_autonomous_turns <= 20 or not 0 <= self.max_new_quests <= 10:
            raise ValueError("invalid autonomous turn or new quest budget")
        if self.max_total_tokens < 0 or not 0 <= self.max_node_repairs <= 10:
            raise ValueError("invalid token or node repair budget")
        if not 1 <= self.max_model_calls <= 64:
            raise ValueError("NPC_DIRECTOR_MAX_MODEL_CALLS must be between 1 and 64")
        if not 4 <= self.max_execution_nodes <= 32:
            raise ValueError("NPC_DIRECTOR_MAX_EXECUTION_NODES must be between 4 and 32")
        if not 0 <= self.max_plan_revisions <= 4:
            raise ValueError("NPC_DIRECTOR_MAX_PLAN_REVISIONS must be between 0 and 4")
        if self.planning_timeout_seconds <= 0:
            raise ValueError("NPC_DIRECTOR_PLANNING_TIMEOUT_SECONDS must be positive")
        if not 256 <= self.max_output_tokens <= 16384:
            raise ValueError("NPC_DIRECTOR_MAX_OUTPUT_TOKENS must be between 256 and 16384")
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

    def requires_inline_schema(self, model: object) -> bool:
        if self.inline_output_schema is not None:
            return self.inline_output_schema
        return not isinstance(model, str) or not model.startswith("gpt-")

    def estimate_cost(self, input_tokens: int, output_tokens: int) -> float | None:
        if self.input_cost_per_million is None or self.output_cost_per_million is None:
            return None
        return (
            input_tokens * self.input_cost_per_million
            + output_tokens * self.output_cost_per_million
        ) / 1_000_000


def _optional_string(name: str) -> str | None:
    return os.getenv(name, "").strip() or None
