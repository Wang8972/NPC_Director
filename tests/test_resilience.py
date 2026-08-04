from __future__ import annotations

from dataclasses import dataclass

import httpx
import pytest
from openai import APITimeoutError

import npc_director.orchestration.executor as executor_module
from npc_director.config import Settings
from npc_director.contracts import BodyAction, DirectorInput, FacePreset
from npc_director.orchestration.executor import ResilientDirectorExecutor


def director_input() -> DirectorInput:
    return DirectorInput(
        session_id="s1",
        turn_id="s1:1",
        npc_id="elder_maren",
        player_input="你好",
        scene_summary="gate",
        character_core="elder",
        allowed_actions=list(BodyAction),
        allowed_faces=list(FacePreset),
    )


@dataclass
class TimeoutExecutor:
    calls: int = 0

    async def generate(self, director_input, *, repair_feedback=None):
        self.calls += 1
        raise APITimeoutError(request=httpx.Request("POST", "https://api.openai.com"))


@dataclass
class InvalidExecutor:
    calls: int = 0

    async def generate(self, director_input, *, repair_feedback=None):
        self.calls += 1
        raise ValueError("invalid contract")


@dataclass
class LocalTimeoutExecutor:
    calls: int = 0

    async def generate(self, director_input, *, repair_feedback=None):
        self.calls += 1
        raise TimeoutError("turn deadline exceeded")


@pytest.mark.asyncio
async def test_retryable_model_failure_degrades_safely() -> None:
    primary = TimeoutExecutor()
    executor = ResilientDirectorExecutor(
        Settings(model_retry_attempts=2),
        primary=primary,
    )

    result = await executor.generate(director_input())

    assert primary.calls == 2
    assert result.metrics.model == "safe-fallback"
    assert result.proposal.performance.confidence == 0
    assert result.proposal.plan.proposed_state_changes.model_dump() == {
        "relationship": None,
        "flags": [],
        "quests": [],
    }


@pytest.mark.asyncio
async def test_non_retryable_contract_failure_is_not_retried() -> None:
    primary = InvalidExecutor()
    executor = ResilientDirectorExecutor(Settings(model_retry_attempts=3), primary=primary)

    with pytest.raises(ValueError, match="invalid contract"):
        await executor.generate(director_input())

    assert primary.calls == 1


@pytest.mark.asyncio
async def test_local_turn_timeout_is_retried_and_degrades_safely() -> None:
    primary = LocalTimeoutExecutor()
    executor = ResilientDirectorExecutor(
        Settings(model_retry_attempts=2),
        primary=primary,
    )

    result = await executor.generate(director_input())

    assert primary.calls == 2
    assert result.metrics.model == "safe-fallback"


@pytest.mark.asyncio
async def test_safe_degraded_result_respects_empty_action_and_face_policy() -> None:
    primary = TimeoutExecutor()
    executor = ResilientDirectorExecutor(
        Settings(model_retry_attempts=1),
        primary=primary,
    )
    constrained = director_input().model_copy(update={"allowed_actions": [], "allowed_faces": []})

    result = await executor.generate(constrained)

    assert result.proposal.performance.body_cues == []
    assert result.proposal.performance.face_cues == []


@pytest.mark.asyncio
async def test_fallback_model_replaces_every_orchestration_role(monkeypatch) -> None:
    captured_settings: list[Settings] = []

    class FallbackExecutor:
        async def generate(self, director_input, *, repair_feedback=None):
            return executor_module._safe_degraded_result(director_input)

    def build_fallback(settings, lore_retriever):
        captured_settings.append(settings)
        return FallbackExecutor()

    monkeypatch.setattr(executor_module, "_build_primary_executor", build_fallback)
    executor = ResilientDirectorExecutor(
        Settings(
            model="primary",
            director_model="primary-director",
            narrative_model="primary-narrative",
            lore_model="primary-lore",
            screenwriter_model="primary-screenwriter",
            performance_model="primary-performance",
            fallback_model="fallback",
            model_retry_attempts=1,
        ),
        primary=TimeoutExecutor(),
    )

    await executor.generate(director_input())

    fallback_settings = captured_settings[0]
    assert {
        fallback_settings.model_for(role)
        for role in ("director", "narrative", "lore", "screenwriter", "performance")
    } == {"fallback"}
