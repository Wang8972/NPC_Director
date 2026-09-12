"""Durable maintenance, separate from foreground completion handling."""

from __future__ import annotations

import asyncio
import time
from contextlib import suppress
from uuid import uuid4

from agents import Runner

from npc_director.agents.memory_consolidator import build_memory_consolidator, encode_memory_input
from npc_director.contracts.cognition import MemoryConsolidation
from npc_director.model_provider import build_run_config
from npc_director.orchestration.bounded_executor import TypedModelCall


class MemoryWorker:
    def __init__(self, service):
        self.service = service
        self.owner = "memory-" + uuid4().hex
        self.task = None
        self.lock = asyncio.Lock()

    async def start(self):
        if self.task is None or self.task.done():
            self.task = asyncio.create_task(self._loop())

    async def stop(self):
        if self.task is not None:
            self.task.cancel()
            with suppress(asyncio.CancelledError):
                await self.task
            self.task = None

    async def _loop(self):
        while True:
            await self.drain(limit=4)
            await asyncio.sleep(0.25)

    async def _settle(self, job, **usage):
        from npc_director.state.errors import IdempotencyConflictError

        store = self.service.episodes.store
        with store.connection() as conn:
            row = conn.execute(
                "SELECT usage_json FROM episode_reservations WHERE episode_id=? AND operation_id=?",
                (job["episode_id"], job["reservation_id"]),
            ).fetchone()
        if row and row[0] is not None:
            return
        try:
            await store.record_model_usage(job["episode_id"], job["reservation_id"], **usage)
        except IdempotencyConflictError:
            # A lease recovery may conservatively settle the same in-flight call.
            # Keep that first durable charge; never revise it with a late response.
            with store.connection() as conn:
                row = conn.execute(
                    "SELECT usage_json FROM episode_reservations "
                    "WHERE episode_id=? AND operation_id=?",
                    (job["episode_id"], job["reservation_id"]),
                ).fetchone()
            if not row or row[0] is None:
                raise

    async def drain(self, session_id=None, *, limit=16):
        async with self.lock:
            count = 0
            store = self.service.cognition_store
            # A crashed call has unknown billing. Settle its reservation before
            # retaining the failure; never silently reissue an unaccounted call.
            with store.connection() as conn:
                expired = [
                    dict(r)
                    for r in conn.execute(
                        "SELECT * FROM cognition_jobs WHERE status='running' AND lease_until<?",
                        (time.time(),),
                    )
                ]
            for job in expired:
                await self._settle(job, usage_known=False)
                with store.transaction() as conn:
                    conn.execute(
                        "UPDATE cognition_jobs SET status='failed',last_error='lease_expired' "
                        "WHERE job_id=? AND status='running' AND lease_until<?",
                        (job["job_id"], time.time()),
                    )
                store.retry_failed(job["job_id"])
                store.refresh_obsolete(job["session_id"], job["npc_id"])
            for _ in range(limit):
                job = await asyncio.to_thread(
                    store.claim,
                    self.owner,
                    session_id=session_id,
                    lease_seconds=max(120, self.service.settings.timeout_seconds * 3),
                )
                if job is None:
                    break
                count += 1
                started = time.perf_counter()
                output = None
                error = None
                usage = {"usage_known": False}
                try:
                    agent = build_memory_consolidator(self.service.settings)
                    model_input, aliases = encode_memory_input(job["snapshot_json"])
                    primary = getattr(self.service.executor, "primary", self.service.executor)
                    runner = getattr(primary, "_typed_runner", None)
                    parent = self.service.episodes.store.get_episode(job["episode_id"])
                    remaining = parent.budget.max_active_seconds - parent.active_seconds
                    if remaining <= 0:
                        usage = {"total_tokens": 0, "usage_known": True}
                        raise TimeoutError("episode active compute budget exhausted")
                    semaphore = getattr(primary, "_semaphore", asyncio.Semaphore(1))
                    async with (
                        semaphore,
                        asyncio.timeout(min(self.service.settings.timeout_seconds, remaining)),
                    ):
                        if runner is not None:
                            result = await runner(agent, model_input, MemoryConsolidation)
                        else:
                            response = await Runner.run(
                                agent,
                                model_input,
                                max_turns=1,
                                run_config=build_run_config(self.service.settings),
                            )
                            totals = response.context_wrapper.usage
                            result = TypedModelCall(
                                output=response.final_output_as(MemoryConsolidation),
                                input_tokens=totals.input_tokens,
                                output_tokens=totals.output_tokens,
                                total_tokens=totals.total_tokens,
                            )
                    usage = {
                        "input_tokens": result.input_tokens,
                        "output_tokens": result.output_tokens,
                        "total_tokens": result.total_tokens,
                        "usage_known": True,
                    }
                    output = MemoryConsolidation.model_validate(result.output).model_copy(deep=True)
                    for insight in output.insights:
                        insight.source_memory_ids = [
                            aliases.get(ref, ref) for ref in insight.source_memory_ids
                        ]
                        insight.supersedes = [aliases.get(ref, ref) for ref in insight.supersedes]
                        insight.contradicts = [aliases.get(ref, ref) for ref in insight.contradicts]
                except asyncio.CancelledError:
                    error = "cancelled_unknown_usage"
                    raise
                except Exception as exc:
                    error = type(exc).__name__
                    if error == "EvaluationBudgetExceeded":
                        usage = {"total_tokens": 0, "usage_known": True}
                finally:
                    usage["elapsed_seconds"] = time.perf_counter() - started
                    await self._settle(job, **usage)
                    try:
                        store.finish(job, output, error=error, usage=usage)
                    except ValueError as exc:
                        store.finish(job, None, error=str(exc), usage=usage)
                    with store.connection() as conn:
                        state = conn.execute(
                            "SELECT status FROM cognition_jobs WHERE job_id=?", (job["job_id"],)
                        ).fetchone()[0]
                    if state == "obsolete":
                        store.refresh_obsolete(job["session_id"], job["npc_id"])
                    elif state == "failed" and error not in {
                        "cancelled_unknown_usage",
                        "EvaluationBudgetExceeded",
                    }:
                        store.retry_failed(job["job_id"])
            return count
