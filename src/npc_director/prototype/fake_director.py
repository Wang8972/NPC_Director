from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from npc_director.contracts import (
    UNITY_MESSAGE_ADAPTER,
    ErrorMessage,
    ErrorPayload,
    PerformanceDirective,
    PerformanceEventMessage,
    PerformancePlanMessage,
    PrototypeResetRequestMessage,
    SceneActionCommand,
    SceneActionEventMessage,
    SceneActionPlanMessage,
    SceneObserveRequestMessage,
    StateSnapshotMessage,
    TurnRequestMessage,
    WorldEventMessage,
)
from npc_director.prototype.models import (
    FACT_CRATE_CONTAINS_FUSE,
    FACT_GENERATOR_MISSING_FUSE,
    FACT_MANIFEST_FINN_MOVED_C12,
    NPC_IDS,
    ActionCommitResult,
    ActionPlan,
    SceneActionCandidate,
    semantic_state_payload,
)
from npc_director.prototype.orchestrator import (
    PrototypeConversationOrchestrator,
    RecordingPrototypeAdapter,
)
from npc_director.prototype.repository import PrototypeStateRepository

FIXTURE_VERSION = "prototype-p2-fixture-v1"


class PrototypeFakeDirectorSession:
    """Deterministic P2 session using the production prototype rules and repository."""

    def __init__(
        self,
        database: str | Path,
        session_id: str = "p2-fake-001",
        *,
        reset_on_start: bool = False,
    ) -> None:
        self.repository = PrototypeStateRepository(database)
        self.session_id = session_id
        if reset_on_start:
            self.repository.reset(session_id)
        else:
            self.repository.initialize(session_id)
        self.adapter = RecordingPrototypeAdapter()
        self.orchestrator = PrototypeConversationOrchestrator(
            self.repository,
            adapter=self.adapter,
        )
        self._turn_cache: dict[str, tuple[str, list[Any]]] = {}
        self._observe_cache: dict[str, tuple[str, list[Any]]] = {}
        self._internal_turns: dict[str, tuple[str, str]] = {}
        self._emitted_actions: dict[str, tuple[str, str]] = {}
        self._interactions: set[str] = set()
        self._route_success_counts = {"cooperation": 0, "procedure": 0}
        self._action_type_counts: dict[str, int] = {}
        self._rejection_counts: dict[str, int] = {}
        self._performance_plan_count = 0
        self._scene_action_plan_count = 0
        self._reset_count = 0
        self._event_sequence = 0
        self._initial_semantic_hash = self.semantic_state_hash()

    def close(self) -> None:
        self.repository.close()

    def initial_messages(self) -> list[Any]:
        return [self.snapshot_message()]

    def handle(self, message: Any) -> list[Any]:
        if isinstance(message, dict):
            message = UNITY_MESSAGE_ADAPTER.validate_python(message)
        if isinstance(message, SceneObserveRequestMessage):
            return self._handle_observe(message)
        if isinstance(message, TurnRequestMessage):
            return self._handle_turn(message)
        if isinstance(message, SceneActionEventMessage):
            return self._handle_scene_event(message)
        if isinstance(message, PerformanceEventMessage):
            return self._handle_performance_event(message)
        if isinstance(message, PrototypeResetRequestMessage):
            return self._handle_reset(message)
        return [
            self._error(
                message.message_id,
                "unsupported_direction",
                "This message type is server-to-client only in P2 Fake mode.",
            )
        ]

    def snapshot_message(self) -> StateSnapshotMessage:
        world = self.repository.get_world(self.session_id)
        pending = None
        if world.pending_action is not None:
            pending = world.pending_action.model_dump(mode="json")
        return StateSnapshotMessage.model_validate(
            {
                "message_id": self._message_id("snapshot"),
                "payload": {
                    "session_id": world.session_id,
                    "scene_id": world.current_scene_id,
                    "world_version": world.version,
                    "objective_state": world.objective_state,
                    "object_states": [
                        {"object_id": object_id, "state": state}
                        for object_id, state in sorted(world.object_states.items())
                    ],
                    "item_locations": [
                        {"item_id": item_id, "location_id": location_id}
                        for item_id, location_id in sorted(world.item_locations.items())
                    ],
                    "discovered_fact_ids": sorted(world.discovered_fact_ids),
                    "route_flags": world.route_flags.model_dump(mode="json"),
                    "pending_action": pending,
                },
            }
        )

    def semantic_state_hash(self) -> str:
        payload = semantic_state_payload(
            self.repository.get_world(self.session_id),
            self.repository.get_npcs(self.session_id),
        )
        canonical = json.dumps(
            payload,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
        return hashlib.sha256(canonical.encode()).hexdigest()

    def report(self) -> dict[str, Any]:
        world = self.repository.get_world(self.session_id)
        required_interactions = {
            "player_npc",
            "player_scene",
            "npc_scene",
            "npc_npc",
        }
        passed = (
            required_interactions <= self._interactions
            and all(count >= 1 for count in self._route_success_counts.values())
        )
        return {
            "stage": "P2 Fake Director",
            "status": "pass" if passed else "in_progress",
            "fixture_version": FIXTURE_VERSION,
            "session_id": self.session_id,
            "no_api_key_required": True,
            "interaction_types_seen": sorted(self._interactions),
            "route_success_counts": dict(self._route_success_counts),
            "scene_action_plan_count": self._scene_action_plan_count,
            "performance_plan_count": self._performance_plan_count,
            "action_type_counts": dict(sorted(self._action_type_counts.items())),
            "rejection_counts": dict(sorted(self._rejection_counts.items())),
            "reset_count": self._reset_count,
            "current_objective_state": world.objective_state,
            "current_semantic_state_hash": self.semantic_state_hash(),
            "initial_semantic_state_hash": self._initial_semantic_hash,
        }

    def _handle_observe(self, message: SceneObserveRequestMessage) -> list[Any]:
        payload = message.payload
        if payload.session_id != self.session_id:
            return [self._session_error(message.message_id)]
        fingerprint = payload.model_dump_json()
        cached = self._observe_cache.get(payload.request_id)
        if cached is not None:
            if cached[0] != fingerprint:
                return [
                    self._error(
                        message.message_id,
                        "idempotency_conflict",
                        "request_id was reused with different observation data.",
                    )
                ]
            return cached[1]
        if self.orchestrator.is_input_locked(self.session_id):
            return [
                self._error(
                    message.message_id,
                    "input_locked",
                    "A scene action or NPC-to-NPC reply is still active.",
                ),
                self.snapshot_message(),
            ]
        world = self.repository.get_world(self.session_id)
        if payload.expected_world_version != world.version:
            response = [
                self._error(
                    message.message_id,
                    "world_version_mismatch",
                    f"Expected world version {world.version}.",
                ),
                self.snapshot_message(),
            ]
        else:
            self._interactions.add("player_scene")
            candidate = SceneActionCandidate(
                session_id=self.session_id,
                turn_id=payload.request_id,
                action_id=f"{payload.request_id}:observe",
                actor_id="player",
                action_type="inspect_object",
                object_id=payload.object_id,
            )
            response = self._submit_candidate(candidate, observation=True)
        self._observe_cache[payload.request_id] = (fingerprint, response)
        return response

    def _handle_turn(self, message: TurnRequestMessage) -> list[Any]:
        request = message.payload
        if request.session_id != self.session_id:
            return [self._session_error(message.message_id, request.turn_id)]
        fingerprint = request.model_dump_json()
        cached = self._turn_cache.get(request.turn_id)
        if cached is not None:
            if cached[0] != fingerprint:
                return [
                    self._error(
                        message.message_id,
                        "idempotency_conflict",
                        "turn_id was reused with different input.",
                        request.turn_id,
                    )
                ]
            return cached[1]

        if self.orchestrator.is_input_locked(self.session_id):
            return [
                self._error(
                    message.message_id,
                    "input_locked",
                    "A scene action or NPC-to-NPC reply is still active.",
                    request.turn_id,
                ),
                self.snapshot_message(),
            ]

        self._interactions.add("player_npc")
        fixture_id = request.player_input.strip()
        response = self._fixture_response(
            fixture_id,
            request.turn_id,
            request.npc_id,
            message.message_id,
        )
        self._turn_cache[request.turn_id] = (fingerprint, response)
        return response

    def _fixture_response(
        self,
        fixture_id: str,
        turn_id: str,
        selected_npc_id: str,
        message_id: str,
    ) -> list[Any]:
        if selected_npc_id not in NPC_IDS:
            return [self._error(message_id, "error_unknown_actor", selected_npc_id, turn_id)]
        if fixture_id == "fixture:roundtable":
            return [
                self._performance_plan(
                    selected_npc_id,
                    turn_id,
                    "我不会替你召集自动圆桌。请选定一名当事人，明确你要转述的事实或请求。",
                )
            ]

        definitions: dict[str, tuple[str, dict[str, Any]]] = {
            "fixture:inspect_generator": (
                "mechanic_lia",
                {
                    "actor_id": "mechanic_lia",
                    "action_type": "inspect_object",
                    "object_id": "generator",
                },
            ),
            "fixture:lia_tell_maren_diagnosis": (
                "mechanic_lia",
                {
                    "actor_id": "mechanic_lia",
                    "action_type": "tell_npc",
                    "target_npc_id": "guard_captain_maren",
                    "fact_id": FACT_GENERATOR_MISSING_FUSE,
                },
            ),
            "fixture:ask_fuse_location": (
                "porter_finn",
                {
                    "actor_id": "porter_finn",
                    "action_type": "tell_player",
                    "fact_id": FACT_CRATE_CONTAINS_FUSE,
                },
            ),
            "fixture:cooperation_offer": (
                "porter_finn",
                {
                    "actor_id": "porter_finn",
                    "action_type": "give_item",
                    "item_id": "spare_fuse",
                    "target_id": "mechanic_lia",
                    "gameplay_intent": "cooperation_offer",
                },
            ),
            "fixture:request_authorization": (
                "guard_captain_maren",
                {
                    "actor_id": "guard_captain_maren",
                    "action_type": "authorize_object",
                    "object_id": "cargo_crate_c12",
                    "gameplay_intent": "request_authorization",
                },
            ),
            "fixture:give_fuse": (
                "porter_finn",
                {
                    "actor_id": "porter_finn",
                    "action_type": "give_item",
                    "item_id": "spare_fuse",
                    "target_id": "mechanic_lia",
                },
            ),
            "fixture:install_fuse": (
                "mechanic_lia",
                {
                    "actor_id": "mechanic_lia",
                    "action_type": "install_item",
                    "object_id": "generator",
                    "item_id": "spare_fuse",
                },
            ),
            "fixture:authorize_restart": (
                "guard_captain_maren",
                {
                    "actor_id": "guard_captain_maren",
                    "action_type": "authorize_object",
                    "object_id": "control_cabinet",
                },
            ),
            "fixture:restart_gate": (
                "guard_captain_maren",
                {
                    "actor_id": "guard_captain_maren",
                    "action_type": "operate_object",
                    "object_id": "control_cabinet",
                    "operation": "restart_gate_power",
                },
            ),
            "fixture:unknown_object": (
                selected_npc_id,
                {
                    "actor_id": selected_npc_id,
                    "action_type": "inspect_object",
                    "object_id": "imaginary_panel",
                },
            ),
            "fixture:unauthorized_restart": (
                "mechanic_lia",
                {
                    "actor_id": "mechanic_lia",
                    "action_type": "operate_object",
                    "object_id": "control_cabinet",
                    "operation": "restart_gate_power",
                },
            ),
        }
        if fixture_id == "fixture:tell_diagnosis":
            if selected_npc_id not in {"guard_captain_maren", "porter_finn"}:
                return [
                    self._fixture_actor_error(message_id, turn_id, "玛伦或费恩", selected_npc_id)
                ]
            values = {
                "actor_id": "player",
                "action_type": "tell_npc",
                "target_npc_id": selected_npc_id,
                "fact_id": FACT_GENERATOR_MISSING_FUSE,
            }
            expected_actor = selected_npc_id
        elif fixture_id == "fixture:tell_manifest":
            expected_actor = "guard_captain_maren"
            values = {
                "actor_id": "player",
                "action_type": "tell_npc",
                "target_npc_id": "guard_captain_maren",
                "fact_id": FACT_MANIFEST_FINN_MOVED_C12,
            }
        elif fixture_id in definitions:
            expected_actor, values = definitions[fixture_id]
        else:
            return [
                self._performance_plan(
                    selected_npc_id,
                    turn_id,
                    f"未知 Fake fixture：{fixture_id}。状态没有改变。",
                )
            ]

        if selected_npc_id != expected_actor:
            return [
                self._fixture_actor_error(message_id, turn_id, expected_actor, selected_npc_id)
            ]
        candidate = SceneActionCandidate(
            session_id=self.session_id,
            turn_id=turn_id,
            action_id=f"{turn_id}:a1",
            **values,
        )
        return self._submit_candidate(candidate, response_npc_id=selected_npc_id)

    def _submit_candidate(
        self,
        candidate: SceneActionCandidate,
        *,
        observation: bool = False,
        response_npc_id: str | None = None,
    ) -> list[Any]:
        action_plan_count = len(self.adapter.action_plans)
        result = self.orchestrator.submit(candidate)
        if not result.approved:
            assert result.rejection is not None
            rejection = result.rejection
            self._rejection_counts[rejection.reason_code] = (
                self._rejection_counts.get(rejection.reason_code, 0) + 1
            )
            messages: list[Any] = [
                self._world_event(
                    "action_rejected",
                    rejection.player_feedback,
                    event_hint=candidate.action_id,
                )
            ]
            if response_npc_id is not None:
                messages.append(
                    self._performance_plan(
                        response_npc_id,
                        candidate.turn_id,
                        rejection.player_feedback,
                    )
                )
            messages.append(self.snapshot_message())
            return messages

        self._action_type_counts[candidate.action_type] = (
            self._action_type_counts.get(candidate.action_type, 0) + 1
        )
        if result.commit is not None:
            event_type = "observation_committed" if observation else "action_committed"
            messages = self._commit_messages(result.commit, event_type=event_type)
            if response_npc_id is not None:
                messages.append(
                    self._performance_plan(
                        response_npc_id,
                        candidate.turn_id,
                        "事实已按当前权威状态记录；我会据此继续处理。",
                    )
                )
            return messages

        if len(self.adapter.action_plans) != action_plan_count + 1:
            raise RuntimeError("Approved scene action did not emit exactly one action plan")
        self._interactions.add("npc_scene")
        plan = self.adapter.action_plans[-1]
        self._scene_action_plan_count += 1
        return [self._scene_action_plan(plan), self.snapshot_message()]

    def _handle_scene_event(self, message: SceneActionEventMessage) -> list[Any]:
        event = message.payload
        if event.session_id != self.session_id:
            return [self._session_error(message.message_id, event.turn_id)]
        identity = self._emitted_actions.get(event.action_id)
        if identity is None or identity != (event.turn_id, event.idempotency_key):
            return [
                self._error(
                    message.message_id,
                    "event_rejected",
                    "scene action event does not match an emitted action/turn/key",
                    event.turn_id,
                ),
                self.snapshot_message(),
            ]
        before_internal = len(self.adapter.internal_reply_plans)
        try:
            result = self.orchestrator.handle_action_event(
                event.action_id,
                event.idempotency_key,
                event.event_type,
            )
        except Exception as error:  # deterministic protocol error, no state mutation
            return [
                self._error(
                    message.message_id,
                    "event_rejected",
                    f"{type(error).__name__}: {error}",
                    event.turn_id,
                ),
                self.snapshot_message(),
            ]
        if event.event_type in {"ack", "started"}:
            return []
        if event.event_type in {"interrupted", "error"}:
            return [
                self._world_event(
                    "action_cancelled",
                    f"{event.action_id} ended as {event.event_type}; committed state is unchanged.",
                    event_hint=event.action_id,
                ),
                self.snapshot_message(),
            ]
        assert result is not None
        messages = self._commit_messages(result, event_type="action_committed")
        if len(self.adapter.internal_reply_plans) == before_internal + 1:
            self._interactions.add("npc_npc")
            reply = self.adapter.internal_reply_plans[-1]
            reply_turn_id = f"{reply.source_action_id}:reply"
            performance = self._performance_plan(reply.target_npc_id, reply_turn_id, reply.text)
            self._internal_turns[reply_turn_id] = (
                reply.source_action_id,
                performance.payload.idempotency_key,
            )
            messages.append(performance)
        return messages

    def _handle_performance_event(self, message: PerformanceEventMessage) -> list[Any]:
        event = message.payload
        if event.session_id != self.session_id:
            return [self._session_error(message.message_id, event.turn_id)]
        internal = self._internal_turns.get(event.turn_id)
        if internal is not None and event.idempotency_key != internal[1]:
            return [
                self._error(
                    message.message_id,
                    "event_rejected",
                    "internal performance event key mismatch",
                    event.turn_id,
                )
            ]
        if internal is not None and event.event_type.value in {
            "completed",
            "interrupted",
            "error",
        }:
            self.orchestrator.finish_internal_reply(internal[0], event.event_type.value)
        return []

    def _handle_reset(self, message: PrototypeResetRequestMessage) -> list[Any]:
        if message.payload.session_id != self.session_id:
            return [self._session_error(message.message_id)]
        self.repository.reset(self.session_id)
        self.adapter = RecordingPrototypeAdapter()
        self.orchestrator = PrototypeConversationOrchestrator(
            self.repository,
            adapter=self.adapter,
        )
        self._turn_cache.clear()
        self._observe_cache.clear()
        self._internal_turns.clear()
        self._emitted_actions.clear()
        self._reset_count += 1
        if self.semantic_state_hash() != self._initial_semantic_hash:
            raise RuntimeError("Prototype reset did not restore the frozen initial state")
        return [
            self._world_event("session_reset", "P2 原型已恢复固定初始状态。"),
            self.snapshot_message(),
        ]

    def _scene_action_plan(self, plan: ActionPlan) -> SceneActionPlanMessage:
        pending = self.repository.get_pending(plan.action_id)
        if pending is None:
            raise RuntimeError(f"Pending action {plan.action_id!r} is missing")
        approved = pending.approved
        candidate = approved.candidate
        command = SceneActionCommand(
            session_id=candidate.session_id,
            turn_id=candidate.turn_id,
            action_id=candidate.action_id,
            actor_id=candidate.actor_id,
            action_type=candidate.action_type,
            object_id=candidate.object_id,
            item_id=candidate.item_id,
            target_id=candidate.target_id,
            target_npc_id=candidate.target_npc_id,
            operation=candidate.operation,
            basis_world_version=approved.basis_world_version,
            basis_npc_versions=approved.basis_npc_versions,
        )
        self._emitted_actions[candidate.action_id] = (
            candidate.turn_id,
            plan.idempotency_key,
        )
        return SceneActionPlanMessage.model_validate(
            {
                "message_id": self._message_id("scene-plan"),
                "payload": {
                    "action": command.model_dump(mode="json"),
                    "pre_commit_directive": self._directive(
                        candidate.actor_id,
                        candidate.turn_id,
                        approved.pre_commit_text,
                    ).model_dump(mode="json"),
                    "idempotency_key": plan.idempotency_key,
                },
            }
        )

    def _performance_plan(
        self,
        npc_id: str,
        turn_id: str,
        text: str,
    ) -> PerformancePlanMessage:
        key = hashlib.sha256(f"{self.session_id}:{turn_id}:performance:1.0".encode()).hexdigest()
        self._performance_plan_count += 1
        return PerformancePlanMessage.model_validate(
            {
                "message_id": self._message_id("performance"),
                "payload": {
                    "directive": self._directive(npc_id, turn_id, text).model_dump(mode="json"),
                    "idempotency_key": key,
                },
            }
        )

    def _directive(self, npc_id: str, turn_id: str, text: str) -> PerformanceDirective:
        emotion = {
            "guard_captain_maren": ("stern", "firm"),
            "mechanic_lia": ("curious", "neutral"),
            "porter_finn": ("guarded", "wary"),
        }
        primary, voice = emotion[npc_id]
        return PerformanceDirective.model_validate(
            {
                "session_id": self.session_id,
                "turn_id": turn_id,
                "npc_id": npc_id,
                "dialogue": {"text": text, "language": "zh-CN", "voice_style": voice},
                "emotion": {"coarse": "neutral", "primary": primary},
                "face_cues": [{"preset": "neutral", "intensity": 0.5}],
                "body_cues": [{"action": "nod", "priority": 50}],
                "gaze": {"target": "player_head", "mode": "direct"},
                "interrupt_policy": "allow_any",
                "confidence": 1.0,
                "evidence": {"lore_refs": []},
                "runtime_meta": {
                    "specialists_called": ["baseline"],
                    "prompt_versions": [FIXTURE_VERSION],
                    "model": "prototype-fake-director",
                    "trace_id": f"p2:{turn_id}",
                    "response_id": f"p2:{turn_id}:{npc_id}",
                },
            }
        )

    def _commit_messages(
        self,
        result: ActionCommitResult,
        *,
        event_type: str,
    ) -> list[Any]:
        pending_feedback = "动作已提交。"
        commit = result
        if commit.applied:
            pending_feedback = self._commit_feedback(commit.action_id)
            if commit.world.objective_state == "prototype_success":
                route = commit.world.route_flags.fuse_route
                if route in self._route_success_counts:
                    self._route_success_counts[route] += 1
        return [
            self._world_event(
                event_type,
                pending_feedback,
                revealed_fact_ids=sorted(commit.reveal_fact_ids),
                event_hint=commit.action_id,
            ),
            self.snapshot_message(),
        ]

    def _commit_feedback(self, action_id: str) -> str:
        with self.repository.connection() as connection:
            row = connection.execute(
                "SELECT result_json FROM prototype_action_commits WHERE action_id = ?",
                (action_id,),
            ).fetchone()
        if row is None:
            return "动作已提交。"
        result = ActionCommitResult.model_validate_json(row["result_json"])
        revealed = ", ".join(sorted(result.reveal_fact_ids))
        return f"动作已提交；公开事实：{revealed}" if revealed else "动作已提交。"

    def _world_event(
        self,
        event_type: str,
        summary: str,
        *,
        revealed_fact_ids: list[str] | None = None,
        event_hint: str | None = None,
    ) -> WorldEventMessage:
        world = self.repository.get_world(self.session_id)
        return WorldEventMessage.model_validate(
            {
                "message_id": self._message_id("world"),
                "payload": {
                    "session_id": self.session_id,
                    "event_id": event_hint or self._message_id("event"),
                    "event_type": event_type,
                    "world_version": world.version,
                    "summary": summary,
                    "revealed_fact_ids": revealed_fact_ids or [],
                },
            }
        )

    def _fixture_actor_error(
        self,
        message_id: str,
        turn_id: str,
        expected: str,
        actual: str,
    ) -> ErrorMessage:
        return self._error(
            message_id,
            "fixture_actor_mismatch",
            f"该操作需要选择 {expected}，当前选择为 {actual}。",
            turn_id,
        )

    def _session_error(self, message_id: str, turn_id: str | None = None) -> ErrorMessage:
        return self._error(
            message_id,
            "session_mismatch",
            "payload session_id does not match the P2 session.",
            turn_id,
        )

    @staticmethod
    def _error(
        message_id: str,
        code: str,
        message: str,
        turn_id: str | None = None,
    ) -> ErrorMessage:
        return ErrorMessage(
            message_id=f"error:{message_id}",
            payload=ErrorPayload(code=code, message=message, turn_id=turn_id),
        )

    def _message_id(self, kind: str) -> str:
        self._event_sequence += 1
        return f"p2:{kind}:{self._event_sequence}"
