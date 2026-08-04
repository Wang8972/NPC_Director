from __future__ import annotations

import argparse
import asyncio
import dataclasses
import json
import os
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from npc_director.config import Settings
from npc_director.contracts import CheckResult, CheckSeverity, CheckStatus, Intent, TurnStateRecord
from npc_director.governance import Finalizer, run_checks
from npc_director.orchestration.context_adapter import DefaultContextBuilder
from npc_director.orchestration.executor import ResilientDirectorExecutor
from npc_director.rag import CachedLoreRetriever, LexicalLoreIndex, LexicalLoreRetriever
from npc_director.state import DomainStateStore, EventLog, LongTermMemoryStore, TurnStore


class ReplayReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    turn_id: str
    mode: str
    event_types: list[str]
    proposal_equal: bool | None = None
    directive_equal: bool | None = None
    check_names: list[str] = Field(default_factory=list)
    differences: list[str] = Field(default_factory=list)


def _critical_check(turn: TurnStateRecord):
    def check() -> CheckResult:
        if turn.proposal and turn.proposal.plan.intent is Intent.CRITICAL_CHOICE:
            return CheckResult(
                name="critical_story",
                status=CheckStatus.WARN,
                severity=CheckSeverity.CRITICAL,
                reason="Critical story choice requires human approval.",
            )
        return CheckResult(
            name="critical_story",
            status=CheckStatus.PASS,
            reason="No critical story transition detected.",
        )

    return check


async def replay_deterministic(settings: Settings, turn_id: str) -> ReplayReport:
    turn = TurnStore(settings.database_path).require(turn_id)
    events = EventLog(settings.database_path).events_for_turn(turn_id)
    if turn.proposal is None:
        return ReplayReport(
            turn_id=turn_id,
            mode="deterministic",
            event_types=[event.event_type for event in events],
            differences=["turn has no stored proposal"],
        )
    available_refs = tuple(turn.available_lore_refs)
    tool_names = [
        {
            "narrative_planner": "narrative_planner",
            "lore": "lore_specialist",
            "screenwriter": "screenwriter",
            "performance": "performance_specialist",
            "baseline": "baseline",
        }[specialist.value]
        for specialist in turn.specialists_called
    ]
    checks = await run_checks(
        turn.proposal,
        turn.request,
        state_patch_allowlist=turn.allowed_state_paths,
        available_lore_refs=available_refs,
        requested_tools=tool_names,
        tool_allowlist=(
            "narrative_planner",
            "lore_specialist",
            "screenwriter",
            "performance_specialist",
            "baseline",
        ),
        include_input_guard=False,
        extra_checks=(_critical_check(turn),),
    )
    decision = Finalizer(low_confidence_threshold=settings.low_confidence_threshold).decide(
        turn.proposal,
        checks,
        turn.request,
        specialists_called=turn.specialists_called,
        prompt_versions=turn.prompt_versions,
        model=turn.metrics.model if turn.metrics else None,
        trace_id=turn.trace_id,
        response_id=turn.response_id,
    )
    replayed = decision.directive
    directive_equal = replayed == turn.directive if replayed is not None else turn.directive is None
    differences = [] if directive_equal else ["replayed directive differs from stored directive"]
    return ReplayReport(
        turn_id=turn_id,
        mode="deterministic",
        event_types=[event.event_type for event in events],
        proposal_equal=True,
        directive_equal=directive_equal,
        check_names=[check.name for check in checks],
        differences=differences,
    )


async def replay_reinfer(settings: Settings, turn_id: str) -> ReplayReport:
    if not os.getenv("OPENAI_API_KEY", "").strip():
        raise RuntimeError("reinfer mode requires OPENAI_API_KEY")
    turn = TurnStore(settings.database_path).require(turn_id)
    domain = DomainStateStore(settings.database_path).get_or_create(turn.npc_id)
    lore_retriever = CachedLoreRetriever(
        LexicalLoreRetriever(LexicalLoreIndex.from_directory(settings.lore_path))
    )
    built = await DefaultContextBuilder(
        lore_retriever=lore_retriever,
        memory_reader=LongTermMemoryStore(settings.database_path),
        character_root=settings.character_path,
        settings=settings,
        lore_top_k=settings.lore_top_k,
        lore_token_budget=settings.lore_token_budget,
        history_limit=settings.context_history_limit,
    ).build(turn.request, domain)
    result = await ResilientDirectorExecutor(
        settings,
        lore_retriever=lore_retriever,
    ).generate(built.director_input)
    proposal_equal = result.proposal == turn.proposal
    return ReplayReport(
        turn_id=turn_id,
        mode="reinfer",
        event_types=[
            event.event_type for event in EventLog(settings.database_path).events_for_turn(turn_id)
        ],
        proposal_equal=proposal_equal,
        differences=[] if proposal_equal else ["new inference differs from stored proposal"],
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Replay a persisted NPC Director turn")
    parser.add_argument("turn_id")
    parser.add_argument("--mode", choices=("deterministic", "reinfer"), default="deterministic")
    parser.add_argument("--database", type=Path)
    args = parser.parse_args()
    settings = Settings.from_env()
    if args.database:
        settings = dataclasses.replace(settings, database_path=args.database)
    report = asyncio.run(
        replay_deterministic(settings, args.turn_id)
        if args.mode == "deterministic"
        else replay_reinfer(settings, args.turn_id)
    )
    print(json.dumps(report.model_dump(mode="json"), ensure_ascii=False, indent=2))
    return 0 if not report.differences else 1


if __name__ == "__main__":
    raise SystemExit(main())
