from __future__ import annotations

import argparse
import asyncio
import json
import shutil
import tempfile
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from npc_director.config import Settings
from npc_director.contracts import (
    PerformanceEventMessage,
    PerformancePlanMessage,
    PrototypeResetRequestMessage,
    SceneActionEventMessage,
    SceneActionPlanMessage,
    SceneObserveRequestMessage,
    TurnRequestMessage,
)
from npc_director.orchestration.bounded_executor import (
    BoundedDirectorExecutor,
    TypedModelCall,
)
from npc_director.orchestration.executor import ResilientDirectorExecutor
from npc_director.prototype.models import (
    FACT_GENERATOR_MISSING_FUSE,
    FACT_MANIFEST_FINN_MOVED_C12,
)
from npc_director.prototype.real_director import (
    PROTOTYPE_ACTION_INSTRUCTIONS,
    PROTOTYPE_REAL_INSTRUCTIONS,
    OrchestratedPrototypeTurnGenerator,
    PrototypeRealDirectorSession,
    ResilientPrototypeActionGenerator,
)
from npc_director.prototype.real_models import (
    PrototypeActionDecision,
    PrototypeActionGenerationResult,
    PrototypeGenerationResult,
    PrototypeRealTurnProposal,
    PrototypeTrustedContext,
)


@dataclass(frozen=True, slots=True)
class CodexStructuredResult:
    output: BaseModel
    telemetry: dict[str, Any]


class CodexCliStructuredClient:
    """Run typed model nodes through the current Codex provider/auth."""

    def __init__(
        self,
        *,
        model: str,
        timeout_seconds: float,
        input_cost_per_million: float | None = None,
        output_cost_per_million: float | None = None,
    ) -> None:
        self.model = model
        self.timeout_seconds = timeout_seconds
        self.input_cost_per_million = input_cost_per_million
        self.output_cost_per_million = output_cost_per_million
        self.telemetry: list[dict[str, Any]] = []
        if shutil.which("codex") is None:
            raise RuntimeError("codex CLI is not available on PATH")

    async def generate(
        self,
        *,
        instructions: str,
        run_input: str,
        output_type: type[BaseModel],
        node_name: str,
    ) -> CodexStructuredResult:
        sections = [
            instructions,
            "这是纯 JSON 结构化生成任务，不要分析代码，不要调用工具。",
            "严格使用 JSON Schema 中的字段名，只输出符合 schema 的 JSON。",
            "以下是必须遵守的完整 JSON Schema：",
            json.dumps(
                output_type.model_json_schema(),
                ensure_ascii=False,
                separators=(",", ":"),
            ),
            "以下是本节点输入：",
            run_input,
        ]
        started = time.perf_counter()
        with tempfile.TemporaryDirectory(prefix="npc-p3-codex-") as temp_dir:
            temp_root = Path(temp_dir)
            schema_path = temp_root / "output.schema.json"
            output_path = temp_root / "output.json"
            schema_path.write_text(
                json.dumps(output_type.model_json_schema(), ensure_ascii=False),
                encoding="utf-8",
            )
            process = await asyncio.create_subprocess_exec(
                "codex",
                "exec",
                "--ephemeral",
                "--json",
                "--sandbox",
                "read-only",
                "--ignore-rules",
                "--skip-git-repo-check",
                "--model",
                self.model,
                "--output-schema",
                str(schema_path),
                "--output-last-message",
                str(output_path),
                "\n".join(sections),
                cwd=temp_root,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
            )
            events: list[dict[str, Any]] = []
            output_lines: list[str] = []
            milestones: dict[str, float] = {}

            async def collect() -> None:
                assert process.stdout is not None
                while line := await process.stdout.readline():
                    value = line.decode(errors="replace").rstrip()
                    output_lines.append(value)
                    try:
                        event = json.loads(value)
                    except json.JSONDecodeError:
                        continue
                    events.append(event)
                    event_type = str(event.get("type") or "")
                    milestones.setdefault(event_type, time.perf_counter())
                    if event_type == "item.completed":
                        item_type = str((event.get("item") or {}).get("type") or "")
                        milestones.setdefault(f"item:{item_type}", time.perf_counter())
                await process.wait()

            try:
                await asyncio.wait_for(collect(), timeout=self.timeout_seconds)
            except TimeoutError:
                process.kill()
                await process.wait()
                raise TimeoutError(f"codex CLI {node_name} call timed out") from None
            output = "\n".join(output_lines)
            if process.returncode != 0:
                tail = "\n".join(output.splitlines()[-12:])
                raise RuntimeError(
                    f"codex CLI {node_name} failed ({process.returncode}): {tail}"
                )
            if not output_path.exists():
                raise RuntimeError(f"codex CLI {node_name} did not write structured output")
            parse_started = time.perf_counter()
            parsed = output_type.model_validate_json(
                _extract_json_object(output_path.read_text(encoding="utf-8"))
            )
            parsed_at = time.perf_counter()
            usage = next(
                (
                    event.get("usage") or {}
                    for event in reversed(events)
                    if event.get("type") == "turn.completed"
                ),
                {},
            )
            input_tokens = int(usage.get("input_tokens") or 0)
            output_tokens = int(usage.get("output_tokens") or 0)
            estimated_cost = None
            if (
                self.input_cost_per_million is not None
                and self.output_cost_per_million is not None
            ):
                estimated_cost = (
                    input_tokens * self.input_cost_per_million
                    + output_tokens * self.output_cost_per_million
                ) / 1_000_000
            telemetry = _build_codex_telemetry(
                started,
                parsed_at,
                parse_started,
                milestones,
                usage,
                estimated_cost,
            )
            telemetry["node"] = node_name
            self.telemetry.append(telemetry)
            return CodexStructuredResult(output=parsed, telemetry=telemetry)


class CodexCliBoundedRunner:
    def __init__(self, client: CodexCliStructuredClient) -> None:
        self.client = client

    async def __call__(
        self,
        agent: object,
        run_input: str,
        output_type: type[BaseModel],
    ) -> TypedModelCall:
        instructions = getattr(agent, "instructions", None)
        if not isinstance(instructions, str):
            raise TypeError("Codex CLI bounded runner requires static string instructions")
        call = await self.client.generate(
            instructions=instructions,
            run_input=run_input,
            output_type=output_type,
            node_name=str(getattr(agent, "name", output_type.__name__)),
        )
        usage = call.telemetry["usage"]
        return TypedModelCall(
            output=call.output,
            input_tokens=int(usage["input_tokens"]),
            output_tokens=int(usage["output_tokens"]),
            total_tokens=int(usage["input_tokens"]) + int(usage["output_tokens"]),
        )


class CodexCliPrototypeActionGenerator:
    def __init__(self, client: CodexCliStructuredClient) -> None:
        self.client = client

    async def generate(
        self,
        context: PrototypeTrustedContext,
        *,
        repair_feedback: str | None = None,
    ) -> PrototypeActionGenerationResult:
        sections = [
            "以下 JSON 是本回合可信上下文：",
            context.model_dump_json(),
        ]
        if repair_feedback:
            sections.extend(
                [
                    "上一版组合候选被治理拒绝，只修正动作决策中的相关问题：",
                    repair_feedback,
                ]
            )
        call = await self.client.generate(
            instructions=PROTOTYPE_ACTION_INSTRUCTIONS,
            run_input="\n".join(sections),
            output_type=PrototypeActionDecision,
            node_name="Prototype Scene Action Planner",
        )
        usage = call.telemetry["usage"]
        return PrototypeActionGenerationResult(
            decision=PrototypeActionDecision.model_validate(call.output),
            metrics={
                "model": self.client.model,
                "latency_ms": call.telemetry["total_ms"],
                "input_tokens": int(usage["input_tokens"]),
                "output_tokens": int(usage["output_tokens"]),
                "total_tokens": int(usage["input_tokens"]) + int(usage["output_tokens"]),
                "estimated_cost_usd": call.telemetry["estimated_cost_usd"],
            },
        )


class CodexCliPrototypeTurnGenerator:
    """Legacy one-call P3 generator retained for reproducing historical reports."""

    def __init__(
        self,
        *,
        model: str,
        timeout_seconds: float,
        input_cost_per_million: float | None = None,
        output_cost_per_million: float | None = None,
    ) -> None:
        self.client = CodexCliStructuredClient(
            model=model,
            timeout_seconds=timeout_seconds,
            input_cost_per_million=input_cost_per_million,
            output_cost_per_million=output_cost_per_million,
        )
        self.model = model
        self.telemetry = self.client.telemetry

    async def generate(
        self,
        context: PrototypeTrustedContext,
        *,
        repair_feedback: str | None = None,
    ) -> PrototypeGenerationResult:
        sections = ["以下 JSON 是本回合可信上下文：", context.model_dump_json()]
        if repair_feedback:
            sections.extend(["上一候选被确定性治理拒绝，只修正以下问题：", repair_feedback])
        call = await self.client.generate(
            instructions=PROTOTYPE_REAL_INSTRUCTIONS,
            run_input="\n".join(sections),
            output_type=PrototypeRealTurnProposal,
            node_name="Legacy Prototype Turn",
        )
        usage = call.telemetry["usage"]
        return PrototypeGenerationResult(
            proposal=PrototypeRealTurnProposal.model_validate(call.output),
            metrics={
                "model": self.model,
                "latency_ms": call.telemetry["total_ms"],
                "input_tokens": int(usage["input_tokens"]),
                "output_tokens": int(usage["output_tokens"]),
                "total_tokens": int(usage["input_tokens"]) + int(usage["output_tokens"]),
                "estimated_cost_usd": call.telemetry["estimated_cost_usd"],
            },
        )


def build_codex_orchestrated_generator(
    settings: Settings,
    *,
    timeout_seconds: float,
    input_cost_per_million: float | None = None,
    output_cost_per_million: float | None = None,
) -> tuple[OrchestratedPrototypeTurnGenerator, CodexCliStructuredClient]:
    client = CodexCliStructuredClient(
        model=settings.model_for("director") or "qwen3.8-flash",
        timeout_seconds=timeout_seconds,
        input_cost_per_million=input_cost_per_million,
        output_cost_per_million=output_cost_per_million,
    )
    bounded = BoundedDirectorExecutor(
        settings,
        typed_runner=CodexCliBoundedRunner(client),
    )
    generator = OrchestratedPrototypeTurnGenerator(
        settings,
        executor=ResilientDirectorExecutor(settings, primary=bounded),
        action_generator=ResilientPrototypeActionGenerator(
            settings,
            primary=CodexCliPrototypeActionGenerator(client),
        ),
    )
    generator.transport = "codex-cli"
    return generator, client


def _build_codex_telemetry(
    started: float,
    parsed_at: float,
    parse_started: float,
    milestones: dict[str, float],
    usage: dict[str, Any],
    estimated_cost_usd: float | None,
) -> dict[str, Any]:
    thread = milestones.get("thread.started", started)
    turn = milestones.get("turn.started", thread)
    reasoning = milestones.get("item:reasoning", turn)
    answer = milestones.get("item:agent_message", reasoning)
    completed = milestones.get("turn.completed", answer)
    return {
        "stages_ms": {
            "cli_startup": max(0.0, (thread - started) * 1_000),
            "hooks_and_turn_setup": max(0.0, (turn - thread) * 1_000),
            "model_reasoning_to_item": max(0.0, (reasoning - turn) * 1_000),
            "model_answer_after_reasoning": max(0.0, (answer - reasoning) * 1_000),
            "turn_finalize": max(0.0, (completed - answer) * 1_000),
            "post_turn_process_exit": max(0.0, (parse_started - completed) * 1_000),
            "json_parse_validate": max(0.0, (parsed_at - parse_started) * 1_000),
        },
        "total_ms": max(0.0, (parsed_at - started) * 1_000),
        "usage": {
            "input_tokens": int(usage.get("input_tokens") or 0),
            "cached_input_tokens": int(usage.get("cached_input_tokens") or 0),
            "cache_write_input_tokens": int(usage.get("cache_write_input_tokens") or 0),
            "output_tokens": int(usage.get("output_tokens") or 0),
            "reasoning_output_tokens": int(usage.get("reasoning_output_tokens") or 0),
        },
        "estimated_cost_usd": estimated_cost_usd,
    }


@dataclass(frozen=True, slots=True)
class ExpectedAction:
    action_type: str
    actor_id: str
    object_id: str | None = None
    target_npc_id: str | None = None


class P3MockUnityRunner:
    """Drive Real Director like Unity while validating every planned action."""

    def __init__(
        self,
        session: PrototypeRealDirectorSession,
        *,
        step_attempts: int,
        retry_delay_seconds: float,
        inter_turn_delay_seconds: float,
    ) -> None:
        self.session = session
        self.step_attempts = step_attempts
        self.retry_delay_seconds = retry_delay_seconds
        self.inter_turn_delay_seconds = inter_turn_delay_seconds
        self.sequence = 0
        self.step_records: list[dict[str, Any]] = []

    async def run(self) -> dict[str, Any]:
        await self._run_cooperation()
        await self._reset("between-routes")
        await self._run_procedure()
        report = self.session.report()
        passed = (
            report["current_objective_state"] == "prototype_success"
            and report["route_success_counts"]["cooperation"] >= 1
            and report["route_success_counts"]["procedure"] >= 1
            and report["illegal_scene_plan_count"] == 0
            and report["production_orchestration"]
        )
        return {
            "status": "pass" if passed else "fail",
            "mode": "real-model-mock-unity",
            "transport": getattr(self.session.generator, "transport", "agents-sdk"),
            "model": self.session.settings.model_for("director"),
            "step_attempts": self.step_attempts,
            "steps": self.step_records,
            "session_report": report,
            "recorded_at": datetime.now(UTC).isoformat(),
        }

    async def run_smoke(self) -> dict[str, Any]:
        """Exercise one state-changing turn through the real bounded chain."""
        await self._observe("gate_console", "smoke:observe_console")
        await self._action(
            "smoke:inspect_generator",
            "mechanic_lia",
            [
                "控制台显示 E-17。请检查 generator 的实际故障并开始检查动作。",
                "请你亲自检查发电机 generator，确认 E-17 对应的故障。",
            ],
            ExpectedAction("inspect_object", "mechanic_lia", object_id="generator"),
        )
        report = self.session.report()
        passed = (
            report["current_objective_state"] == "find_fuse"
            and report["production_orchestration"]
            and report["illegal_scene_plan_count"] == 0
            and any(
                audit.get("executor_chain")
                == ["ResilientDirectorExecutor", "BoundedDirectorExecutor"]
                for audit in report["turn_audit"]
            )
        )
        return {
            "status": "pass" if passed else "fail",
            "mode": "real-model-mock-unity-bounded-smoke",
            "transport": getattr(self.session.generator, "transport", "agents-sdk"),
            "model": self.session.settings.model_for("director"),
            "step_attempts": self.step_attempts,
            "steps": self.step_records,
            "session_report": report,
            "recorded_at": datetime.now(UTC).isoformat(),
        }

    async def _run_cooperation(self) -> None:
        await self._observe("gate_console", "cooperation:observe_console")
        await self._action(
            "cooperation:inspect_generator",
            "mechanic_lia",
            [
                "控制台显示 E-17。请检查 generator 的实际故障并开始检查动作。",
                "请你亲自检查发电机 generator，确认 E-17 对应的故障。",
            ],
            ExpectedAction("inspect_object", "mechanic_lia", object_id="generator"),
        )
        await self._action(
            "cooperation:lia_tell_maren",
            "mechanic_lia",
            [
                "请把你刚确认的发电机故障告诉玛伦，让她知道维修依据。",
                "把缺少保险丝的检查结论转述给 guard_captain_maren。",
            ],
            ExpectedAction(
                "tell_npc",
                "mechanic_lia",
                target_npc_id="guard_captain_maren",
            ),
        )
        await self._direct_fact_transfer(
            "cooperation:tell_finn_diagnosis",
            "porter_finn",
            [
                "莉娅确认发电机缺少备用保险丝。请把这个诊断记录下来。",
                "我把 fact_generator_missing_fuse 这个已发现诊断告诉你。",
            ],
            lambda: FACT_GENERATOR_MISSING_FUSE
            in self.session.repository.get_npc(
                self.session.session_id, "porter_finn"
            ).known_fact_ids,
        )
        await self._action(
            "cooperation:ask_location",
            "porter_finn",
            [
                "备用保险丝在哪里？请把你确定知道的位置告诉我。",
                "请向我披露 spare_fuse 的确切位置。",
            ],
            ExpectedAction("tell_player", "porter_finn"),
        )
        await self._action(
            "cooperation:give_fuse",
            "porter_finn",
            [
                "先把保险丝交给莉娅恢复供电，搬运责任之后按程序处理，可以吗？",
                "我理解你担心被追责，但请先把 spare_fuse 交给 mechanic_lia。",
            ],
            ExpectedAction("give_item", "porter_finn"),
        )
        await self._finish_common("cooperation")

    async def _run_procedure(self) -> None:
        await self._observe("gate_console", "procedure:observe_console")
        await self._action(
            "procedure:inspect_generator",
            "mechanic_lia",
            ["请根据 E-17 亲自检查 generator。"],
            ExpectedAction("inspect_object", "mechanic_lia", object_id="generator"),
        )
        await self._action(
            "procedure:lia_tell_maren",
            "mechanic_lia",
            ["把缺少保险丝的检查结论告诉 guard_captain_maren。"],
            ExpectedAction(
                "tell_npc",
                "mechanic_lia",
                target_npc_id="guard_captain_maren",
            ),
        )
        await self._observe("manifest_board", "procedure:observe_manifest")
        await self._direct_fact_transfer(
            "procedure:tell_maren_manifest",
            "guard_captain_maren",
            [
                "记录板显示费恩最近移动过 C-12，请把这条已发现证据记入判断。",
                "我把 fact_manifest_finn_moved_c12 这条记录板事实告诉你。",
            ],
            lambda: FACT_MANIFEST_FINN_MOVED_C12
            in self.session.repository.get_npc(
                self.session.session_id, "guard_captain_maren"
            ).known_fact_ids,
        )
        await self._action(
            "procedure:authorize_crate",
            "guard_captain_maren",
            [
                "维修需要保险丝，记录又指向 C-12，请授权紧急检查 cargo_crate_c12。",
                "基于诊断和搬运记录，请执行对 C-12 的检查授权。",
            ],
            ExpectedAction(
                "authorize_object",
                "guard_captain_maren",
                object_id="cargo_crate_c12",
            ),
        )
        await self._action(
            "procedure:give_fuse",
            "porter_finn",
            [
                "玛伦已经授权检查 C-12，请把 spare_fuse 交给 mechanic_lia。",
                "按现有授权执行保险丝交付。",
            ],
            ExpectedAction("give_item", "porter_finn"),
        )
        await self._finish_common("procedure")

    async def _finish_common(self, route: str) -> None:
        await self._action(
            f"{route}:install_fuse",
            "mechanic_lia",
            ["保险丝已经交给你，请把 spare_fuse 安装到 generator。"],
            ExpectedAction("install_item", "mechanic_lia", object_id="generator"),
        )
        await self._action(
            f"{route}:authorize_restart",
            "guard_captain_maren",
            ["保险丝已安装，请授权 control_cabinet 进入重启准备。"],
            ExpectedAction(
                "authorize_object",
                "guard_captain_maren",
                object_id="control_cabinet",
            ),
        )
        await self._action(
            f"{route}:restart_gate",
            "guard_captain_maren",
            [
                "控制柜已授权，请操作 control_cabinet 执行最终重启；"
                "结构化 operation 必须是 restart_gate_power。"
            ],
            ExpectedAction(
                "operate_object",
                "guard_captain_maren",
                object_id="control_cabinet",
            ),
        )
        world = self.session.repository.get_world(self.session.session_id)
        if world.objective_state != "prototype_success":
            raise AssertionError(f"{route} ended at {world.objective_state}")

    async def _action(
        self,
        step: str,
        npc_id: str,
        prompts: list[str],
        expected: ExpectedAction,
    ) -> None:
        failures: list[str] = []
        for attempt in range(1, self.step_attempts + 1):
            prompt = prompts[(attempt - 1) % len(prompts)]
            messages = await self._turn(npc_id, prompt)
            plan = next(
                (item for item in messages if isinstance(item, SceneActionPlanMessage)),
                None,
            )
            if plan is not None and self._matches(plan, expected):
                responses = await self._complete_scene_action(plan)
                await self._finish_internal_replies(responses)
                self._record_step(step, attempt, "pass", plan.payload.action.model_dump())
                await asyncio.sleep(self.inter_turn_delay_seconds)
                return
            if plan is not None:
                failures.append(
                    f"unexpected:{plan.payload.action.action_type}:"
                    f"{plan.payload.action.actor_id}:{plan.payload.action.object_id}"
                )
                await self._interrupt_scene_action(plan)
            else:
                failures.append("no_scene_action")
            await asyncio.sleep(self.retry_delay_seconds * attempt)
        self._record_step(step, self.step_attempts, "fail", {"failures": failures})
        raise AssertionError(f"{step} failed after retries: {failures}")

    async def _direct_fact_transfer(
        self,
        step: str,
        npc_id: str,
        prompts: list[str],
        completed: Callable[[], bool],
    ) -> None:
        failures: list[str] = []
        for attempt in range(1, self.step_attempts + 1):
            prompt = prompts[(attempt - 1) % len(prompts)]
            messages = await self._turn(npc_id, prompt)
            if completed():
                self._record_step(step, attempt, "pass", {"direct_commit": True})
                await asyncio.sleep(self.inter_turn_delay_seconds)
                return
            plan = next(
                (item for item in messages if isinstance(item, SceneActionPlanMessage)),
                None,
            )
            if plan is not None:
                failures.append(f"unexpected:{plan.payload.action.action_type}")
                await self._interrupt_scene_action(plan)
            else:
                failures.append("fact_not_committed")
            await asyncio.sleep(self.retry_delay_seconds * attempt)
        self._record_step(step, self.step_attempts, "fail", {"failures": failures})
        raise AssertionError(f"{step} failed after retries: {failures}")

    async def _observe(self, object_id: str, step: str) -> None:
        self.sequence += 1
        world = self.session.repository.get_world(self.session.session_id)
        messages = await self.session.handle_async(
            SceneObserveRequestMessage.model_validate(
                {
                    "message_id": f"mock-observe:{self.sequence}",
                    "payload": {
                        "session_id": self.session.session_id,
                        "request_id": f"mock-observe:{self.sequence}",
                        "object_id": object_id,
                        "expected_world_version": world.version,
                    },
                }
            )
        )
        error = next((item for item in messages if getattr(item, "type", "") == "error"), None)
        if error is not None:
            raise AssertionError(f"{step} failed: {error.payload.code}")
        self._record_step(step, 1, "pass", {"object_id": object_id})

    async def _reset(self, token: str) -> None:
        await self.session.handle_async(
            PrototypeResetRequestMessage.model_validate(
                {
                    "message_id": f"mock-reset:{token}",
                    "payload": {
                        "session_id": self.session.session_id,
                        "reset_token": f"mock-reset:{token}",
                    },
                }
            )
        )

    async def _turn(self, npc_id: str, player_input: str) -> list[Any]:
        self.sequence += 1
        turn_id = f"{self.session.session_id}:mock:{self.sequence}"
        return await self.session.handle_async(
            TurnRequestMessage.model_validate(
                {
                    "message_id": f"mock-request:{self.sequence}",
                    "payload": {
                        "session_id": self.session.session_id,
                        "turn_id": turn_id,
                        "npc_id": npc_id,
                        "player_input": player_input,
                        "scene": {"location": "prototype_gate_repair"},
                        "character_core": "Mock Unity client; Backend projection is authoritative.",
                    },
                }
            )
        )

    async def _complete_scene_action(self, plan: SceneActionPlanMessage) -> list[Any]:
        action = plan.payload.action
        responses: list[Any] = []
        for event_type in ("ack", "started", "completed"):
            responses = await self.session.handle_async(
                SceneActionEventMessage.model_validate(
                    {
                        "message_id": f"mock-event:{action.action_id}:{event_type}",
                        "type": f"scene.action.{event_type}",
                        "payload": {
                            "session_id": self.session.session_id,
                            "turn_id": action.turn_id,
                            "action_id": action.action_id,
                            "idempotency_key": plan.payload.idempotency_key,
                            "event_type": event_type,
                        },
                    }
                )
            )
        return responses

    async def _interrupt_scene_action(self, plan: SceneActionPlanMessage) -> None:
        action = plan.payload.action
        await self.session.handle_async(
            SceneActionEventMessage.model_validate(
                {
                    "message_id": f"mock-event:{action.action_id}:interrupted",
                    "type": "scene.action.interrupted",
                    "payload": {
                        "session_id": self.session.session_id,
                        "turn_id": action.turn_id,
                        "action_id": action.action_id,
                        "idempotency_key": plan.payload.idempotency_key,
                        "event_type": "interrupted",
                        "detail": "mock rejected unexpected plan",
                    },
                }
            )
        )

    async def _finish_internal_replies(self, messages: list[Any]) -> None:
        for message in messages:
            if not isinstance(message, PerformancePlanMessage):
                continue
            directive = message.payload.directive
            if not directive.turn_id.endswith(":reply"):
                continue
            await self.session.handle_async(
                PerformanceEventMessage.model_validate(
                    {
                        "message_id": f"mock-performance:{directive.turn_id}:completed",
                        "type": "performance.completed",
                        "payload": {
                            "session_id": self.session.session_id,
                            "turn_id": directive.turn_id,
                            "idempotency_key": message.payload.idempotency_key,
                            "event_type": "completed",
                        },
                    }
                )
            )

    @staticmethod
    def _matches(plan: SceneActionPlanMessage, expected: ExpectedAction) -> bool:
        action = plan.payload.action
        return (
            action.action_type == expected.action_type
            and action.actor_id == expected.actor_id
            and (expected.object_id is None or action.object_id == expected.object_id)
            and (
                expected.target_npc_id is None
                or action.target_npc_id == expected.target_npc_id
            )
        )

    def _record_step(
        self,
        step: str,
        attempt: int,
        status: str,
        detail: dict[str, Any],
    ) -> None:
        record = {
            "step": step,
            "attempt": attempt,
            "status": status,
            "detail": detail,
        }
        self.step_records.append(record)
        print(
            f"[P3_MOCK_STEP] step={step} attempt={attempt} status={status} "
            f"detail={json.dumps(detail, ensure_ascii=False, sort_keys=True)}"
        )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run P3 Real Director with a Mock Unity client")
    parser.add_argument("--model", default="qwen3.8-flash")
    parser.add_argument("--model-profile", default="idealab_qwen")
    parser.add_argument(
        "--transport",
        choices=("codex-cli", "agents-sdk"),
        default="codex-cli",
    )
    parser.add_argument("--session-id", default="p3-local-qwen38")
    parser.add_argument(
        "--smoke-only",
        action="store_true",
        help="Run one state-changing turn through the production bounded chain.",
    )
    parser.add_argument("--step-attempts", type=int, default=5)
    parser.add_argument("--model-retry-attempts", type=int, default=5)
    parser.add_argument("--retry-delay-seconds", type=float, default=8.0)
    parser.add_argument("--inter-turn-delay-seconds", type=float, default=2.0)
    parser.add_argument("--timeout-seconds", type=float, default=90.0)
    parser.add_argument(
        "--database",
        type=Path,
        default=Path("artifacts/prototype-p3/p3-local-mock.sqlite3"),
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("artifacts/prototype-p3/p3-local-mock-report.json"),
    )
    return parser.parse_args()


async def run(args: argparse.Namespace) -> dict[str, Any]:
    settings = Settings(
        model=args.model,
        director_model=args.model,
        model_profile=args.model_profile,
        timeout_seconds=args.timeout_seconds,
        model_retry_attempts=args.model_retry_attempts,
        max_repair_attempts=2,
    )
    settings.validate()
    args.database.parent.mkdir(parents=True, exist_ok=True)
    generator = None
    codex_client = None
    if args.transport == "codex-cli":
        generator, codex_client = build_codex_orchestrated_generator(
            settings,
            timeout_seconds=args.timeout_seconds,
        )
    session = PrototypeRealDirectorSession(
        args.database,
        args.session_id,
        settings=settings,
        generator=generator,
        reset_on_start=True,
    )
    try:
        runner = P3MockUnityRunner(
            session,
            step_attempts=args.step_attempts,
            retry_delay_seconds=args.retry_delay_seconds,
            inter_turn_delay_seconds=args.inter_turn_delay_seconds,
        )
        try:
            report = await (runner.run_smoke() if args.smoke_only else runner.run())
        except Exception as error:
            report = {
                "status": "fail",
                "mode": "real-model-mock-unity",
                "model": args.model,
                "transport": args.transport,
                "error": f"{type(error).__name__}: {error}",
                "steps": list(runner.step_records),
                "session_report": session.report(),
                "recorded_at": datetime.now(UTC).isoformat(),
            }
        if codex_client is not None:
            report["model_calls"] = list(codex_client.telemetry)
        return report
    finally:
        session.close()


def _extract_json_object(value: str) -> str:
    """Accept a fenced JSON object emitted by models that ignore output-file purity."""
    stripped = value.strip()
    start = stripped.find("{")
    end = stripped.rfind("}")
    if start < 0 or end < start:
        raise ValueError("structured model output contains no JSON object")
    return stripped[start : end + 1]


def main() -> int:
    args = parse_args()
    try:
        report = asyncio.run(run(args))
    except Exception as error:
        report = {
            "status": "fail",
            "model": args.model,
            "error": f"{type(error).__name__}: {error}",
            "recorded_at": datetime.now(UTC).isoformat(),
        }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(
        f"[P3_MOCK_SUMMARY] status={report['status']} model={args.model} "
        f"output={args.output}"
    )
    return 0 if report["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
