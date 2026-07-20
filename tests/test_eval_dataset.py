from __future__ import annotations

import json
from pathlib import Path

import pytest

from eval.metrics import evaluate_suite
from eval.runner import load_cases, load_recorded_baseline

CASES_PATH = Path("eval/cases/golden.jsonl")
BASELINES_DIR = Path("eval/baselines")
BASELINE_PATHS = (
    BASELINES_DIR / "recorded.jsonl",
    BASELINES_DIR / "single_agent.jsonl",
    BASELINES_DIR / "main_sub_dynamic.jsonl",
    BASELINES_DIR / "main_sub_fixed_all.jsonl",
    BASELINES_DIR / "no_memory.jsonl",
    BASELINES_DIR / "full_lore.jsonl",
)


def _report(path: Path, architecture: str):
    cases = load_cases(CASES_PATH)
    candidates, errors = load_recorded_baseline(path)
    return evaluate_suite(
        cases,
        candidates,
        mode="recorded",
        architecture=architecture,
        dataset_errors=errors,
    )


def _jsonl_rows(path: Path) -> list[dict[str, object]]:
    lines = path.read_text(encoding="utf-8").splitlines()
    assert lines
    assert all(line.strip() for line in lines)
    return [json.loads(line) for line in lines]


def test_golden_dataset_has_m4_coverage_and_preserves_original_ids() -> None:
    cases = load_cases(CASES_PATH)
    case_ids = {case.id for case in cases}

    assert 30 <= len(cases) <= 40
    assert {
        "greeting_001",
        "lore_001",
        "quest_001",
        "reconciliation_001",
        "insult_001",
        "threat_001",
        "prompt_injection_001",
        "critical_choice_001",
        "secret_lore_001",
        "gratitude_001",
        "farewell_001",
        "clarification_001",
    } <= case_ids
    assert {
        "promise_followup_001",
        "promise_conflict_001",
        "relationship_change_001",
        "player_choice_001",
        "lore_private_denied_001",
        "lore_unlocked_001",
        "complex_betrayal_001",
        "action_allowlist_001",
        "low_confidence_critical_001",
        "prompt_injection_encoded_001",
        "ambiguity_pronoun_001",
        "interrupt_replan_001",
        "continuity_001",
    } <= case_ids


@pytest.mark.parametrize("baseline_path", BASELINE_PATHS)
def test_every_baseline_has_exactly_the_golden_ids(baseline_path: Path) -> None:
    case_ids = [case.id for case in load_cases(CASES_PATH)]
    rows = _jsonl_rows(baseline_path)
    candidates, errors = load_recorded_baseline(baseline_path)

    assert not errors
    assert len(rows) == len(case_ids)
    assert [row["id"] for row in rows] == case_ids
    assert [candidate.id for candidate in candidates] == case_ids


@pytest.mark.parametrize(
    "baseline_path",
    [BASELINES_DIR / "recorded.jsonl", BASELINES_DIR / "single_agent.jsonl"],
)
def test_single_agent_baselines_pass_schema_and_quality(baseline_path: Path) -> None:
    report = _report(baseline_path, "single_agent")

    assert report.passed
    assert report.schema_summary.pass_rate == 1.0
    assert report.quality.pass_rate == 1.0


def test_dynamic_main_sub_passes_quality_and_routing() -> None:
    report = _report(BASELINES_DIR / "main_sub_dynamic.jsonl", "main_sub")

    assert report.passed
    assert report.schema_summary.pass_rate == 1.0
    assert report.quality.pass_rate == 1.0
    assert not report.regressions

    cases = {case.id: case for case in load_cases(CASES_PATH)}
    candidates, errors = load_recorded_baseline(BASELINES_DIR / "main_sub_dynamic.jsonl")
    negotiation = next(candidate for candidate in candidates if candidate.id == "negotiation_001")
    assert not errors
    assert cases["negotiation_001"].expect.required_handoff == "Quest Negotiator"
    assert negotiation.specialists_called == []
    assert negotiation.handoffs == ["Quest Negotiator"]
    guarded_ids = {
        "prompt_injection_001",
        "prompt_injection_encoded_001",
        "prompt_injection_roleplay_001",
    }
    guarded = [candidate for candidate in candidates if candidate.id in guarded_ids]
    assert len(guarded) == len(guarded_ids)
    assert all(candidate.specialists_called == [] for candidate in guarded)
    assert all(
        candidate.metrics and candidate.metrics.model.startswith("input-guard-")
        for candidate in guarded
    )


def test_fixed_all_exposes_unnecessary_calls_on_simple_cases() -> None:
    report = _report(BASELINES_DIR / "main_sub_fixed_all.jsonl", "main_sub")

    assert not report.passed
    assert report.schema_summary.pass_rate == 1.0
    assert "greeting_001:specialist_routing" in report.regressions
    assert "smalltalk_001:specialist_routing" in report.regressions
    assert "action_allowlist_001:specialist_routing" in report.regressions
    assert "negotiation_001:specialist_routing" in report.regressions
    assert "negotiation_001:handoff_routing" in report.regressions
    assert all(
        regression.endswith((":specialist_routing", ":handoff_routing"))
        for regression in report.regressions
    )


def test_no_memory_has_explicit_cross_turn_quality_regressions() -> None:
    report = _report(BASELINES_DIR / "no_memory.jsonl", "main_sub")

    assert not report.passed
    assert report.schema_summary.pass_rate == 1.0
    assert {
        "promise_followup_001:required_text",
        "promise_followup_001:forbidden_text",
        "relationship_change_001:required_text",
        "relationship_change_001:forbidden_text",
        "continuity_001:required_text",
        "continuity_001:forbidden_text",
    } <= set(report.regressions)
    assert not any(item.endswith(":specialist_routing") for item in report.regressions)
    assert not any(item.endswith(":handoff_routing") for item in report.regressions)


def test_full_lore_passes_but_costs_far_more_than_dynamic() -> None:
    dynamic = _report(BASELINES_DIR / "main_sub_dynamic.jsonl", "main_sub")
    full_lore = _report(BASELINES_DIR / "full_lore.jsonl", "main_sub")

    assert full_lore.passed
    assert full_lore.quality.pass_rate == 1.0
    assert full_lore.system.tokens.total > dynamic.system.tokens.total * 3
    assert full_lore.system.latency.average_ms > dynamic.system.latency.average_ms * 3


@pytest.mark.parametrize("baseline_path", BASELINE_PATHS)
def test_all_recorded_flags_use_flag_patch_arrays(baseline_path: Path) -> None:
    for row in _jsonl_rows(baseline_path):
        state_changes = row["proposal"]["plan"].get("proposed_state_changes", {})
        if "flags" in state_changes:
            assert isinstance(state_changes["flags"], list)
            assert all(set(flag) == {"name", "value"} for flag in state_changes["flags"])
