from __future__ import annotations

import asyncio
import sqlite3
import uuid
from functools import partial
from pathlib import Path

from npc_director.contracts import (
    ApprovalRecord,
    ApprovalStatus,
    DecisionAction,
    FinalizationDecision,
    PerformanceDirective,
    TurnStateRecord,
    TurnStatus,
)
from npc_director.contracts.workflow import utc_now
from npc_director.state._sqlite import SQLiteStore, datetime_text
from npc_director.state.errors import (
    ApprovalAlreadyResolvedError,
    IdempotencyConflictError,
    RecordNotFoundError,
)
from npc_director.state.turn_store import TurnStore


class ApprovalStore(SQLiteStore):
    """Persistent human-review queue with restart-safe terminal decisions."""

    def __init__(
        self,
        database: str | Path,
        *,
        turn_store: TurnStore | None = None,
    ) -> None:
        super().__init__(database)
        self.turn_store = turn_store

    def create(self, record: ApprovalRecord) -> ApprovalRecord:
        try:
            with self.transaction() as connection:
                connection.execute(
                    """
                    INSERT INTO approvals
                        (approval_id, turn_id, status, record_json, created_at, resolved_at)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        record.approval_id,
                        record.turn_id,
                        record.status.value,
                        record.model_dump_json(),
                        datetime_text(record.created_at),
                        None,
                    ),
                )
        except sqlite3.IntegrityError as error:
            existing = self.get(record.approval_id)
            if existing == record:
                return existing
            raise IdempotencyConflictError(
                f"Approval {record.approval_id!r} already exists with different data"
            ) from error
        return record

    def pause(
        self,
        turn: TurnStateRecord,
        decision: FinalizationDecision,
        *,
        approval_id: str | None = None,
    ) -> ApprovalRecord:
        if decision.action is not DecisionAction.REQUIRE_APPROVAL:
            raise ValueError("Only require_approval decisions can be paused")
        if decision.directive is None:
            raise ValueError("Approval decisions must include a proposed directive")

        pending = self.pending(turn_id=turn.turn_id)
        if pending:
            existing = pending[0]
            if existing.proposed_directive != decision.directive:
                raise IdempotencyConflictError(
                    f"Turn {turn.turn_id!r} already has a different pending approval"
                )
            if self.turn_store is not None:
                self.turn_store.update_status(
                    turn.turn_id,
                    TurnStatus.PENDING_APPROVAL,
                    approval_id=existing.approval_id,
                )
            return existing

        record = ApprovalRecord(
            approval_id=approval_id or f"approval-{uuid.uuid4().hex}",
            turn_id=turn.turn_id,
            reasons=decision.reasons,
            proposed_directive=decision.directive,
        )
        created = self.create(record)
        if self.turn_store is not None:
            self.turn_store.update_status(
                turn.turn_id,
                TurnStatus.PENDING_APPROVAL,
                approval_id=created.approval_id,
            )
        return created

    def get(self, approval_id: str) -> ApprovalRecord | None:
        with self.connection() as connection:
            row = connection.execute(
                "SELECT record_json FROM approvals WHERE approval_id = ?",
                (approval_id,),
            ).fetchone()
        if row is None:
            return None
        return ApprovalRecord.model_validate_json(row["record_json"])

    def require(self, approval_id: str) -> ApprovalRecord:
        record = self.get(approval_id)
        if record is None:
            raise RecordNotFoundError(f"Approval {approval_id!r} does not exist")
        return record

    def pending(
        self,
        *,
        turn_id: str | None = None,
        limit: int = 100,
    ) -> list[ApprovalRecord]:
        if limit < 1:
            return []
        parameters: list[str | int] = [ApprovalStatus.PENDING.value]
        where = "status = ?"
        if turn_id is not None:
            where += " AND turn_id = ?"
            parameters.append(turn_id)
        parameters.append(limit)
        with self.connection() as connection:
            rows = connection.execute(
                f"""
                SELECT record_json FROM approvals
                WHERE {where}
                ORDER BY created_at, approval_id
                LIMIT ?
                """,  # noqa: S608 - where is assembled only from fixed SQL fragments.
                parameters,
            ).fetchall()
        return [ApprovalRecord.model_validate_json(row["record_json"]) for row in rows]

    list_pending = pending

    def approve(
        self,
        approval_id: str,
        *,
        reviewer: str,
        comment: str | None = None,
    ) -> ApprovalRecord:
        current = self.require(approval_id)
        return self._resolve(
            approval_id,
            ApprovalStatus.APPROVED,
            resolved_directive=current.proposed_directive,
            reviewer=reviewer,
            comment=comment,
        )

    def reject(
        self,
        approval_id: str,
        *,
        reviewer: str,
        comment: str | None = None,
    ) -> ApprovalRecord:
        return self._resolve(
            approval_id,
            ApprovalStatus.REJECTED,
            resolved_directive=None,
            reviewer=reviewer,
            comment=comment,
        )

    def edit(
        self,
        approval_id: str,
        directive: PerformanceDirective,
        *,
        reviewer: str,
        comment: str | None = None,
    ) -> ApprovalRecord:
        return self._resolve(
            approval_id,
            ApprovalStatus.EDITED,
            resolved_directive=directive,
            reviewer=reviewer,
            comment=comment,
        )

    def _resolve(
        self,
        approval_id: str,
        status: ApprovalStatus,
        *,
        resolved_directive: PerformanceDirective | None,
        reviewer: str,
        comment: str | None,
    ) -> ApprovalRecord:
        resolved_at = utc_now()
        with self.transaction() as connection:
            row = connection.execute(
                "SELECT record_json FROM approvals WHERE approval_id = ?",
                (approval_id,),
            ).fetchone()
            if row is None:
                raise RecordNotFoundError(f"Approval {approval_id!r} does not exist")
            current = ApprovalRecord.model_validate_json(row["record_json"])
            if current.status is not ApprovalStatus.PENDING:
                if (
                    current.status is status
                    and current.resolved_directive == resolved_directive
                    and current.reviewer == reviewer
                    and current.comment == comment
                ):
                    return current
                raise ApprovalAlreadyResolvedError(
                    f"Approval {approval_id!r} is already {current.status.value}"
                )

            payload = current.model_dump()
            payload.update(
                status=status,
                resolved_directive=resolved_directive,
                reviewer=reviewer,
                comment=comment,
                resolved_at=resolved_at,
            )
            updated = ApprovalRecord.model_validate(payload)
            cursor = connection.execute(
                """
                UPDATE approvals
                SET status = ?, record_json = ?, resolved_at = ?
                WHERE approval_id = ? AND status = ?
                """,
                (
                    status.value,
                    updated.model_dump_json(),
                    datetime_text(resolved_at),
                    approval_id,
                    ApprovalStatus.PENDING.value,
                ),
            )
            if cursor.rowcount != 1:
                raise ApprovalAlreadyResolvedError(
                    f"Approval {approval_id!r} was resolved concurrently"
                )
        return updated

    async def aget(self, approval_id: str) -> ApprovalRecord | None:
        return await asyncio.to_thread(self.get, approval_id)

    async def apause(
        self,
        turn: TurnStateRecord,
        decision: FinalizationDecision,
        *,
        approval_id: str | None = None,
    ) -> ApprovalRecord:
        operation = partial(self.pause, turn, decision, approval_id=approval_id)
        return await asyncio.to_thread(operation)

    async def aapprove(
        self,
        approval_id: str,
        *,
        reviewer: str,
        comment: str | None = None,
    ) -> ApprovalRecord:
        operation = partial(
            self.approve,
            approval_id,
            reviewer=reviewer,
            comment=comment,
        )
        return await asyncio.to_thread(operation)

    async def areject(
        self,
        approval_id: str,
        *,
        reviewer: str,
        comment: str | None = None,
    ) -> ApprovalRecord:
        operation = partial(
            self.reject,
            approval_id,
            reviewer=reviewer,
            comment=comment,
        )
        return await asyncio.to_thread(operation)

    async def aedit(
        self,
        approval_id: str,
        directive: PerformanceDirective,
        *,
        reviewer: str,
        comment: str | None = None,
    ) -> ApprovalRecord:
        operation = partial(
            self.edit,
            approval_id,
            directive,
            reviewer=reviewer,
            comment=comment,
        )
        return await asyncio.to_thread(operation)
