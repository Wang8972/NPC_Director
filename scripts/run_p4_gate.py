# ruff: noqa: E501 - pytest node IDs are intentionally kept intact for auditability.
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

RECORDED = {
    "EV-G01": "tests/test_p2_fake_director.py::test_p2_fake_runs_both_routes_and_all_four_interactions",
    "EV-G02": "tests/test_p2_fake_director.py::test_invalid_actor_object_and_authority_never_emit_scene_plan",
    "EV-G03": "tests/test_p3_real_director.py::test_real_model_candidate_uses_existing_rules_and_completed_commit",
    "EV-G04": "tests/test_p3_real_director.py::test_governance_blocks_private_surface_leak_even_without_fact_self_report",
    "EV-K01": "tests/test_p3_real_director.py::test_trusted_projection_isolates_npc_private_facts",
    "EV-K02": "tests/test_p3_real_director.py::test_trusted_projection_isolates_npc_private_facts",
    "EV-K03": "tests/test_p3_real_director.py::test_player_fact_transfer_updates_only_selected_npc",
    "EV-K04": "tests/test_p2_fake_director.py::test_p2_fake_runs_both_routes_and_all_four_interactions",
    "EV-A01": "tests/test_p3_real_director.py::test_real_model_candidate_uses_existing_rules_and_completed_commit",
    "EV-A02": "tests/test_p2_fake_director.py::test_invalid_actor_object_and_authority_never_emit_scene_plan",
    "EV-A03": "tests/test_prototype_spikes.py::test_s4_seven_action_governance_and_post_commit_reveal",
    "EV-A04": "tests/test_p2_fake_director.py::test_repeated_plan_and_completed_are_idempotent",
    "EV-C01": "tests/test_p3_real_director.py::test_npc_to_npc_second_beat_is_real_and_cannot_create_third_beat",
    "EV-C02": "tests/test_p2_fake_director.py::test_npc_to_npc_is_exactly_two_beats_and_roundtable_is_refused",
    "EV-C03": "artifact:p3_mock:cooperation",
    "EV-C04": "artifact:p3_mock:procedure",
    "EV-S01": "tests/test_p3_real_director.py::test_prompt_injection_is_blocked_before_model_call",
    "EV-S02": "tests/test_p2_fake_director.py::test_interrupt_does_not_commit_and_retry_can_succeed",
}

FUNCTIONAL = {
    f"TC-{index:02d}": node
    for index, node in enumerate(
        [
            RECORDED["EV-G01"],
            RECORDED["EV-G04"],
            RECORDED["EV-A01"],
            RECORDED["EV-A03"],
            RECORDED["EV-C03"],
            RECORDED["EV-K03"],
            RECORDED["EV-C01"],
            RECORDED["EV-A02"],
            RECORDED["EV-S02"],
            RECORDED["EV-A04"],
            RECORDED["EV-S01"],
            "tests/test_p2_fake_director.py::test_p2_server_treats_transport_disconnect_as_a_boundary_event",
            "tests/test_unity_protocol.py::test_protocol_accepts_scene_action_lifecycle_and_rejects_type_mismatch",
            "tests/test_p2_fake_director.py::test_reset_restores_initial_hash_and_only_target_session",
            RECORDED["EV-C03"],
            RECORDED["EV-C04"],
        ],
        start=1,
    )
}

FAULTS = {
    "FT-01": "tests/test_idempotency.py::test_completed_event_commits_once_after_emit",
    "FT-02": "tests/test_unity_client_files.py::test_executor_has_local_idempotency_and_all_feedback_events",
    "FT-03": "tests/test_p2_fake_director.py::test_repeated_plan_and_completed_are_idempotent",
    "FT-04": RECORDED["EV-S02"],
    "FT-05": "tests/test_prototype_spikes.py::test_s4_seven_action_governance_and_post_commit_reveal",
    "FT-06": "tests/test_resilience.py::test_retryable_model_failure_degrades_safely",
    "FT-07": "tests/test_p2_fake_director.py::test_repeated_plan_and_completed_are_idempotent",
    "FT-08": "tests/test_prototype_spikes.py::test_s2_atomic_world_and_npc_commit",
    "FT-09": "tests/test_prototype_spikes.py::test_s2_atomic_world_and_npc_commit",
    "FT-10": "tests/test_p2_fake_director.py::test_interrupt_does_not_commit_and_retry_can_succeed",
    "FT-11": RECORDED["EV-G02"],
    "FT-12": "tests/test_p3_real_director.py::test_model_error_returns_explicit_safe_fallback_without_state_change",
}


def run_node(node: str, artifact: dict) -> dict:
    if node.startswith("artifact:p3_mock:"):
        route = node.rsplit(":", maxsplit=1)[1]
        passed = (
            artifact.get("status") == "pass"
            and artifact.get("session_report", {}).get("route_success_counts", {}).get(route, 0)
            >= 1
        )
        return {"status": "pass" if passed else "fail", "source": node}
    result = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", node],
        capture_output=True,
        text=True,
        check=False,
    )
    return {
        "status": "pass" if result.returncode == 0 else "fail",
        "source": node,
        "returncode": result.returncode,
        "output_tail": "\n".join((result.stdout + result.stderr).splitlines()[-8:]),
    }


def evaluate_group(mapping: dict[str, str], artifact: dict) -> dict[str, dict]:
    cache: dict[str, dict] = {}
    output: dict[str, dict] = {}
    for case_id, node in mapping.items():
        if node not in cache:
            cache[node] = run_node(node, artifact)
        output[case_id] = cache[node]
    return output


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the deterministic P4 gate")
    parser.add_argument(
        "--mock-report",
        type=Path,
        default=Path("artifacts/prototype-p3/p3-local-mock-report.json"),
    )
    parser.add_argument(
        "--live-report",
        type=Path,
        default=Path("artifacts/prototype-p4/p4-live-report.json"),
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("artifacts/prototype-p4/p4-gate-report.json"),
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    artifact = json.loads(args.mock_report.read_text(encoding="utf-8"))
    full = subprocess.run(
        [sys.executable, "-m", "pytest", "-q"],
        capture_output=True,
        text=True,
        check=False,
    )
    recorded = evaluate_group(RECORDED, artifact)
    functional = evaluate_group(FUNCTIONAL, artifact)
    faults = evaluate_group(FAULTS, artifact)
    live = (
        json.loads(args.live_report.read_text(encoding="utf-8"))
        if args.live_report.exists()
        else {"status": "missing"}
    )
    deterministic_pass = all(
        item["status"] == "pass"
        for group in (recorded, functional, faults)
        for item in group.values()
    )
    passed = full.returncode == 0 and deterministic_pass and live.get("status") == "pass"
    report = {
        "stage": "P4 Automated Eval and Fault Validation",
        "status": "pass" if passed else "in_progress",
        "recorded": recorded,
        "functional": functional,
        "faults": faults,
        "summary": {
            "full_regression_pass": full.returncode == 0,
            "recorded_passed": sum(v["status"] == "pass" for v in recorded.values()),
            "recorded_total": len(recorded),
            "functional_passed": sum(v["status"] == "pass" for v in functional.values()),
            "functional_total": len(functional),
            "faults_passed": sum(v["status"] == "pass" for v in faults.values()),
            "faults_total": len(faults),
            "live_status": live.get("status"),
        },
        "live_report": live,
        "recorded_at": datetime.now(UTC).isoformat(),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(report["summary"], ensure_ascii=False, sort_keys=True))
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
