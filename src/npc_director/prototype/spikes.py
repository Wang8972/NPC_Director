from __future__ import annotations

import json
import os
from pathlib import Path

from npc_director.prototype.harness import FakePrototypeRouteHarness
from npc_director.prototype.models import (
    ACTION_TYPES,
    FACT_FINN_UNAUTHORIZED_MOVE,
    FACT_GENERATOR_MISSING_FUSE,
    RejectedAction,
    SceneActionCandidate,
)
from npc_director.prototype.orchestrator import (
    PrototypeConversationOrchestrator,
    RecordingPrototypeAdapter,
    require_approved,
)
from npc_director.prototype.repository import (
    InjectedCommitFailure,
    PrototypeStateRepository,
    PrototypeVersionConflict,
)
from npc_director.prototype.rules import PrototypePuzzleRules


def _candidate(
    session_id: str,
    index: str,
    actor_id: str,
    action_type: str,
    **kwargs: object,
) -> SceneActionCandidate:
    return SceneActionCandidate(
        session_id=session_id,
        turn_id=f"{session_id}:t:{index}",
        action_id=f"{session_id}:a:{index}",
        actor_id=actor_id,
        action_type=action_type,
        **kwargs,
    )


def _prepare_generator_inspection(
    repository: PrototypeStateRepository,
    session_id: str,
    *,
    prefix: str,
) -> tuple[PrototypeConversationOrchestrator, str, str]:
    repository.initialize(session_id)
    orchestrator = PrototypeConversationOrchestrator(repository)
    observed = orchestrator.submit(
        _candidate(
            session_id,
            f"{prefix}-observe",
            "player",
            "inspect_object",
            object_id="gate_console",
        )
    )
    require_approved(observed)
    inspection = _candidate(
        session_id,
        f"{prefix}-inspect",
        "mechanic_lia",
        "inspect_object",
        object_id="generator",
    )
    submitted = orchestrator.submit(inspection)
    key = require_approved(submitted)
    return orchestrator, inspection.action_id, key


def run_s2(database: str | Path) -> dict[str, object]:
    repository = PrototypeStateRepository(database)
    try:
        normal, action_id, key = _prepare_generator_inspection(
            repository,
            "s2-normal",
            prefix="normal",
        )
        first = normal.handle_action_event(action_id, key, "completed")
        assert first is not None and first.applied
        duplicates = [
            normal.handle_action_event(action_id, key, "completed") for _ in range(20)
        ]
        with repository.connection() as connection:
            commit_rows = connection.execute(
                """
                SELECT COUNT(*) AS count FROM prototype_action_commits
                WHERE action_id = ?
                """,
                (action_id,),
            ).fetchone()["count"]

        failing, fail_action_id, fail_key = _prepare_generator_inspection(
            repository,
            "s2-rollback",
            prefix="rollback",
        )
        before_world = repository.get_world("s2-rollback")
        before_npcs = repository.get_npcs("s2-rollback")
        rollback_raised = False
        try:
            failing.handle_action_event(
                fail_action_id,
                fail_key,
                "completed",
                fail_after_world_write=True,
            )
        except InjectedCommitFailure:
            rollback_raised = True
        after_world = repository.get_world("s2-rollback")
        after_npcs = repository.get_npcs("s2-rollback")
        half_commit_count = int(
            before_world.objective_state != after_world.objective_state
            or before_world.discovered_fact_ids != after_world.discovered_fact_ids
            or any(
                before_npcs[npc_id].known_fact_ids != after_npcs[npc_id].known_fact_ids
                for npc_id in before_npcs
            )
        )

        stale_world_conflicts = 0
        stale_npc_conflicts = 0
        for index in range(10):
            session_id = f"s2-stale-world-{index}"
            flow, stale_action, stale_key = _prepare_generator_inspection(
                repository,
                session_id,
                prefix="world",
            )
            repository.force_world_version_for_test(session_id)
            try:
                flow.handle_action_event(stale_action, stale_key, "completed")
            except PrototypeVersionConflict:
                stale_world_conflicts += 1

        for index in range(10):
            session_id = f"s2-stale-npc-{index}"
            flow, stale_action, stale_key = _prepare_generator_inspection(
                repository,
                session_id,
                prefix="npc",
            )
            repository.force_npc_version_for_test(session_id, "mechanic_lia")
            try:
                flow.handle_action_event(stale_action, stale_key, "completed")
            except PrototypeVersionConflict:
                stale_npc_conflicts += 1

        passed = all(
            (
                first.world.objective_state == "find_fuse",
                commit_rows == 1,
                all(result is not None and not result.applied for result in duplicates),
                rollback_raised,
                half_commit_count == 0,
                stale_world_conflicts == 10,
                stale_npc_conflicts == 10,
            )
        )
        return {
            "spike": "S2",
            "status": "pass" if passed else "fail",
            "normal_effect_count": 1 if first.world.objective_state == "find_fuse" else 0,
            "duplicate_completed_attempts": 20,
            "commit_rows_for_action": commit_rows,
            "duplicate_effect_count": sum(bool(result and result.applied) for result in duplicates),
            "injected_failure_raised": rollback_raised,
            "half_commit_count": half_commit_count,
            "stale_world_conflicts": f"{stale_world_conflicts}/10",
            "stale_npc_conflicts": f"{stale_npc_conflicts}/10",
        }
    finally:
        repository.close()


def run_s4(database: str | Path) -> dict[str, object]:
    full = FakePrototypeRouteHarness(database, "s4-legal")
    try:
        legal_route = full.run("cooperation")
        legal_types = sorted(set(legal_route["submitted_action_types"]))
    finally:
        full.close()

    repository = PrototypeStateRepository(database)
    try:
        session_id = "s4-invalid"
        repository.initialize(session_id)
        rules = PrototypePuzzleRules()
        adapter = RecordingPrototypeAdapter()
        orchestrator = PrototypeConversationOrchestrator(
            repository,
            rules=rules,
            adapter=adapter,
        )
        invalid_candidates = [
            _candidate(session_id, "unknown-action", "player", "dance"),
            _candidate(
                session_id,
                "unknown-actor",
                "imaginary_npc",
                "inspect_object",
                object_id="gate_console",
            ),
            _candidate(
                session_id,
                "unknown-object",
                "player",
                "inspect_object",
                object_id="imaginary_panel",
            ),
            _candidate(
                session_id,
                "unknown-item",
                "porter_finn",
                "give_item",
                item_id="imaginary_fuse",
                target_id="mechanic_lia",
            ),
            _candidate(
                session_id,
                "missing-fact",
                "mechanic_lia",
                "inspect_object",
                object_id="generator",
            ),
            _candidate(
                session_id,
                "missing-item",
                "mechanic_lia",
                "install_item",
                item_id="spare_fuse",
                object_id="generator",
            ),
            _candidate(
                session_id,
                "unauthorized",
                "mechanic_lia",
                "operate_object",
                object_id="control_cabinet",
                operation="restart_gate_power",
            ),
            _candidate(
                session_id,
                "wrong-order",
                "guard_captain_maren",
                "authorize_object",
                object_id="control_cabinet",
            ),
        ]
        reason_codes: list[str] = []
        adapter_before = adapter.total_plan_count
        for candidate in invalid_candidates:
            result = orchestrator.submit(candidate)
            if result.rejection is not None:
                reason_codes.append(result.rejection.reason_code)
        adapter_after = adapter.total_plan_count

        first_observe = orchestrator.submit(
            _candidate(
                session_id,
                "repeat-first",
                "player",
                "inspect_object",
                object_id="gate_console",
            )
        )
        require_approved(first_observe)
        repeat_result = orchestrator.submit(
            _candidate(
                session_id,
                "repeat-second",
                "player",
                "inspect_object",
                object_id="gate_console",
            )
        )
        if repeat_result.rejection is not None:
            reason_codes.append(repeat_result.rejection.reason_code)

        reveal_session = "s4-reveal"
        repository.initialize(reveal_session)
        reveal_adapter = RecordingPrototypeAdapter()
        reveal_flow = PrototypeConversationOrchestrator(repository, adapter=reveal_adapter)
        reveal_candidate = _candidate(
            reveal_session,
            "reveal",
            "porter_finn",
            "tell_player",
            fact_id=FACT_FINN_UNAUTHORIZED_MOVE,
        )
        reveal_submitted = reveal_flow.submit(reveal_candidate)
        reveal_key = require_approved(reveal_submitted)
        pre_commit_reveals = sum(item.startswith("reveal:") for item in reveal_flow.timeline)
        pre_commit_secret_in_wire = int(
            FACT_FINN_UNAUTHORIZED_MOVE in reveal_adapter.action_plans[0].pre_commit_text
        )
        reveal_flow.handle_action_event(reveal_candidate.action_id, reveal_key, "completed")
        post_commit_reveals = sum(item.startswith("reveal:") for item in reveal_flow.timeline)

        interrupted_session = "s4-interrupted"
        repository.initialize(interrupted_session)
        interrupted_flow = PrototypeConversationOrchestrator(repository)
        interrupted = _candidate(
            interrupted_session,
            "reveal",
            "porter_finn",
            "tell_player",
            fact_id=FACT_FINN_UNAUTHORIZED_MOVE,
        )
        interrupted_result = interrupted_flow.submit(interrupted)
        interrupted_key = require_approved(interrupted_result)
        interrupted_flow.handle_action_event(interrupted.action_id, interrupted_key, "interrupted")
        interrupted_reveals = sum(
            item.startswith("reveal:") for item in interrupted_flow.timeline
        )

        illegal_adapter_calls = adapter_after - adapter_before
        passed = all(
            (
                legal_types == sorted(ACTION_TYPES),
                len(reason_codes) == len(invalid_candidates) + 1,
                illegal_adapter_calls == 0,
                pre_commit_reveals == 0,
                pre_commit_secret_in_wire == 0,
                post_commit_reveals == 1,
                interrupted_reveals == 0,
            )
        )
        return {
            "spike": "S4",
            "status": "pass" if passed else "fail",
            "legal_action_types": legal_types,
            "legal_action_type_coverage": f"{len(legal_types)}/{len(ACTION_TYPES)}",
            "illegal_samples": len(invalid_candidates) + 1,
            "stable_reason_codes": reason_codes,
            "illegal_adapter_calls": illegal_adapter_calls,
            "pre_commit_reveals": pre_commit_reveals,
            "pre_commit_secret_in_wire": pre_commit_secret_in_wire,
            "post_commit_reveals": post_commit_reveals,
            "interrupted_reveals": interrupted_reveals,
        }
    finally:
        repository.close()


def _setup_chain(
    repository: PrototypeStateRepository,
    session_id: str,
) -> tuple[PrototypeConversationOrchestrator, RecordingPrototypeAdapter, SceneActionCandidate, str]:
    flow, inspection_id, inspection_key = _prepare_generator_inspection(
        repository,
        session_id,
        prefix="chain",
    )
    flow.handle_action_event(inspection_id, inspection_key, "completed")
    candidate = _candidate(
        session_id,
        "tell-maren",
        "mechanic_lia",
        "tell_npc",
        target_npc_id="guard_captain_maren",
        fact_id=FACT_GENERATOR_MISSING_FUSE,
    )
    result = flow.submit(candidate)
    key = require_approved(result)
    return flow, flow.adapter, candidate, key


def run_s5(database: str | Path) -> dict[str, object]:
    repository = PrototypeStateRepository(database)
    try:
        flow, adapter, candidate, key = _setup_chain(repository, "s5-completed")
        plans_before_chain = adapter.total_plan_count - 1
        flow.handle_action_event(candidate.action_id, key, "ack")
        after_ack = adapter.total_plan_count - plans_before_chain
        flow.handle_action_event(candidate.action_id, key, "started")
        after_started = adapter.total_plan_count - plans_before_chain
        flow.handle_action_event(candidate.action_id, key, "completed")
        after_completed = adapter.total_plan_count - plans_before_chain
        flow.handle_action_event(candidate.action_id, key, "completed")
        after_duplicate = adapter.total_plan_count - plans_before_chain
        locked_before_b_terminal = flow.is_input_locked("s5-completed")

        world = repository.get_world("s5-completed")
        npc_states = repository.get_npcs("s5-completed")
        hop_two_candidate = _candidate(
            "s5-completed",
            "forbidden-hop2",
            "guard_captain_maren",
            "tell_npc",
            target_npc_id="porter_finn",
            fact_id=FACT_GENERATOR_MISSING_FUSE,
        )
        hop_two = PrototypePuzzleRules().validate(
            hop_two_candidate,
            world,
            npc_states,
            hop_index=1,
        )
        hop_two_reason = (
            hop_two.reason_code if isinstance(hop_two, RejectedAction) else "unexpected_approval"
        )
        b_error_finished = flow.finish_internal_reply(candidate.action_id, "error")
        unlocked_after_b_error = not flow.is_input_locked("s5-completed")

        interrupted, interrupted_adapter, interrupted_candidate, interrupted_key = _setup_chain(
            repository,
            "s5-interrupted",
        )
        interrupt_before = interrupted_adapter.total_plan_count
        interrupted.handle_action_event(
            interrupted_candidate.action_id,
            interrupted_key,
            "interrupted",
        )
        interrupted_second_beats = interrupted_adapter.total_plan_count - interrupt_before
        unlocked_after_interrupt = not interrupted.is_input_locked("s5-interrupted")

        passed = all(
            (
                after_ack == 1,
                after_started == 1,
                after_completed == 2,
                after_duplicate == 2,
                locked_before_b_terminal,
                hop_two_reason == "error_chain_limit",
                b_error_finished,
                unlocked_after_b_error,
                interrupted_second_beats == 0,
                unlocked_after_interrupt,
            )
        )
        return {
            "spike": "S5",
            "status": "pass" if passed else "fail",
            "plans_after_ack": after_ack,
            "plans_after_started": after_started,
            "plans_after_completed": after_completed,
            "plans_after_duplicate_completed": after_duplicate,
            "max_plans_per_chain": after_duplicate,
            "hop_two_reason": hop_two_reason,
            "locked_until_b_terminal": locked_before_b_terminal,
            "unlocked_after_b_error": unlocked_after_b_error,
            "second_beats_after_a_interrupted": interrupted_second_beats,
            "unlocked_after_a_interrupted": unlocked_after_interrupt,
        }
    finally:
        repository.close()


def run_s6(database: str | Path) -> dict[str, object]:
    results: dict[str, list[dict[str, object]]] = {"cooperation": [], "procedure": []}
    for route in ("cooperation", "procedure"):
        for index in range(10):
            session_id = f"s6-{route}-{index}"
            harness = FakePrototypeRouteHarness(database, session_id)
            try:
                results[route].append(harness.run(route))
            finally:
                harness.close()

    cooperation_hashes = {item["semantic_state_hash"] for item in results["cooperation"]}
    procedure_hashes = {item["semantic_state_hash"] for item in results["procedure"]}
    projections = {
        json.dumps(item["normalized_success_projection"], sort_keys=True)
        for route_results in results.values()
        for item in route_results
    }
    success_count = sum(
        item["objective_state"] == "prototype_success"
        for route_results in results.values()
        for item in route_results
    )
    engineering_violations = sum(
        bool(item["input_locked"])
        or item["internal_reply_plan_count"] != 1
        or item["total_plan_count_for_chain"] > 2
        for route_results in results.values()
        for item in route_results
    )
    passed = all(
        (
            success_count == 20,
            len(cooperation_hashes) == 1,
            len(procedure_hashes) == 1,
            len(projections) == 1,
            engineering_violations == 0,
        )
    )
    compact_runs = {
        route: [
            {
                "run": index + 1,
                "semantic_state_hash": item["semantic_state_hash"],
                "normalized_success_projection": item["normalized_success_projection"],
                "world_version_sequence": item["world_version_sequence"],
                "final_world_version": item["world_version"],
                "commit_count": item["commit_count"],
                "action_plan_count": item["action_plan_count"],
                "internal_reply_plan_count": item["internal_reply_plan_count"],
            }
            for index, item in enumerate(route_results)
        ]
        for route, route_results in results.items()
    }
    return {
        "spike": "S6",
        "status": "pass" if passed else "fail",
        "api_key_present": bool(os.environ.get("OPENAI_API_KEY")),
        "api_key_used": False,
        "prototype_success_count": f"{success_count}/20",
        "cooperation_hash_consistency": f"10/10 ({next(iter(cooperation_hashes))})",
        "procedure_hash_consistency": f"10/10 ({next(iter(procedure_hashes))})",
        "normalized_success_projection_count": len(projections),
        "engineering_violations": engineering_violations,
        "runs": compact_runs,
    }


def run_backend_spikes(workdir: str | Path) -> dict[str, object]:
    root = Path(workdir)
    root.mkdir(parents=True, exist_ok=True)
    reports = {
        "S2": run_s2(root / "s2.sqlite3"),
        "S4": run_s4(root / "s4.sqlite3"),
        "S5": run_s5(root / "s5.sqlite3"),
        "S6": run_s6(root / "s6.sqlite3"),
    }
    return {
        "status": "pass"
        if all(report["status"] == "pass" for report in reports.values())
        else "fail",
        "reports": reports,
    }
