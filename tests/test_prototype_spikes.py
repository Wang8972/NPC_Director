from __future__ import annotations

from pathlib import Path

from npc_director.prototype.models import ACTION_TYPES
from npc_director.prototype.spikes import run_s2, run_s4, run_s5, run_s6


def test_s2_atomic_world_and_npc_commit(tmp_path: Path) -> None:
    report = run_s2(tmp_path / "s2.sqlite3")

    assert report["status"] == "pass"
    assert report["normal_effect_count"] == 1
    assert report["commit_rows_for_action"] == 1
    assert report["duplicate_effect_count"] == 0
    assert report["half_commit_count"] == 0
    assert report["stale_world_conflicts"] == "10/10"
    assert report["stale_npc_conflicts"] == "10/10"


def test_s4_seven_action_governance_and_post_commit_reveal(tmp_path: Path) -> None:
    report = run_s4(tmp_path / "s4.sqlite3")

    assert report["status"] == "pass"
    assert report["legal_action_types"] == sorted(ACTION_TYPES)
    assert report["illegal_adapter_calls"] == 0
    assert report["pre_commit_reveals"] == 0
    assert report["pre_commit_secret_in_wire"] == 0
    assert report["post_commit_reveals"] == 1
    assert report["interrupted_reveals"] == 0


def test_s5_completed_is_the_only_second_beat_trigger(tmp_path: Path) -> None:
    report = run_s5(tmp_path / "s5.sqlite3")

    assert report["status"] == "pass"
    assert report["plans_after_ack"] == 1
    assert report["plans_after_started"] == 1
    assert report["plans_after_completed"] == 2
    assert report["plans_after_duplicate_completed"] == 2
    assert report["hop_two_reason"] == "error_chain_limit"
    assert report["unlocked_after_b_error"] is True
    assert report["unlocked_after_a_interrupted"] is True


def test_s6_fake_director_runs_both_routes_without_api_key(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    report = run_s6(tmp_path / "s6.sqlite3")

    assert report["status"] == "pass"
    assert report["api_key_present"] is False
    assert report["api_key_used"] is False
    assert report["prototype_success_count"] == "20/20"
    assert report["normalized_success_projection_count"] == 1
    assert report["engineering_violations"] == 0
