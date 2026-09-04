from __future__ import annotations

import inspect
from pathlib import Path
from typing import Any

from npc_director.contracts import (
    PerformanceEventMessage,
    PerformancePlanMessage,
    SceneActionEventMessage,
    SceneActionPlanMessage,
    SceneObserveRequestMessage,
    TurnRequestMessage,
    WorldEventMessage,
)
from npc_director.prototype.fake_director import PrototypeFakeDirectorSession


def turn(session_id: str, turn_id: str, npc_id: str, fixture_id: str) -> TurnRequestMessage:
    return TurnRequestMessage.model_validate(
        {
            "message_id": f"request:{turn_id}",
            "payload": {
                "session_id": session_id,
                "turn_id": turn_id,
                "npc_id": npc_id,
                "player_input": fixture_id,
                "scene": {"location": "prototype_gate_repair"},
                "character_core": "P2 Fake fixture; backend profile is authoritative.",
            },
        }
    )


def observe(
    session: PrototypeFakeDirectorSession,
    request_id: str,
    object_id: str,
) -> list[Any]:
    world = session.repository.get_world(session.session_id)
    message = SceneObserveRequestMessage.model_validate(
        {
            "message_id": f"observe:{request_id}",
            "payload": {
                "session_id": session.session_id,
                "request_id": request_id,
                "object_id": object_id,
                "expected_world_version": world.version,
            },
        }
    )
    return session.handle(message)


def submit(
    session: PrototypeFakeDirectorSession,
    index: int,
    npc_id: str,
    fixture_id: str,
) -> list[Any]:
    turn_id = f"{session.session_id}:t{index}"
    return session.handle(turn(session.session_id, turn_id, npc_id, fixture_id))


def complete_scene_action(
    session: PrototypeFakeDirectorSession,
    messages: list[Any],
    *,
    terminal: str = "completed",
) -> list[Any]:
    plan = next(message for message in messages if isinstance(message, SceneActionPlanMessage))
    action = plan.payload.action
    before_version = session.repository.get_world(session.session_id).version
    for event_type in ("ack", "started"):
        response = session.handle(
            SceneActionEventMessage.model_validate(
                {
                    "message_id": f"event:{action.action_id}:{event_type}",
                    "type": f"scene.action.{event_type}",
                    "payload": {
                        "session_id": session.session_id,
                        "turn_id": action.turn_id,
                        "action_id": action.action_id,
                        "idempotency_key": plan.payload.idempotency_key,
                        "event_type": event_type,
                    },
                }
            )
        )
        assert response == []
        assert session.repository.get_world(session.session_id).version == before_version
    return session.handle(
        SceneActionEventMessage.model_validate(
            {
                "message_id": f"event:{action.action_id}:{terminal}",
                "type": f"scene.action.{terminal}",
                "payload": {
                    "session_id": session.session_id,
                    "turn_id": action.turn_id,
                    "action_id": action.action_id,
                    "idempotency_key": plan.payload.idempotency_key,
                    "event_type": terminal,
                },
            }
        )
    )


def finish_internal_reply(
    session: PrototypeFakeDirectorSession,
    messages: list[Any],
) -> None:
    reply = next(
        message
        for message in messages
        if isinstance(message, PerformancePlanMessage)
        and message.payload.directive.turn_id.endswith(":reply")
    )
    directive = reply.payload.directive
    session.handle(
        PerformanceEventMessage.model_validate(
            {
                "message_id": f"event:{directive.turn_id}:completed",
                "type": "performance.completed",
                "payload": {
                    "session_id": session.session_id,
                    "turn_id": directive.turn_id,
                    "idempotency_key": reply.payload.idempotency_key,
                    "event_type": "completed",
                },
            }
        )
    )


def common_prefix(session: PrototypeFakeDirectorSession, offset: int = 0) -> int:
    observe(session, f"observe-console-{offset}", "gate_console")
    response = complete_scene_action(
        session,
        submit(session, offset + 1, "mechanic_lia", "fixture:inspect_generator"),
    )
    assert any(isinstance(message, WorldEventMessage) for message in response)
    response = complete_scene_action(
        session,
        submit(
            session,
            offset + 2,
            "mechanic_lia",
            "fixture:lia_tell_maren_diagnosis",
        ),
    )
    finish_internal_reply(session, response)
    return offset + 2


def finish_route(session: PrototypeFakeDirectorSession, index: int) -> None:
    complete_scene_action(
        session,
        submit(session, index + 1, "mechanic_lia", "fixture:install_fuse"),
    )
    complete_scene_action(
        session,
        submit(session, index + 2, "guard_captain_maren", "fixture:authorize_restart"),
    )
    complete_scene_action(
        session,
        submit(session, index + 3, "guard_captain_maren", "fixture:restart_gate"),
    )


def reset_session(session: PrototypeFakeDirectorSession, run_id: int) -> list[Any]:
    return session.handle(
        {
            "message_id": f"reset-{run_id}",
            "type": "prototype.reset.request",
            "payload": {
                "session_id": session.session_id,
                "reset_token": f"p2-reset-{run_id}",
            },
        }
    )


def run_cooperation(session: PrototypeFakeDirectorSession, offset: int) -> None:
    index = common_prefix(session, offset)
    submit(session, index + 1, "porter_finn", "fixture:tell_diagnosis")
    complete_scene_action(
        session,
        submit(session, index + 2, "porter_finn", "fixture:ask_fuse_location"),
    )
    complete_scene_action(
        session,
        submit(session, index + 3, "porter_finn", "fixture:cooperation_offer"),
    )
    finish_route(session, index + 3)


def run_procedure(session: PrototypeFakeDirectorSession, offset: int) -> None:
    index = common_prefix(session, offset)
    observe(session, f"observe-manifest-{offset}", "manifest_board")
    submit(session, index + 1, "guard_captain_maren", "fixture:tell_manifest")
    complete_scene_action(
        session,
        submit(
            session,
            index + 2,
            "guard_captain_maren",
            "fixture:request_authorization",
        ),
    )
    complete_scene_action(
        session,
        submit(session, index + 3, "porter_finn", "fixture:give_fuse"),
    )
    finish_route(session, index + 3)


def test_p2_fake_runs_both_routes_and_all_four_interactions(tmp_path: Path) -> None:
    session = PrototypeFakeDirectorSession(tmp_path / "p2.sqlite3", reset_on_start=True)
    try:
        for run_id in range(10):
            if run_id > 0:
                reset_session(session, run_id)
            run_cooperation(session, run_id * 100)
        for run_id in range(10):
            reset = reset_session(session, 100 + run_id)
            assert reset[0].type == "world.event"
            run_procedure(session, 1000 + run_id * 100)

        report = session.report()
        assert report["status"] == "pass"
        assert report["route_success_counts"] == {"cooperation": 10, "procedure": 10}
        assert report["route_hashes_stable"] == {"cooperation": True, "procedure": True}
        assert report["interaction_types_seen"] == [
            "npc_npc",
            "npc_scene",
            "player_npc",
            "player_scene",
        ]
        assert report["no_api_key_required"] is True
        assert report["route_runs_required"] == 1
        assert report["scripted_route_runs_required"] == 10
    finally:
        session.close()


def test_p2_unity_gate_requires_one_real_run_per_route(tmp_path: Path) -> None:
    session = PrototypeFakeDirectorSession(tmp_path / "unity-gate.sqlite3", reset_on_start=True)
    try:
        run_cooperation(session, 0)
        reset_session(session, 1)
        run_procedure(session, 100)

        report = session.report()
        assert report["status"] == "pass"
        assert report["route_success_counts"] == {"cooperation": 1, "procedure": 1}
        assert report["route_hashes_stable"] == {"cooperation": True, "procedure": True}
    finally:
        session.close()


def test_p2_server_treats_transport_disconnect_as_a_boundary_event() -> None:
    source = Path("scripts/run_p2_fake_server.py").read_text(encoding="utf-8")
    assert "except ConnectionClosed as error:" in source
    assert "Unity connection closed" in source


def test_same_state_and_input_reproduce_plan_rejection_and_hash(tmp_path: Path) -> None:
    first = PrototypeFakeDirectorSession(tmp_path / "first.sqlite3", reset_on_start=True)
    second = PrototypeFakeDirectorSession(tmp_path / "second.sqlite3", reset_on_start=True)
    try:
        for session in (first, second):
            observe(session, "same-observe", "gate_console")
        first_plan = submit(first, 1, "mechanic_lia", "fixture:inspect_generator")
        second_plan = submit(second, 1, "mechanic_lia", "fixture:inspect_generator")
        first_action = next(
            message.payload.action
            for message in first_plan
            if isinstance(message, SceneActionPlanMessage)
        )
        second_action = next(
            message.payload.action
            for message in second_plan
            if isinstance(message, SceneActionPlanMessage)
        )
        assert first_action == second_action
        assert first.semantic_state_hash() == second.semantic_state_hash()
        complete_scene_action(first, first_plan)
        complete_scene_action(second, second_plan)

        first_rejection = submit(first, 2, "mechanic_lia", "fixture:unknown_object")
        second_rejection = submit(second, 2, "mechanic_lia", "fixture:unknown_object")
        assert first_rejection[0].payload.summary == second_rejection[0].payload.summary
        assert not any(isinstance(item, SceneActionPlanMessage) for item in first_rejection)
    finally:
        first.close()
        second.close()


def test_invalid_actor_object_and_authority_never_emit_scene_plan(tmp_path: Path) -> None:
    session = PrototypeFakeDirectorSession(tmp_path / "invalid.sqlite3", reset_on_start=True)
    try:
        wrong_actor = submit(session, 1, "porter_finn", "fixture:inspect_generator")
        unknown_object = submit(session, 2, "mechanic_lia", "fixture:unknown_object")
        unauthorized = submit(session, 3, "mechanic_lia", "fixture:unauthorized_restart")
        for result in (wrong_actor, unknown_object, unauthorized):
            assert not any(isinstance(item, SceneActionPlanMessage) for item in result)
        assert wrong_actor[0].payload.code == "fixture_actor_mismatch"
        assert unknown_object[0].payload.event_type == "action_rejected"
        assert unauthorized[0].payload.event_type == "action_rejected"
        assert session.repository.count_commits(session_id=session.session_id) == 0
    finally:
        session.close()


def test_interrupt_does_not_commit_and_retry_can_succeed(tmp_path: Path) -> None:
    session = PrototypeFakeDirectorSession(tmp_path / "interrupt.sqlite3", reset_on_start=True)
    try:
        observe(session, "console", "gate_console")
        planned = submit(session, 1, "mechanic_lia", "fixture:inspect_generator")
        before = session.repository.get_world(session.session_id)
        locked = submit(session, 99, "porter_finn", "fixture:roundtable")
        assert locked[0].payload.code == "input_locked"
        plan = next(item for item in planned if isinstance(item, SceneActionPlanMessage))
        bad_event = session.handle(
            SceneActionEventMessage.model_validate(
                {
                    "message_id": "wrong-key",
                    "type": "scene.action.completed",
                    "payload": {
                        "session_id": session.session_id,
                        "turn_id": plan.payload.action.turn_id,
                        "action_id": plan.payload.action.action_id,
                        "idempotency_key": "wrong-key",
                        "event_type": "completed",
                    },
                }
            )
        )
        assert bad_event[0].payload.code == "event_rejected"
        assert session.repository.get_world(session.session_id).version == before.version
        complete_scene_action(session, planned, terminal="interrupted")
        after = session.repository.get_world(session.session_id)
        assert after.version == before.version
        assert after.objective_state == "investigate_fault"
        assert after.pending_action is None

        complete_scene_action(
            session,
            submit(session, 2, "mechanic_lia", "fixture:inspect_generator"),
        )
        assert session.repository.get_world(session.session_id).objective_state == "find_fuse"
    finally:
        session.close()


def test_repeated_plan_and_completed_are_idempotent(tmp_path: Path) -> None:
    session = PrototypeFakeDirectorSession(tmp_path / "repeat.sqlite3", reset_on_start=True)
    try:
        observe(session, "console", "gate_console")
        request = turn(
            session.session_id,
            f"{session.session_id}:same",
            "mechanic_lia",
            "fixture:inspect_generator",
        )
        first = session.handle(request)
        repeated = session.handle(request)
        first_plan = next(item for item in first if isinstance(item, SceneActionPlanMessage))
        repeated_plan = next(item for item in repeated if isinstance(item, SceneActionPlanMessage))
        assert first_plan == repeated_plan
        completed = complete_scene_action(session, first)
        duplicate = session.handle(
            SceneActionEventMessage.model_validate(
                {
                    "message_id": "duplicate-completed",
                    "type": "scene.action.completed",
                    "payload": {
                        "session_id": session.session_id,
                        "turn_id": first_plan.payload.action.turn_id,
                        "action_id": first_plan.payload.action.action_id,
                        "idempotency_key": first_plan.payload.idempotency_key,
                        "event_type": "completed",
                    },
                }
            )
        )
        assert completed[-1].payload.world_version == duplicate[-1].payload.world_version
        assert session.repository.count_commits(session_id=session.session_id) == 2
    finally:
        session.close()


def test_npc_to_npc_is_exactly_two_beats_and_roundtable_is_refused(tmp_path: Path) -> None:
    session = PrototypeFakeDirectorSession(tmp_path / "chain.sqlite3", reset_on_start=True)
    try:
        observe(session, "console", "gate_console")
        complete_scene_action(
            session,
            submit(session, 1, "mechanic_lia", "fixture:inspect_generator"),
        )
        first_beat = submit(
            session,
            2,
            "mechanic_lia",
            "fixture:lia_tell_maren_diagnosis",
        )
        assert sum(isinstance(item, SceneActionPlanMessage) for item in first_beat) == 1
        second_beat = complete_scene_action(session, first_beat)
        assert sum(isinstance(item, PerformancePlanMessage) for item in second_beat) == 1
        finish_internal_reply(session, second_beat)
        assert len(session.adapter.action_plans) == 2
        assert len(session.adapter.internal_reply_plans) == 1

        roundtable = submit(session, 3, "guard_captain_maren", "fixture:roundtable")
        assert len(roundtable) == 1
        assert isinstance(roundtable[0], PerformancePlanMessage)
        assert "不会替你召集自动圆桌" in roundtable[0].payload.directive.dialogue.text
        assert len(session.adapter.internal_reply_plans) == 1
    finally:
        session.close()


def test_reset_restores_initial_hash_and_only_target_session(tmp_path: Path) -> None:
    database = tmp_path / "reset.sqlite3"
    first = PrototypeFakeDirectorSession(database, "p2-a", reset_on_start=True)
    second = PrototypeFakeDirectorSession(database, "p2-b", reset_on_start=True)
    try:
        initial_hash = first.semantic_state_hash()
        observe(first, "console-a", "gate_console")
        observe(second, "console-b", "gate_console")
        second_hash = second.semantic_state_hash()
        first.handle(
            {
                "message_id": "reset-a",
                "type": "prototype.reset.request",
                "payload": {"session_id": "p2-a", "reset_token": "p2-reset-a"},
            }
        )
        assert first.semantic_state_hash() == initial_hash
        assert second.semantic_state_hash() == second_hash
    finally:
        first.close()
        second.close()


def test_p2_fake_source_does_not_read_api_keys() -> None:
    source = inspect.getsource(PrototypeFakeDirectorSession)
    assert "OPENAI_API_KEY" not in source
    assert "os.getenv" not in source
