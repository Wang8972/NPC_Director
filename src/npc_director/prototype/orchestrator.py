from __future__ import annotations

from dataclasses import dataclass, field

from npc_director.prototype.models import (
    ActionCommitResult,
    ActionPlan,
    ApprovedAction,
    InternalReplyPlan,
    RejectedAction,
    SceneActionCandidate,
    SubmissionResult,
)
from npc_director.prototype.repository import PrototypeStateRepository
from npc_director.prototype.rules import PrototypePuzzleRules


@dataclass(slots=True)
class RecordingPrototypeAdapter:
    action_plans: list[ActionPlan] = field(default_factory=list)
    internal_reply_plans: list[InternalReplyPlan] = field(default_factory=list)

    def emit_action(self, plan: ActionPlan) -> None:
        self.action_plans.append(plan)

    def emit_internal_reply(self, plan: InternalReplyPlan) -> None:
        self.internal_reply_plans.append(plan)

    @property
    def total_plan_count(self) -> int:
        return len(self.action_plans) + len(self.internal_reply_plans)


class PrototypeConversationOrchestrator:
    """Minimal scene-action lifecycle plus a persisted, maximum-two-beat chain."""

    def __init__(
        self,
        repository: PrototypeStateRepository,
        *,
        rules: PrototypePuzzleRules | None = None,
        adapter: RecordingPrototypeAdapter | None = None,
    ) -> None:
        self.repository = repository
        self.rules = rules or PrototypePuzzleRules()
        self.adapter = adapter or RecordingPrototypeAdapter()
        self.input_locked: dict[str, bool] = {}
        self.timeline: list[str] = []

    def submit(
        self,
        candidate: SceneActionCandidate,
        *,
        hop_index: int = 0,
    ) -> SubmissionResult:
        world = self.repository.get_world(candidate.session_id)
        npc_states = self.repository.get_npcs(candidate.session_id)
        decision = self.rules.validate(candidate, world, npc_states, hop_index=hop_index)
        if isinstance(decision, RejectedAction):
            self.timeline.append(f"reject:{candidate.action_id}:{decision.reason_code}")
            return SubmissionResult(approved=False, rejection=decision)

        record = self.repository.prepare_action(decision)
        if not decision.adapter_required:
            commit = self.repository.commit_completed(
                candidate.action_id,
                record.idempotency_key,
            )
            self._record_commit_and_reveals(commit)
            return SubmissionResult(
                approved=True,
                commit=commit,
                idempotency_key=record.idempotency_key,
            )

        self.input_locked[candidate.session_id] = True
        plan = ActionPlan(
            action_id=candidate.action_id,
            session_id=candidate.session_id,
            turn_id=candidate.turn_id,
            actor_id=candidate.actor_id,
            action_type=candidate.action_type,
            idempotency_key=record.idempotency_key,
            pre_commit_text=decision.pre_commit_text,
        )
        self.adapter.emit_action(plan)
        self.timeline.append(f"action_plan:{candidate.action_id}:{candidate.actor_id}")
        return SubmissionResult(
            approved=True,
            idempotency_key=record.idempotency_key,
        )

    def handle_action_event(
        self,
        action_id: str,
        idempotency_key: str,
        event_type: str,
        *,
        fail_after_world_write: bool = False,
    ) -> ActionCommitResult | None:
        if event_type in {"ack", "started"}:
            self.repository.mark_lifecycle(action_id, event_type)
            self.timeline.append(f"{event_type}:{action_id}")
            return None
        if event_type in {"interrupted", "error"}:
            pending = self.repository.get_pending(action_id)
            cancelled = self.repository.cancel_action(action_id, status=event_type)
            if cancelled and pending is not None:
                self.input_locked[pending.approved.candidate.session_id] = False
            self.timeline.append(f"{event_type}:{action_id}")
            return None
        if event_type != "completed":
            raise ValueError(f"Unsupported action event {event_type!r}")

        result = self.repository.commit_completed(
            action_id,
            idempotency_key,
            fail_after_world_write=fail_after_world_write,
        )
        if result.applied:
            self._record_commit_and_reveals(result)
        chain_job = self.repository.dispatch_chain_job_once(action_id)
        if chain_job is None:
            if not self._chain_is_dispatched(action_id):
                self.input_locked[result.world.session_id] = False
            return result

        session_id, target_npc_id = chain_job
        plan = InternalReplyPlan(
            source_action_id=action_id,
            session_id=session_id,
            target_npc_id=target_npc_id,
            text="我已经收到这条信息。",
        )
        self.adapter.emit_internal_reply(plan)
        self.timeline.append(f"internal_plan:{action_id}:{target_npc_id}:hop1")
        self.input_locked[session_id] = True
        return result

    def finish_internal_reply(self, source_action_id: str, event_type: str) -> bool:
        finished = self.repository.finish_chain_job(source_action_id, event_type)
        if not finished:
            return False
        session_id = self._chain_session(source_action_id)
        if session_id is not None:
            self.input_locked[session_id] = False
        self.timeline.append(f"internal_{event_type}:{source_action_id}:hop1")
        return True

    def is_input_locked(self, session_id: str) -> bool:
        return self.input_locked.get(session_id, False)

    def _record_commit_and_reveals(self, result: ActionCommitResult) -> None:
        self.timeline.append(f"commit:{result.action_id}:v{result.world.version}")
        for fact_id in sorted(result.reveal_fact_ids):
            self.timeline.append(f"reveal:{result.action_id}:{fact_id}")

    def _chain_is_dispatched(self, source_action_id: str) -> bool:
        with self.repository.connection() as connection:
            row = connection.execute(
                """
                SELECT status FROM prototype_chain_jobs WHERE source_action_id = ?
                """,
                (source_action_id,),
            ).fetchone()
        return row is not None and row["status"] == "dispatched"

    def _chain_session(self, source_action_id: str) -> str | None:
        with self.repository.connection() as connection:
            row = connection.execute(
                """
                SELECT session_id FROM prototype_chain_jobs WHERE source_action_id = ?
                """,
                (source_action_id,),
            ).fetchone()
        return None if row is None else row["session_id"]


def require_approved(result: SubmissionResult) -> str:
    if not result.approved or result.idempotency_key is None:
        reason = None if result.rejection is None else result.rejection.reason_code
        raise AssertionError(f"Expected approved prototype action, got {reason}")
    return result.idempotency_key


def require_decision_type(
    decision: ApprovedAction | RejectedAction,
    expected: type[ApprovedAction] | type[RejectedAction],
) -> None:
    if not isinstance(decision, expected):
        raise AssertionError(f"Expected {expected.__name__}, got {type(decision).__name__}")
