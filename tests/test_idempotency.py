from __future__ import annotations

import asyncio

import pytest

from npc_director.contracts import (
    EngineEvent,
    NPCDomainState,
    StateChangeProposal,
    TurnRequest,
    TurnStatus,
)
from npc_director.state import (
    DomainStateStore,
    EventLog,
    OptimisticLockError,
    TurnStore,
)


def request(turn_id: str = "session-1:1") -> TurnRequest:
    return TurnRequest.model_validate(
        {
            "session_id": "session-1",
            "turn_id": turn_id,
            "npc_id": "elder_maren",
            "player_input": "我会信守承诺。",
            "scene": {"location": "village_gate"},
            "character_core": "重视承诺的长老。",
        }
    )


def relationship_patch(delta: int = 2) -> StateChangeProposal:
    return StateChangeProposal.model_validate({"relationship": {"trust_delta": delta}})


@pytest.mark.asyncio
async def test_completed_event_commits_once_after_emit(tmp_path) -> None:
    database = tmp_path / "state.db"
    domain = DomainStateStore(database)
    turns = TurnStore(database)
    events = EventLog(database)
    domain.create(NPCDomainState(npc_id="elder_maren", relationship={"trust": 10}))
    turn = turns.start_turn(request())
    turns.update_status(turn.turn_id, TurnStatus.EMITTED)

    ack = EngineEvent.model_validate(
        {
            "session_id": "session-1",
            "turn_id": turn.turn_id,
            "idempotency_key": "emit-key-1",
            "event_type": "ack",
        }
    )
    events.append(ack)
    duplicate_ack = events.append(ack.model_copy(update={"detail": "duplicate_in_flight"}))
    before_completed = domain.get("elder_maren")
    assert before_completed is not None
    assert before_completed.relationship["trust"] == 10
    assert before_completed.version == 0
    assert duplicate_ack.appended is False

    completed = ack.model_copy(update={"event_type": "completed"})
    first_event, second_event = await asyncio.gather(
        events.aappend(completed),
        events.aappend(completed),
    )
    first_commit, duplicate_commit = await asyncio.gather(
        domain.acommit_completed(
            turn.turn_id,
            "elder_maren",
            relationship_patch(),
            expected_version=0,
            allowed_paths=["relationship.trust_delta"],
        ),
        domain.acommit_completed(
            turn.turn_id,
            "elder_maren",
            relationship_patch(),
            expected_version=0,
            allowed_paths=["relationship.trust_delta"],
        ),
    )
    turns.update_status(turn.turn_id, TurnStatus.COMPLETED)

    assert sorted((first_event.appended, second_event.appended)) == [False, True]
    assert sorted((first_commit.applied, duplicate_commit.applied)) == [False, True]
    persisted = domain.get("elder_maren")
    assert persisted is not None
    assert persisted.relationship["trust"] == 12
    assert persisted.version == 1
    assert events.count(turn_id=turn.turn_id) == 2


def test_completed_commit_uses_optimistic_version(tmp_path) -> None:
    domain = DomainStateStore(tmp_path / "state.db")
    domain.get_or_create("elder_maren")
    domain.commit_completed(
        "session-1:1",
        "elder_maren",
        relationship_patch(),
        expected_version=0,
        allowed_paths=["relationship.trust_delta"],
    )

    with pytest.raises(OptimisticLockError):
        domain.commit_completed(
            "session-1:2",
            "elder_maren",
            relationship_patch(),
            expected_version=0,
            allowed_paths=["relationship.trust_delta"],
        )


def test_empty_patch_does_not_conflict_with_newer_domain_version(tmp_path) -> None:
    domain = DomainStateStore(tmp_path / "state.db")
    domain.get_or_create("elder_maren")
    domain.commit_completed(
        "session-1:change",
        "elder_maren",
        relationship_patch(),
        expected_version=0,
        allowed_paths=["relationship.trust_delta"],
    )

    result = domain.commit_completed(
        "session-1:dialogue-only",
        "elder_maren",
        StateChangeProposal(),
        expected_version=0,
    )

    assert result.applied is True
    assert result.version == 1
