from __future__ import annotations

import asyncio
import hashlib
from collections.abc import Collection
from datetime import UTC, datetime, timedelta
from functools import partial
from pathlib import Path
from weakref import WeakValueDictionary

from npc_director.agents.director import DIRECTOR_PROMPT_VERSION
from npc_director.agents.handoffs import QUEST_NEGOTIATOR_PROMPT_VERSION
from npc_director.agents.specialists import (
    LORE_PROMPT_VERSION,
    NARRATIVE_PROMPT_VERSION,
    PERFORMANCE_PROMPT_VERSION,
    SCREENWRITER_PROMPT_VERSION,
)
from npc_director.config import Settings
from npc_director.context import MemoryDistillationRequest, MemoryDistillationService
from npc_director.contracts import (
    ApprovalRecord,
    CheckResult,
    CheckSeverity,
    CheckStatus,
    DecisionAction,
    EngineEvent,
    EngineEventType,
    FinalizationDecision,
    Intent,
    PerformanceDirective,
    SpecialistName,
    TurnExecutionResult,
    TurnProposal,
    TurnRequest,
    TurnStateRecord,
    TurnStatus,
)
from npc_director.governance import (
    INPUT_GUARD_VERSION,
    Finalizer,
    build_safe_input_proposal,
    check_input,
    finalize_proposal,
    run_checks,
)
from npc_director.model_profile import get_active_profile
from npc_director.orchestration.context_adapter import DefaultContextBuilder
from npc_director.orchestration.executor import DirectorExecutor, ResilientDirectorExecutor
from npc_director.rag import CachedLoreRetriever, LexicalLoreIndex, LexicalLoreRetriever
from npc_director.state import (
    ApprovalStore,
    DomainStateStore,
    EventLog,
    LongTermMemoryStore,
    OptimisticLockError,
    OutboxStore,
    RecordNotFoundError,
    TurnStore,
)
from npc_director.unity_adapter.base import EngineAdapter, build_idempotency_key

ALL_SPECIALIST_TOOLS = (
    "narrative_planner",
    "lore_specialist",
    "screenwriter",
    "performance_specialist",
)

PROMPT_VERSION_BY_SPECIALIST = {
    SpecialistName.NARRATIVE_PLANNER: NARRATIVE_PROMPT_VERSION,
    SpecialistName.LORE: LORE_PROMPT_VERSION,
    SpecialistName.SCREENWRITER: SCREENWRITER_PROMPT_VERSION,
    SpecialistName.PERFORMANCE: PERFORMANCE_PROMPT_VERSION,
}


def state_patch_allowlist(intent: Intent) -> tuple[str, ...]:
    return {
        Intent.RECONCILIATION: (
            "relationship.trust_delta",
            "relationship.affinity_delta",
            "flags.reunion_started",
        ),
        Intent.GRATITUDE: ("relationship.affinity_delta",),
        Intent.INSULT: ("relationship.affinity_delta", "relationship.trust_delta"),
        Intent.THREAT: ("relationship.trust_delta", "relationship.affinity_delta"),
        Intent.QUEST_ACCEPTANCE: ("quests.*.status",),
        Intent.CRITICAL_CHOICE: ("flags.*", "quests.*.status"),
    }.get(intent, ())


class NPCDirectorService:
    def __init__(
        self,
        settings: Settings,
        *,
        executor: DirectorExecutor,
        context_builder: DefaultContextBuilder,
        turn_store: TurnStore,
        domain_store: DomainStateStore,
        event_log: EventLog,
        approval_store: ApprovalStore,
        outbox_store: OutboxStore,
        memory_store: LongTermMemoryStore | None = None,
        memory_distiller: MemoryDistillationService | None = None,
    ) -> None:
        self.settings = settings
        self.executor = executor
        self.context_builder = context_builder
        self.turn_store = turn_store
        self.domain_store = domain_store
        self.event_log = event_log
        self.approval_store = approval_store
        self.outbox_store = outbox_store
        self.memory_store = memory_store
        self.memory_distiller = memory_distiller or MemoryDistillationService()
        self.model_profile = get_active_profile(settings)
        self.finalizer = Finalizer(low_confidence_threshold=settings.low_confidence_threshold)
        self._turn_locks: WeakValueDictionary[str, asyncio.Lock] = WeakValueDictionary()
        self._turn_locks_guard = asyncio.Lock()

    async def run_turn(
        self,
        request: TurnRequest,
        *,
        adapter: EngineAdapter,
    ) -> TurnExecutionResult:
        turn_lock = await self._turn_lock(request.turn_id)
        async with turn_lock:
            return await self._run_turn(request, adapter=adapter)

    def _prompt_versions(
        self,
        specialists: Collection[SpecialistName],
        handoffs: Collection[str] = (),
    ) -> list[str]:
        return _prompt_versions(
            specialists,
            handoffs,
            version_tag=self.model_profile.prompts.version_tag,
        )

    async def _turn_lock(self, turn_id: str) -> asyncio.Lock:
        async with self._turn_locks_guard:
            turn_lock = self._turn_locks.get(turn_id)
            if turn_lock is None:
                turn_lock = asyncio.Lock()
                self._turn_locks[turn_id] = turn_lock
            return turn_lock

    async def _run_turn(
        self,
        request: TurnRequest,
        *,
        adapter: EngineAdapter,
    ) -> TurnExecutionResult:
        turn = await self.turn_store.astart_turn(request)
        if turn.status is TurnStatus.READY_TO_EMIT:
            return await self._deliver(turn, adapter, metrics=turn.metrics)
        if turn.status in {
            TurnStatus.PENDING_APPROVAL,
            TurnStatus.EMITTED,
            TurnStatus.COMPLETED,
            TurnStatus.INTERRUPTED,
            TurnStatus.FAILED,
        }:
            return self._execution_result(turn)

        guard = check_input(request)
        if guard.status is CheckStatus.FAIL:
            return await self._emit_safe_input_response(turn, guard, adapter)

        domain_state = await self.domain_store.aget_or_create(request.npc_id)
        built_context = await self.context_builder.build(request, domain_state)
        trusted_request = request.model_copy(
            update={"character_core": built_context.director_input.character_core}
        )
        turn = await self.turn_store.asave(
            turn.model_copy(update={"domain_version": domain_state.version})
        )
        await self._record(
            turn,
            "turn.request",
            request.model_dump(mode="json"),
            suffix="request",
        )
        await self._record(
            turn,
            "context.snapshot",
            built_context.snapshot,
            suffix="context",
        )

        repair_feedback: str | None = None
        recovered_proposal = turn.proposal is not None
        while True:
            if recovered_proposal and turn.proposal is not None:
                proposal = turn.proposal
                specialists = turn.specialists_called
                requested_tools = [_tool_name(item) for item in specialists]
                metrics = turn.metrics
                trace_id = turn.trace_id
                response_id = turn.response_id
                handoffs = turn.handoffs
                prompt_versions = turn.prompt_versions or self._prompt_versions(
                    specialists, handoffs
                )
                available_lore_refs = turn.available_lore_refs
                delegations = []
                recovered_proposal = False
            else:
                director_result = await self.executor.generate(
                    built_context.director_input,
                    repair_feedback=repair_feedback,
                )
                proposal = self.model_profile.normalizer.normalize(director_result.proposal)
                specialists = _actual_specialists(director_result.delegations)
                requested_tools = [event.tool_name for event in director_result.delegations]
                metrics = director_result.metrics
                trace_id = director_result.trace_id
                response_id = director_result.response_id
                handoffs = director_result.handoffs
                prompt_versions = self._prompt_versions(specialists, handoffs)
                available_lore_refs = sorted(director_result.lore_refs_accessed)
                delegations = director_result.delegations
            checks = await run_checks(
                proposal,
                trusted_request,
                state_patch_allowlist=state_patch_allowlist(proposal.plan.intent),
                available_lore_refs=available_lore_refs,
                requested_tools=requested_tools,
                tool_allowlist=ALL_SPECIALIST_TOOLS,
                persona_forbidden_phrases=("作为AI", "system prompt", "开发者消息"),
                safety_forbidden_phrases=("杀了你", "现实世界地址"),
                include_input_guard=False,
                extra_checks=(_critical_story_check(proposal),),
            )
            decision = self.finalizer.decide(
                proposal,
                checks,
                trusted_request,
                specialists_called=specialists,
                prompt_versions=prompt_versions,
                model=metrics.model if metrics else None,
                trace_id=trace_id,
                response_id=response_id,
            )
            turn = await self.turn_store.asave(
                turn.model_copy(
                    update={
                        "proposal": proposal,
                        "checks": checks,
                        "repair_attempts": turn.repair_attempts,
                        "metrics": metrics,
                        "specialists_called": specialists,
                        "handoffs": handoffs,
                        "prompt_versions": prompt_versions,
                        "trace_id": trace_id,
                        "response_id": response_id,
                        "available_lore_refs": available_lore_refs,
                    }
                )
            )
            await self._record(
                turn,
                "director.proposal",
                {
                    "proposal": proposal.model_dump(mode="json"),
                    "delegations": [event.model_dump(mode="json") for event in delegations],
                    "handoffs": handoffs,
                    "metrics": metrics.model_dump(mode="json") if metrics else None,
                    "available_lore_refs": available_lore_refs,
                },
                suffix=f"proposal:{turn.repair_attempts}",
            )
            await self._record(
                turn,
                "governance.checks",
                {"checks": [check.model_dump(mode="json") for check in checks]},
                suffix=f"checks:{turn.repair_attempts}",
            )

            if decision.action is not DecisionAction.REPAIR:
                break
            if turn.repair_attempts >= self.settings.max_repair_attempts:
                decision = FinalizationDecision(
                    action=DecisionAction.REQUIRE_APPROVAL,
                    reasons=["repair budget exhausted", *decision.reasons],
                    directive=finalize_proposal(
                        request,
                        proposal,
                        specialists_called=specialists,
                        prompt_versions=prompt_versions,
                        model=metrics.model if metrics else None,
                        trace_id=trace_id,
                        response_id=response_id,
                    ),
                )
                break
            turn = await self.turn_store.asave(
                turn.model_copy(update={"repair_attempts": turn.repair_attempts + 1})
            )
            repair_feedback = decision.repair_feedback

        if decision.action is DecisionAction.REJECT:
            turn = await self.turn_store.aupdate_status(turn.turn_id, TurnStatus.FAILED)
            return self._execution_result(turn, metrics=metrics)

        if decision.action is DecisionAction.REQUIRE_APPROVAL:
            approval = await self.approval_store.apause(turn, decision)
            turn = await self.turn_store.aget(turn.turn_id) or turn
            await self._record(
                turn,
                "approval.pending",
                approval.model_dump(mode="json"),
                suffix="approval",
            )
            return self._execution_result(turn, metrics=metrics)

        if decision.directive is None:
            raise RuntimeError("emit decision is missing a directive")
        turn = await self._stage_directive(turn, decision.directive)
        return await self._deliver(turn, adapter, metrics=metrics)

    async def process_engine_event(self, event: EngineEvent) -> TurnExecutionResult | None:
        turn_lock = await self._turn_lock(event.turn_id)
        async with turn_lock:
            return await self._process_engine_event(event)

    async def _process_engine_event(self, event: EngineEvent) -> TurnExecutionResult | None:
        turn = await self.turn_store.aget(event.turn_id)
        if turn is None:
            raise RecordNotFoundError(f"Turn {event.turn_id!r} does not exist")
        if turn.idempotency_key != event.idempotency_key:
            raise ValueError("engine event idempotency key does not match turn")
        await self.event_log.aappend(event)
        outbox_message = await asyncio.to_thread(
            self.outbox_store.get_by_idempotency_key,
            event.idempotency_key,
        )
        if outbox_message is not None and outbox_message.status != "sent":
            await self.outbox_store.amark_sent(outbox_message.message_id)

        if turn.status in {
            TurnStatus.COMPLETED,
            TurnStatus.INTERRUPTED,
            TurnStatus.FAILED,
        }:
            return self._execution_result(turn)

        if event.event_type in {EngineEventType.ACK, EngineEventType.STARTED}:
            turn = await self.turn_store.aupdate_status(event.turn_id, TurnStatus.EMITTED)
        elif event.event_type is EngineEventType.COMPLETED:
            if turn.proposal is None or turn.domain_version is None:
                raise RuntimeError("completed turn is missing proposal or domain version")
            try:
                await self.domain_store.acommit_completed(
                    turn.turn_id,
                    turn.npc_id,
                    turn.proposal.plan.proposed_state_changes,
                    expected_version=turn.domain_version,
                    allowed_paths=state_patch_allowlist(turn.proposal.plan.intent),
                )
            except OptimisticLockError:
                turn = await self.turn_store.aupdate_status(turn.turn_id, TurnStatus.FAILED)
                raise
            await self._distill_long_term_memory(turn)
            turn = await self.turn_store.aupdate_status(event.turn_id, TurnStatus.COMPLETED)
        elif event.event_type is EngineEventType.INTERRUPTED:
            turn = await self.turn_store.aupdate_status(event.turn_id, TurnStatus.INTERRUPTED)
        elif event.event_type is EngineEventType.ERROR:
            turn = await self.turn_store.aupdate_status(event.turn_id, TurnStatus.FAILED)
        return self._execution_result(turn)

    async def get_approval(self, approval_id: str) -> ApprovalRecord | None:
        return await self.approval_store.aget(approval_id)

    async def recover_incomplete_events(self) -> int:
        recovered = 0
        after_sequence = 0
        while True:
            entries = await asyncio.to_thread(
                self.event_log.all,
                after_sequence=after_sequence,
                limit=500,
            )
            if not entries:
                break
            for entry in entries:
                after_sequence = entry.sequence
                if entry.event_type != EngineEventType.COMPLETED.value:
                    continue
                turn = await self.turn_store.aget(entry.turn_id)
                if turn is None or turn.status in {
                    TurnStatus.COMPLETED,
                    TurnStatus.INTERRUPTED,
                    TurnStatus.FAILED,
                }:
                    continue
                event = EngineEvent.model_validate(entry.payload)
                await self.process_engine_event(event)
                recovered += 1
        return recovered

    async def resolve_approval(
        self,
        approval_id: str,
        *,
        action: str,
        reviewer: str,
        comment: str | None,
        edited_directive: PerformanceDirective | None,
        adapter: EngineAdapter,
    ) -> TurnExecutionResult:
        current = await self.approval_store.aget(approval_id)
        if current is None:
            raise KeyError(approval_id)
        if action == "approve":
            resolved = await self.approval_store.aapprove(
                approval_id,
                reviewer=reviewer,
                comment=comment,
            )
        elif action == "reject":
            resolved = await self.approval_store.areject(
                approval_id,
                reviewer=reviewer,
                comment=comment,
            )
        elif action == "edit":
            if edited_directive is None:
                raise ValueError("edit action requires edited_directive")
            _validate_edited_directive(current.proposed_directive, edited_directive)
            resolved = await self.approval_store.aedit(
                approval_id,
                edited_directive,
                reviewer=reviewer,
                comment=comment,
            )
        else:
            raise ValueError(f"unsupported approval action: {action}")

        turn = await self.turn_store.aget(resolved.turn_id)
        if turn is None:
            raise RuntimeError("approval references a missing turn")
        await self._record(
            turn,
            f"approval.{resolved.status.value}",
            resolved.model_dump(mode="json"),
            suffix=f"approval:{resolved.status.value}",
        )
        if resolved.resolved_directive is None:
            turn = await self.turn_store.aupdate_status(turn.turn_id, TurnStatus.FAILED)
            return self._execution_result(turn)
        turn = await self._stage_directive(turn, resolved.resolved_directive)
        return await self._deliver(turn, adapter)

    async def dispatch_outbox(
        self,
        adapter: EngineAdapter,
        *,
        limit: int = 100,
        session_id: str | None = None,
    ) -> int:
        delivered = 0
        for message in await self.outbox_store.adue(limit=limit):
            try:
                directive = PerformanceDirective.model_validate(message.payload)
                if session_id is not None and directive.session_id != session_id:
                    continue
                receipt = await adapter.emit(directive)
                if receipt.status in {"sent", "duplicate"}:
                    delivered += 1
                else:
                    await self.outbox_store.amark_failed(
                        message.message_id,
                        receipt.detail or "adapter queued message",
                        retry_at=_next_retry_at(message.attempts),
                        max_attempts=self.settings.outbox_retry_limit,
                    )
            except Exception as exc:
                await self.outbox_store.amark_failed(
                    message.message_id,
                    str(exc),
                    retry_at=_next_retry_at(message.attempts),
                    max_attempts=self.settings.outbox_retry_limit,
                )
        return delivered

    async def _emit_safe_input_response(
        self,
        turn: TurnStateRecord,
        guard: CheckResult,
        adapter: EngineAdapter,
    ) -> TurnExecutionResult:
        proposal = build_safe_input_proposal(turn.request)
        domain_state = await self.domain_store.aget_or_create(turn.npc_id)
        directive = finalize_proposal(
            turn.request,
            proposal,
            specialists_called=[],
            prompt_versions=[INPUT_GUARD_VERSION],
            model=None,
            trace_id=f"input-guard:{turn.turn_id}",
        )
        turn = await self.turn_store.asave(
            turn.model_copy(
                update={
                    "proposal": proposal,
                    "checks": [guard],
                    "domain_version": domain_state.version,
                }
            )
        )
        await self._record(
            turn,
            "turn.request",
            turn.request.model_dump(mode="json"),
            suffix="request",
        )
        await self._record(
            turn,
            "input_guard.blocked",
            {
                "check": guard.model_dump(mode="json"),
                "proposal": proposal.model_dump(mode="json"),
            },
            suffix="input-guard",
        )
        turn = await self._stage_directive(turn, directive)
        return await self._deliver(turn, adapter)

    async def _distill_long_term_memory(self, turn: TurnStateRecord) -> None:
        if self.memory_store is None or turn.directive is None:
            return
        existing = await self.memory_store.alist_for_npc(turn.npc_id)
        memory_kinds: list[str] = []
        if turn.proposal is not None:
            intent = turn.proposal.plan.intent
            if intent in {
                Intent.QUEST_ACCEPTANCE,
                Intent.CRITICAL_CHOICE,
                Intent.REFUSAL,
                Intent.NEGOTIATION,
            }:
                memory_kinds.append("player_choice")
            if intent in {Intent.INSULT, Intent.THREAT}:
                memory_kinds.append("conflict")
            relationship = turn.proposal.plan.proposed_state_changes.relationship
            if relationship is not None and (
                relationship.trust_delta or relationship.affinity_delta
            ):
                memory_kinds.append("relationship_change")
        player_record: dict[str, object] = {
            "text": f"玩家：{turn.request.player_input}",
            "turn_id": turn.turn_id,
        }
        if memory_kinds:
            player_record["kinds"] = memory_kinds
        history = [
            *turn.request.recent_history,
            player_record,
            {
                "text": f"NPC回应：{turn.directive.dialogue.text}",
                "turn_id": turn.turn_id,
            },
        ]
        distilled = await self.memory_distiller.distill_async(
            MemoryDistillationRequest(
                session_id=turn.session_id,
                npc_id=turn.npc_id,
                history=history,
                existing_memories=tuple(existing),
            )
        )
        await self.memory_store.aadd_many(distilled.memories)

    async def _stage_directive(
        self,
        turn: TurnStateRecord,
        directive: PerformanceDirective,
    ) -> TurnStateRecord:
        idempotency_key = build_idempotency_key(directive)
        await self.outbox_store.aenqueue(idempotency_key, directive)
        updated = turn.model_copy(
            update={
                "directive": directive,
                "idempotency_key": idempotency_key,
                "status": TurnStatus.READY_TO_EMIT,
            }
        )
        turn = await self.turn_store.asave(updated)
        await self._record(
            turn,
            "performance.plan",
            directive.model_dump(mode="json"),
            suffix="plan",
            idempotency_key=idempotency_key,
        )
        return turn

    async def _deliver(
        self,
        turn: TurnStateRecord,
        adapter: EngineAdapter,
        *,
        metrics=None,
    ) -> TurnExecutionResult:
        if turn.directive is None or turn.idempotency_key is None:
            raise RuntimeError("turn is not ready for delivery")
        await adapter.emit(turn.directive)
        return self._execution_result(turn, metrics=metrics)

    async def _record(
        self,
        turn: TurnStateRecord,
        event_type: str,
        payload: dict,
        *,
        suffix: str,
        idempotency_key: str | None = None,
    ) -> None:
        key = hashlib.sha256(f"{turn.turn_id}:{suffix}".encode()).hexdigest()
        operation = partial(
            self.event_log.append_data,
            session_id=turn.session_id,
            turn_id=turn.turn_id,
            idempotency_key=idempotency_key or f"internal:{turn.turn_id}",
            event_type=event_type,
            payload=payload,
            event_key=key,
        )
        await asyncio.to_thread(operation)

    @staticmethod
    def _execution_result(turn: TurnStateRecord, *, metrics=None) -> TurnExecutionResult:
        return TurnExecutionResult(
            turn_id=turn.turn_id,
            status=turn.status,
            plan=turn.proposal.plan if turn.proposal else None,
            directive=turn.directive,
            metrics=metrics or turn.metrics,
            checks=turn.checks,
            approval_id=turn.approval_id,
            idempotency_key=turn.idempotency_key,
        )


def build_default_service(settings: Settings | None = None) -> NPCDirectorService:
    resolved = settings or Settings.from_env()
    database = Path(resolved.database_path)
    turn_store = TurnStore(database)
    lore_index = LexicalLoreIndex.from_directory(resolved.lore_path)
    lore_retriever = CachedLoreRetriever(LexicalLoreRetriever(lore_index))
    memory_store = LongTermMemoryStore(database)
    return NPCDirectorService(
        resolved,
        executor=ResilientDirectorExecutor(resolved, lore_retriever=lore_retriever),
        context_builder=DefaultContextBuilder(
            lore_retriever=lore_retriever,
            memory_reader=memory_store,
            character_root=resolved.character_path,
            lore_top_k=resolved.lore_top_k,
            lore_token_budget=resolved.lore_token_budget,
            history_limit=resolved.context_history_limit,
        ),
        turn_store=turn_store,
        domain_store=DomainStateStore(database),
        event_log=EventLog(database),
        approval_store=ApprovalStore(database, turn_store=turn_store),
        outbox_store=OutboxStore(database),
        memory_store=memory_store,
    )


def _actual_specialists(delegations) -> list[SpecialistName]:
    result: list[SpecialistName] = []
    for event in delegations:
        if event.specialist not in result:
            result.append(event.specialist)
    return result


def _tool_name(specialist: SpecialistName) -> str:
    return {
        SpecialistName.NARRATIVE_PLANNER: "narrative_planner",
        SpecialistName.LORE: "lore_specialist",
        SpecialistName.SCREENWRITER: "screenwriter",
        SpecialistName.PERFORMANCE: "performance_specialist",
        SpecialistName.BASELINE: "baseline",
    }[specialist]


def _prompt_versions(
    specialists: Collection[SpecialistName],
    handoffs: Collection[str] = (),
    *,
    version_tag: str | None = None,
) -> list[str]:
    versions = [DIRECTOR_PROMPT_VERSION]
    versions.extend(
        PROMPT_VERSION_BY_SPECIALIST[specialist]
        for specialist in specialists
        if specialist in PROMPT_VERSION_BY_SPECIALIST
    )
    if "Quest Negotiator" in handoffs:
        versions.append(QUEST_NEGOTIATOR_PROMPT_VERSION)
    if version_tag:
        versions = [f"{version}+{version_tag}" for version in versions]
    return versions


def _critical_story_check(proposal: TurnProposal):
    def check() -> CheckResult:
        if proposal.plan.intent is Intent.CRITICAL_CHOICE:
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


def _validate_edited_directive(
    original: PerformanceDirective,
    edited: PerformanceDirective,
) -> None:
    immutable_fields = (
        "session_id",
        "turn_id",
        "npc_id",
        "schema_version",
        "runtime_meta",
    )
    for field_name in immutable_fields:
        if getattr(original, field_name) != getattr(edited, field_name):
            raise ValueError(f"edited directive cannot change {field_name}")


def _next_retry_at(attempts: int) -> datetime:
    delay_seconds = min(60, 2 ** min(attempts, 6))
    return datetime.now(UTC) + timedelta(seconds=delay_seconds)
