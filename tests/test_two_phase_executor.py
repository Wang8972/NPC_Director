from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

import npc_director.orchestration.executor as executor_module
from npc_director.config import Settings
from npc_director.contracts import DelegationEvent, DirectorInput, SpecialistName, TurnProposal
from npc_director.orchestration.executor import (
    OpenAIDirectorExecutor,
    build_summary_input,
)

PHASE_ONE_AGENT = object()
SUMMARY_AGENT = object()


def make_settings(tmp_path, model: str = "qwen3.7-max") -> Settings:
    return Settings(model=model, database_path=tmp_path / "executor.db")


def make_director_input() -> DirectorInput:
    return DirectorInput.model_validate(
        {
            "session_id": "two-phase-session",
            "turn_id": "two_phase_001",
            "npc_id": "elder_maren",
            "player_input": "你好，玛伦长老。",
            "scene_summary": "村门口，气氛平静。",
            "character_core": "玛伦是守护灰港村的长老。",
            "allowed_actions": ["idle", "small_nod"],
            "allowed_faces": ["neutral", "happy"],
        }
    )


def make_proposal(specialists: list[str] | None = None) -> TurnProposal:
    return TurnProposal.model_validate(
        {
            "plan": {
                "goal": "回应玩家问候",
                "intent": "greeting",
                "required_specialists": specialists or ["screenwriter"],
            },
            "performance": {
                "dialogue": {"text": "欢迎来到灰港。"},
                "emotion": {"coarse": "joy", "primary": "warm"},
                "face_cues": [{"preset": "happy"}],
                "body_cues": [{"action": "small_nod"}],
                "confidence": 0.9,
            },
        }
    )


class FakeRunResult:
    def __init__(self, final_output, new_items=(), response_id="fake-response"):
        self.final_output = final_output
        self.new_items = list(new_items)
        self.last_response_id = response_id
        self.context_wrapper = SimpleNamespace(
            usage=SimpleNamespace(input_tokens=10, output_tokens=5, total_tokens=15)
        )

    def final_output_as(self, output_type, raise_if_incorrect_type=False):
        if raise_if_incorrect_type and not isinstance(self.final_output, output_type):
            raise TypeError(f"final output is not {output_type.__name__}")
        return self.final_output


def build_executor(settings: Settings) -> OpenAIDirectorExecutor:
    return OpenAIDirectorExecutor(
        settings,
        agent_factory=lambda _settings: PHASE_ONE_AGENT,
        summary_agent_factory=lambda _settings: SUMMARY_AGENT,
    )


def install_fake_runner(monkeypatch, run_agents: list, responder) -> None:
    async def fake_run(agent, run_input, **kwargs):
        run_agents.append(agent)
        return responder(agent, run_input, kwargs)

    monkeypatch.setattr(executor_module.Runner, "run", staticmethod(fake_run))


def test_two_phase_runs_summary_agent_and_overrides_specialists(tmp_path, monkeypatch) -> None:
    settings = make_settings(tmp_path)
    run_agents: list = []
    proposal = make_proposal(specialists=["baseline"])

    def responder(agent, run_input, kwargs):
        if agent is PHASE_ONE_AGENT:
            hooks = kwargs["hooks"]
            hooks.delegations.append(
                DelegationEvent(
                    specialist=SpecialistName.NARRATIVE_PLANNER,
                    tool_name="narrative_planner",
                    call_id="unfinished-call",
                    input_payload="{}",
                    status="started",
                )
            )
            for specialist, tool_name in (
                (SpecialistName.SCREENWRITER, "screenwriter"),
                (SpecialistName.PERFORMANCE, "performance_specialist"),
                (SpecialistName.SCREENWRITER, "screenwriter"),
            ):
                hooks.delegations.append(
                    DelegationEvent(
                        specialist=specialist,
                        tool_name=tool_name,
                        call_id=f"call-{len(hooks.delegations)}",
                        input_payload="{}",
                        status="completed",
                    )
                )
            return FakeRunResult("阶段一文本汇总")
        assert agent is SUMMARY_AGENT
        assert "阶段一文本汇总" in run_input
        return FakeRunResult(proposal)

    install_fake_runner(monkeypatch, run_agents, responder)

    result = asyncio.run(build_executor(settings).generate(make_director_input()))

    assert run_agents == [PHASE_ONE_AGENT, SUMMARY_AGENT]
    # Delegation trace beats the model's self-report, deduplicated in order.
    assert result.proposal.plan.required_specialists == [
        SpecialistName.SCREENWRITER,
        SpecialistName.PERFORMANCE,
    ]
    # Usage from both phases is accumulated.
    assert result.metrics.input_tokens == 20
    assert result.metrics.output_tokens == 10
    assert result.metrics.total_tokens == 30


def test_legacy_hooks_honor_narrower_per_turn_budgets(tmp_path, monkeypatch) -> None:
    settings = make_settings(tmp_path, model="gpt-4.1-mini")
    captured_hooks = []

    def responder(agent, run_input, kwargs):
        captured_hooks.append(kwargs["hooks"])
        return FakeRunResult(make_proposal())

    install_fake_runner(monkeypatch, [], responder)
    turn_input = make_director_input().model_copy(
        update={
            "max_tool_calls": 2,
            "max_specialist_calls": 3,
            "max_handoffs": 0,
        }
    )

    asyncio.run(build_executor(settings).generate(turn_input))

    assert captured_hooks[0].max_specialist_calls == 2
    assert captured_hooks[0].max_handoffs == 0


def test_default_profile_stays_single_phase(tmp_path, monkeypatch) -> None:
    settings = make_settings(tmp_path, model="gpt-4.1-mini")
    run_agents: list = []
    proposal = make_proposal()

    install_fake_runner(
        monkeypatch,
        run_agents,
        lambda agent, run_input, kwargs: FakeRunResult(proposal),
    )

    result = asyncio.run(build_executor(settings).generate(make_director_input()))

    assert run_agents == [PHASE_ONE_AGENT]
    assert result.proposal.performance.dialogue.text == "欢迎来到灰港。"
    assert result.metrics.total_tokens == 15


def test_two_phase_skips_summary_when_handoff_yields_proposal(tmp_path, monkeypatch) -> None:
    settings = make_settings(tmp_path)
    run_agents: list = []
    proposal = make_proposal()

    install_fake_runner(
        monkeypatch,
        run_agents,
        lambda agent, run_input, kwargs: FakeRunResult(proposal),
    )

    result = asyncio.run(build_executor(settings).generate(make_director_input()))

    # Phase 1 already produced a TurnProposal (e.g. via handoff), so no phase 2.
    assert run_agents == [PHASE_ONE_AGENT]
    # No delegations were recorded, so the self-reported specialists survive.
    assert result.proposal.plan.required_specialists == [SpecialistName.SCREENWRITER]


def test_summary_input_serializes_tool_transcript() -> None:
    director_input = make_director_input()
    phase_one = FakeRunResult(
        "汇总文本",
        new_items=[
            SimpleNamespace(
                type="tool_call_item",
                raw_item=SimpleNamespace(name="screenwriter", arguments='{"draft":"欢迎"}'),
            ),
            SimpleNamespace(type="tool_call_output_item", output='{"text":"欢迎来到灰港。"}'),
        ],
    )

    summary_input = build_summary_input(director_input, phase_one, "修复反馈")

    assert "[调用 screenwriter]" in summary_input
    assert "[工具返回]" in summary_input
    assert "汇总文本" in summary_input
    assert "修复反馈" in summary_input


def test_two_phase_raises_when_summary_output_is_not_proposal(tmp_path, monkeypatch) -> None:
    settings = make_settings(tmp_path)
    run_agents: list = []

    install_fake_runner(
        monkeypatch,
        run_agents,
        lambda agent, run_input, kwargs: FakeRunResult("仍然是纯文本"),
    )

    with pytest.raises(TypeError):
        asyncio.run(build_executor(settings).generate(make_director_input()))
    assert run_agents == [PHASE_ONE_AGENT, SUMMARY_AGENT]
