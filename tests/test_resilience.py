from __future__ import annotations

from dataclasses import dataclass

import httpx
import pytest
from openai import APITimeoutError

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
