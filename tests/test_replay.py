from __future__ import annotations

from pathlib import Path

import pytest

from npc_director.config import Settings
from npc_director.contracts import EngineEvent, EngineEventType, TurnRequest
from npc_director.orchestration.context_adapter import DefaultContextBuilder
from npc_director.orchestration.service import NPCDirectorService
from npc_director.orchestration.testing import DeterministicDirectorExecutor
from npc_director.state import ApprovalStore, DomainStateStore, EventLog, OutboxStore, TurnStore
from npc_director.unity_adapter.console import ConsoleEngineAdapter
from scripts.replay_turn import replay_deterministic
from scripts.trace_to_regression import build_regression_case


def service(database: Path) -> NPCDirectorService:
    settings = Settings(database_path=database)
    turns = TurnStore(database)
    return NPCDirectorService(
        settings,
        executor=DeterministicDirectorExecutor(),
        context_builder=DefaultContextBuilder(),
        turn_store=turns,
        domain_store=DomainStateStore(database),
        event_log=EventLog(database),
        approval_store=ApprovalStore(database, turn_store=turns),
        outbox_store=OutboxStore(database),
    )


@pytest.mark.asyncio
async def test_deterministic_replay_and_regression_conversion(tmp_path: Path) -> None:
    database = tmp_path / "state.db"
    app = service(database)
    request = TurnRequest.model_validate(
        {
            "session_id": "s1",
            "turn_id": "s1:replay",
            "npc_id": "elder_maren",
            "player_input": "你好",
            "scene": {"location": "gate"},
            "character_core": "沉稳的长老",
        }
    )
    result = await app.run_turn(request, adapter=ConsoleEngineAdapter(writer=lambda _: None))
    await app.process_engine_event(
        EngineEvent(
            session_id="s1",
            turn_id=request.turn_id,
            idempotency_key=result.idempotency_key or "",
            event_type=EngineEventType.COMPLETED,
        )
    )

    report = await replay_deterministic(Settings(database_path=database), request.turn_id)
    regression = build_regression_case(database, request.turn_id)

    assert report.directive_equal is True
    assert "performance.plan" in report.event_types
    assert regression["id"] == request.turn_id
    assert regression["expect"]["intent"] == "greeting"
    assert regression["expect"]["required_handoff"] is None
