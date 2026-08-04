from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

import pytest

from npc_director.contracts import (
    ApprovalRecord,
    ApprovalStatus,
    BodyAction,
    DecisionAction,
    FacePreset,
    FinalizationDecision,
    PerformanceDirective,
    TurnRequest,
    TurnStatus,
)
from npc_director.state import ApprovalStore, OutboxStore, TurnStore


def turn_request(turn_id: str = "session-1:1") -> TurnRequest:
    return TurnRequest.model_validate(
        {
            "session_id": "session-1",
            "turn_id": turn_id,
            "npc_id": "elder_maren",
            "player_input": "你好。",
            "scene": {"location": "village_gate"},
            "character_core": "沉稳克制的村庄长老。",
        }
    )


def directive(turn_id: str = "session-1:1", text: str = "欢迎。") -> PerformanceDirective:
    return PerformanceDirective.model_validate(
        {
            "session_id": "session-1",
            "turn_id": turn_id,
            "npc_id": "elder_maren",
            "dialogue": {"text": text},
            "emotion": {"coarse": "neutral", "primary": "calm"},
            "runtime_meta": {
                "specialists_called": ["baseline"],
                "prompt_versions": ["test-v1"],
            },
        }
    )


@pytest.mark.asyncio
async def test_turn_store_is_restart_and_worker_thread_safe(tmp_path) -> None:
    database = tmp_path / "state.db"
    store = TurnStore(database)
    request = turn_request()

    started = await asyncio.to_thread(store.start_turn, request)
    updated = await store.aupdate_status(started.turn_id, TurnStatus.PENDING_APPROVAL)
    assert updated.status is TurnStatus.PENDING_APPROVAL
    store.close()

    restarted = TurnStore(database)
    recovered = await restarted.aget(request.turn_id)
    assert recovered is not None
    assert recovered.request == request
    assert recovered.status is TurnStatus.PENDING_APPROVAL


def test_turn_store_persists_exact_policy_snapshot(tmp_path) -> None:
    database = tmp_path / "state.db"
    store = TurnStore(database)
    started = store.start_turn(turn_request("session-1:policy"))
    secured = store.save(
        started.model_copy(
            update={
                "policy_digest": "a" * 64,
                "policy_catalog_version": "m0-v1",
                "allowed_actions": [BodyAction.IDLE, BodyAction.NOD],
                "allowed_faces": [FacePreset.NEUTRAL, FacePreset.STERN],
                "allowed_state_paths": [
                    "quests.herbalist_escort.status",
                    "flags.reunion_started",
                ],
                "state_tokens": [
                    "transition_quest:herbalist_escort",
                    "set_flag:reunion_started",
                ],
                "max_tool_calls": 3,
                "max_specialist_calls": 2,
                "max_handoffs": 1,
            }
        )
    )
    store.close()

    recovered = TurnStore(database).require(secured.turn_id)

    assert recovered.policy_digest == "a" * 64
    assert recovered.policy_catalog_version == "m0-v1"
    assert recovered.allowed_actions == [BodyAction.IDLE, BodyAction.NOD]
    assert recovered.allowed_faces == [FacePreset.NEUTRAL, FacePreset.STERN]
    assert recovered.allowed_state_paths == [
        "flags.reunion_started",
        "quests.herbalist_escort.status",
    ]
    assert recovered.state_tokens == [
        "set_flag:reunion_started",
        "transition_quest:herbalist_escort",
    ]
    assert recovered.max_tool_calls == 3
    assert recovered.max_specialist_calls == 2
    assert recovered.max_handoffs == 1


def test_approval_actions_survive_restart(tmp_path) -> None:
    database = tmp_path / "state.db"
    store = ApprovalStore(database)
    records = [
        ApprovalRecord(
            approval_id=f"approval-{action}",
            turn_id=f"session-1:{index}",
            reasons=["manual review"],
            proposed_directive=directive(f"session-1:{index}"),
        )
        for index, action in enumerate(("approve", "reject", "edit"), start=1)
    ]
    for record in records:
        store.create(record)

    approved = store.approve("approval-approve", reviewer="alice")
    rejected = store.reject("approval-reject", reviewer="bob", comment="unsafe")
    edited_directive = directive("session-1:3", "请稍等，我需要确认。")
    edited = store.edit(
        "approval-edit",
        edited_directive,
        reviewer="carol",
        comment="safer wording",
    )
    assert approved.status is ApprovalStatus.APPROVED
    assert rejected.status is ApprovalStatus.REJECTED
    assert edited.status is ApprovalStatus.EDITED
    store.close()

    restarted = ApprovalStore(database)
    assert restarted.require("approval-approve").resolved_directive == directive("session-1:1")
    assert restarted.require("approval-reject").resolved_directive is None
    recovered_edit = restarted.require("approval-edit")
    assert recovered_edit.resolved_directive == edited_directive
    assert restarted.pending() == []


def test_pending_approval_is_recovered_after_restart(tmp_path) -> None:
    database = tmp_path / "state.db"
    record = ApprovalRecord(
        approval_id="approval-pending",
        turn_id="session-1:4",
        reasons=["critical lore choice"],
        proposed_directive=directive("session-1:4"),
    )
    ApprovalStore(database).create(record)

    recovered = ApprovalStore(database).pending(turn_id=record.turn_id)
    assert recovered == [record]


def test_pending_approval_repairs_turn_status_after_partial_failure(tmp_path) -> None:
    database = tmp_path / "state.db"
    turns = TurnStore(database)
    turn = turns.start_turn(turn_request("session-1:partial-approval"))
    approvals = ApprovalStore(database, turn_store=turns)
    record = ApprovalRecord(
        approval_id="approval-partial",
        turn_id=turn.turn_id,
        reasons=["critical choice"],
        proposed_directive=directive(turn.turn_id),
    )
    approvals.create(record)

    recovered = approvals.pause(
        turn,
        FinalizationDecision(
            action=DecisionAction.REQUIRE_APPROVAL,
            reasons=record.reasons,
            directive=record.proposed_directive,
        ),
    )

    assert recovered == record
    repaired_turn = turns.require(turn.turn_id)
    assert repaired_turn.status is TurnStatus.PENDING_APPROVAL
    assert repaired_turn.approval_id == record.approval_id


def test_outbox_due_retry_and_sent_lifecycle(tmp_path) -> None:
    store = OutboxStore(tmp_path / "state.db")
    now = datetime.now(UTC)
    due = store.enqueue("emit-1", {"turn_id": "session-1:1"}, available_at=now)
    future = store.enqueue(
        "emit-2",
        {"turn_id": "session-1:2"},
        available_at=now + timedelta(hours=1),
    )

    assert store.enqueue("emit-1", {"turn_id": "session-1:1"}).message_id == due.message_id
    assert [message.message_id for message in store.due(now=now + timedelta(seconds=1))] == [
        due.message_id
    ]

    failed = store.mark_failed(
        due.message_id,
        "Unity unavailable",
        retry_at=now + timedelta(minutes=5),
    )
    assert failed.attempts == 1
    assert store.due(now=now + timedelta(minutes=1)) == []
    assert [message.message_id for message in store.due(now=now + timedelta(minutes=6))] == [
        due.message_id
    ]

    sent = store.mark_sent(due.message_id)
    assert sent.status == "sent"
    remaining_due = store.due(now=future.available_at)
    assert all(message.message_id != due.message_id for message in remaining_due)
