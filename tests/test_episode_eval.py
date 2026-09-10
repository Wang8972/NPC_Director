from __future__ import annotations

import json

import pytest

from eval.episode_runner import (
    ACTORS,
    EpisodeQualityVerdict,
    LiveEpisodeTransport,
    load_episode_cases,
    run_episode_case,
    run_episode_suite,
    summarize_episode_results,
)
from npc_director.config import Settings
from npc_director.orchestration.bounded_executor import TypedModelCall
from scripts.run_episode_demo import demo_case

CASES = load_episode_cases()
BY_ID = {case.id: case for case in CASES}


def test_multiturn_catalog_contains_all_eight_granularity_regressions():
    assert len(CASES) >= 32
    assert len(BY_ID) == len(CASES)
    assert all(len(case.turns) >= 2 for case in CASES)
    assert {
        "near_action",
        "long_parent_steps",
        "existing_branch",
        "authored_encounter",
        "meaningful_short_quest",
        "merge_existing_quest",
        "reject_unmotivated_quest",
        "duplicate_content_receipt",
    } <= {case.id for case in CASES if "granularity" in case.tags}


@pytest.mark.asyncio
@pytest.mark.parametrize("case", CASES, ids=[case.id for case in CASES])
async def test_recorded_episode_drives_production_service_and_completion(case, tmp_path):
    result = await run_episode_case(case, settings=Settings(), workdir=tmp_path)
    assert result["structural_passed"], {
        "failed_checks": [key for key, value in result["checks"].items() if not value],
        "errors": result["errors"],
        "invariants": result["invariant_errors"],
    }
    assert result["source"] == "scripted_fixture"
    assert result["quality"] is None
    assert result["goal_passed"] is None
    assert result["quality_status"] == "not_measured_in_recorded_mode"
    assert result["generation_metrics"]["fixture_calls"] > 0
    assert result["generation_metrics"]["model_calls"] == 0
    assert result["generation_metrics"]["total_tokens"] == 0
    assert result["fallback_count"] == 0
    assert all(item["mode"] == "recorded" for item in [result])


@pytest.mark.asyncio
async def test_completed_commitment_is_durable_across_followup(tmp_path):
    result = await run_episode_case(BY_ID["promise_followup"], workdir=tmp_path)
    state = result["final_contexts"]["main"]["elder_maren"]["dialogue_state"]
    assert state["commitments"]
    assert state["commitments"][0]["text"] == "我会核对记录，确认后告诉你。"


@pytest.mark.asyncio
async def test_interrupted_content_and_speech_never_enter_completed_context(tmp_path):
    case = BY_ID["interrupted_content"]
    result = await run_episode_case(case, workdir=tmp_path)
    assert result["published_content"] == []
    assert result["new_quests"] == []
    for context in result["final_contexts"]["main"].values():
        assert case.turns[0].fixture_reply not in " ".join(context["history"])


@pytest.mark.asyncio
async def test_private_fact_does_not_enter_other_actor_context(tmp_path):
    result = await run_episode_case(BY_ID["private_knowledge"], workdir=tmp_path)
    contexts = result["final_contexts"]["main"]
    secret = "紫鸢十七"
    assert secret in json.dumps(contexts["elder_maren"]["knowledge"], ensure_ascii=False)
    assert secret not in json.dumps(contexts["village_guard"], ensure_ascii=False)
    assert secret not in json.dumps(contexts["herbalist_iona"], ensure_ascii=False)


@pytest.mark.asyncio
async def test_demo_really_emits_three_actors_and_publishes_an_offer(tmp_path):
    result = await run_episode_case(demo_case(), workdir=tmp_path)
    assert result["structural_passed"], result["errors"]
    assert {item["npc_id"] for item in result["transcript"] if item["role"] == "npc"} == set(ACTORS)
    assert len(result["new_quests"]) == 1
    assert result["new_quests"][0]["status"] == "offered"
    roles = {call["schema"] for call in result["call_summaries"]}
    assert {"ContentCandidate", "ContentReview"} <= roles
    # Requesting other actors' terms does not run a negotiator before those
    # terms have actually arrived. Follow-ups here only acknowledge pending work.


@pytest.mark.asyncio
async def test_whole_episode_judge_is_separate_and_never_sees_fixture_answers(monkeypatch):
    seen = []

    async def capture(self, agent, run_input, output_type):
        seen.append((agent.name, json.loads(run_input), output_type))
        return TypedModelCall(
            output=EpisodeQualityVerdict(
                task_completion=4,
                continuity=4,
                persona=4,
                naturalness=4,
                performance_alignment=4,
                passed=True,
            )
        )

    monkeypatch.setattr(LiveEpisodeTransport, "__call__", capture)
    judge = LiveEpisodeTransport(Settings())
    case = BY_ID["composite_request"]
    transcript = [{"role": "npc", "npc_id": "elder_maren", "text": "实际生成的对话"}]
    await judge.evaluate(case, {"transcript": transcript, "checks": {}, "published_content": []})
    name, payload, schema = seen[0]
    assert name == "Independent Episode Quality Judge"
    assert schema is EpisodeQualityVerdict
    assert payload["transcript"] == transcript
    encoded = json.dumps(payload, ensure_ascii=False)
    assert "fixture_reply" not in encoded
    assert case.turns[0].fixture_reply not in encoded
    assert len(payload["player_turns"]) == len(case.turns)


@pytest.mark.asyncio
async def test_report_is_incremental_and_refuses_to_overwrite_existing_report(tmp_path):
    path = tmp_path / "report.json"
    report = await run_episode_suite([BY_ID["duplicate_input"]], repeats=2, output_path=path)
    assert len(report["results"]) == 2
    assert report["summary"]["naturalness_mean"] is None
    assert report["summary"]["meets_live_acceptance"] is False
    saved = path.read_text()
    assert json.loads(saved)["completed_at"]
    with pytest.raises(FileExistsError):
        await run_episode_suite([BY_ID["duplicate_input"]], output_path=path)
    assert path.read_text() == saved


def test_live_acceptance_counts_failed_judges_and_fallbacks_in_denominator():
    good = {
        "mode": "live",
        "structural_passed": True,
        "goal_passed": True,
        "quality": {"naturalness": 4, "persona": 4},
        "fallback_count": 0,
        "generation_metrics": {"total_tokens": 200, "latency_ms": 100},
    }
    failed = {**good, "goal_passed": False, "quality": None, "fallback_count": 1}
    summary = summarize_episode_results([good, failed])
    assert summary["live_goal_success_rate"] == 0.5
    assert summary["fallback_runs"] == 1
    assert summary["meets_live_acceptance"] is False
    assert summary["generation_tokens"] == 400
