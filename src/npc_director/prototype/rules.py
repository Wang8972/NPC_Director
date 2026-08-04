from __future__ import annotations

from npc_director.prototype.models import (
    ACTION_TYPES,
    ACTOR_IDS,
    FACT_CONSOLE_E17,
    FACT_CRATE_CONTAINS_FUSE,
    FACT_CRATE_SEAL_ANOMALY,
    FACT_FUSE_INSTALLED,
    FACT_GATE_RESTARTED,
    FACT_GENERATOR_MISSING_FUSE,
    FACT_MANIFEST_FINN_MOVED_C12,
    ITEM_IDS,
    NPC_IDS,
    OBJECT_IDS,
    ApprovedAction,
    PrototypeEffect,
    PrototypeNpcState,
    PrototypeWorldState,
    RejectedAction,
    SceneActionCandidate,
)


class PrototypePuzzleRules:
    """Deterministic authority for the seven prototype scene actions."""

    def validate(
        self,
        candidate: SceneActionCandidate,
        world: PrototypeWorldState,
        npc_states: dict[str, PrototypeNpcState],
        *,
        hop_index: int = 0,
    ) -> ApprovedAction | RejectedAction:
        common_rejection = self._validate_common(candidate, world)
        if common_rejection is not None:
            return common_rejection

        handler = getattr(self, f"_validate_{candidate.action_type}")
        return handler(candidate, world, npc_states, hop_index=hop_index)

    def _validate_common(
        self,
        candidate: SceneActionCandidate,
        world: PrototypeWorldState,
    ) -> RejectedAction | None:
        if candidate.session_id != world.session_id:
            return self._reject(candidate, "error_wrong_scene", [world.session_id])
        if candidate.action_type not in ACTION_TYPES:
            return self._reject(candidate, "error_unknown_action", list(ACTION_TYPES))
        if candidate.actor_id not in ACTOR_IDS:
            return self._reject(candidate, "error_unknown_actor", list(ACTOR_IDS))
        if candidate.object_id is not None and candidate.object_id not in OBJECT_IDS:
            return self._reject(candidate, "error_unknown_object", list(OBJECT_IDS))
        if candidate.item_id is not None and candidate.item_id not in ITEM_IDS:
            return self._reject(candidate, "error_unknown_item", list(ITEM_IDS))
        if world.objective_state == "prototype_success":
            return self._reject(candidate, "error_terminal_state")
        if world.pending_action is not None:
            return self._reject(candidate, "error_action_pending", [world.pending_action.action_id])
        shape_error = self._shape_error(candidate)
        if shape_error is not None:
            return self._reject(candidate, "error_schema", [shape_error])
        return None

    @staticmethod
    def _shape_error(candidate: SceneActionCandidate) -> str | None:
        required_by_type = {
            "inspect_object": {"object_id"},
            "authorize_object": {"object_id"},
            "give_item": {"item_id", "target_id"},
            "install_item": {"item_id", "object_id"},
            "operate_object": {"object_id", "operation"},
            "tell_npc": {"target_npc_id", "fact_id"},
            "tell_player": {"fact_id"},
        }
        values = candidate.model_dump()
        missing = sorted(
            field for field in required_by_type[candidate.action_type] if values[field] is None
        )
        if missing:
            return f"missing:{','.join(missing)}"
        return None

    def _validate_inspect_object(
        self,
        candidate: SceneActionCandidate,
        world: PrototypeWorldState,
        npc_states: dict[str, PrototypeNpcState],
        **_: object,
    ) -> ApprovedAction | RejectedAction:
        if candidate.actor_id == "player":
            fact_by_object = {
                "gate_console": FACT_CONSOLE_E17,
                "manifest_board": FACT_MANIFEST_FINN_MOVED_C12,
                "cargo_crate_c12": FACT_CRATE_SEAL_ANOMALY,
            }
            fact_id = fact_by_object.get(candidate.object_id or "")
            if fact_id is None:
                return self._reject(
                    candidate,
                    "error_actor_not_capable",
                    ["mechanic_lia checks generator"],
                )
            if fact_id in world.discovered_fact_ids:
                return self._reject(candidate, "already_applied", [fact_id])
            return self._approve(
                candidate,
                world,
                npc_states,
                PrototypeEffect(add_player_fact_ids={fact_id}, reveal_fact_ids={fact_id}),
                feedback=f"观察结果已记录：{fact_id}",
                adapter_required=False,
            )

        if candidate.actor_id != "mechanic_lia" or candidate.object_id != "generator":
            return self._reject(
                candidate,
                "error_actor_not_capable",
                ["mechanic_lia", "generator"],
            )
        if FACT_CONSOLE_E17 not in world.discovered_fact_ids:
            return self._reject(
                candidate,
                "error_missing_fact",
                [FACT_CONSOLE_E17, "inspect gate_console"],
            )
        if world.objective_state != "investigate_fault":
            return self._reject(candidate, "already_applied", [FACT_GENERATOR_MISSING_FUSE])
        effect = PrototypeEffect(
            add_player_fact_ids={FACT_GENERATOR_MISSING_FUSE},
            objective_state="find_fuse",
            npc_fact_additions={"mechanic_lia": {FACT_GENERATOR_MISSING_FUSE}},
            npc_event_additions={"mechanic_lia": {"generator_inspection_completed"}},
            reveal_fact_ids={FACT_GENERATOR_MISSING_FUSE},
        )
        return self._approve(
            candidate,
            world,
            npc_states,
            effect,
            feedback="莉娅完成检查：发电机缺少备用保险丝。",
            pre_commit_text="莉娅正在检查发电机。",
        )

    def _validate_authorize_object(
        self,
        candidate: SceneActionCandidate,
        world: PrototypeWorldState,
        npc_states: dict[str, PrototypeNpcState],
        **_: object,
    ) -> ApprovedAction | RejectedAction:
        if candidate.actor_id != "guard_captain_maren":
            return self._reject(candidate, "error_actor_not_authorized", ["guard_captain_maren"])
        maren = npc_states["guard_captain_maren"]
        if candidate.object_id == "cargo_crate_c12":
            if world.route_flags.crate_c12_authorized:
                return self._reject(candidate, "already_applied", ["cargo_crate_c12"])
            missing = sorted(
                {
                    FACT_GENERATOR_MISSING_FUSE,
                    FACT_MANIFEST_FINN_MOVED_C12,
                }
                - maren.known_fact_ids
            )
            if missing:
                return self._reject(candidate, "error_missing_fact", missing)
            if candidate.gameplay_intent != "request_authorization":
                return self._reject(
                    candidate,
                    "error_missing_precondition",
                    ["request_authorization"],
                )
            if world.objective_state != "find_fuse":
                return self._reject(candidate, "error_missing_precondition", ["find_fuse"])
            effect = PrototypeEffect(
                set_object_states={"cargo_crate_c12": "access_authorized"},
                set_route_flags={"crate_c12_authorized": True},
            )
            return self._approve(
                candidate,
                world,
                npc_states,
                effect,
                feedback="玛伦已授权紧急检查 C-12。",
                pre_commit_text="玛伦正在核对诊断与搬运记录。",
            )

        if candidate.object_id == "control_cabinet":
            if world.route_flags.control_cabinet_authorized:
                return self._reject(candidate, "already_applied", ["control_cabinet"])
            if world.objective_state != "restart_gate" or (
                FACT_FUSE_INSTALLED not in world.discovered_fact_ids
            ):
                return self._reject(
                    candidate,
                    "error_missing_precondition",
                    [FACT_FUSE_INSTALLED, "install fuse first"],
                )
            effect = PrototypeEffect(
                set_object_states={"control_cabinet": "authorized"},
                set_route_flags={"control_cabinet_authorized": True},
            )
            return self._approve(
                candidate,
                world,
                npc_states,
                effect,
                feedback="控制柜已授权。",
                pre_commit_text="玛伦正在授权控制柜。",
            )
        return self._reject(
            candidate,
            "error_actor_not_authorized",
            ["cargo_crate_c12", "control_cabinet"],
        )

    def _validate_give_item(
        self,
        candidate: SceneActionCandidate,
        world: PrototypeWorldState,
        npc_states: dict[str, PrototypeNpcState],
        **_: object,
    ) -> ApprovedAction | RejectedAction:
        if candidate.actor_id != "porter_finn":
            return self._reject(candidate, "error_actor_not_capable", ["porter_finn"])
        if candidate.item_id != "spare_fuse" or candidate.target_id != "mechanic_lia":
            return self._reject(
                candidate,
                "error_missing_precondition",
                ["spare_fuse", "mechanic_lia"],
            )
        if world.item_locations["spare_fuse"] != "cargo_crate_c12":
            return self._reject(candidate, "already_applied", ["spare_fuse delivered"])
        if world.objective_state != "find_fuse":
            return self._reject(candidate, "error_missing_precondition", ["find_fuse"])
        finn = npc_states["porter_finn"]
        if FACT_CRATE_CONTAINS_FUSE not in finn.known_fact_ids:
            return self._reject(candidate, "error_actor_missing_fact", [FACT_CRATE_CONTAINS_FUSE])

        if world.route_flags.crate_c12_authorized:
            route = "procedure"
        else:
            if FACT_GENERATOR_MISSING_FUSE not in finn.known_fact_ids:
                return self._reject(
                    candidate,
                    "error_missing_fact",
                    [FACT_GENERATOR_MISSING_FUSE],
                )
            if candidate.gameplay_intent != "cooperation_offer":
                return self._reject(
                    candidate,
                    "error_missing_precondition",
                    ["respond_to_concern", "request_delivery"],
                )
            route = "cooperation"

        effect = PrototypeEffect(
            set_item_locations={"spare_fuse": "mechanic_lia"},
            add_player_fact_ids={FACT_CRATE_CONTAINS_FUSE},
            set_route_flags={"fuse_route": route},
            objective_state="install_fuse",
            npc_event_additions={"guard_captain_maren": {"fuse_delivery_witnessed"}},
            reveal_fact_ids={FACT_CRATE_CONTAINS_FUSE},
        )
        return self._approve(
            candidate,
            world,
            npc_states,
            effect,
            feedback=f"费恩已按 {route} 路线把保险丝交给莉娅。",
            pre_commit_text="费恩正在取出并交付备件。",
        )

    def _validate_install_item(
        self,
        candidate: SceneActionCandidate,
        world: PrototypeWorldState,
        npc_states: dict[str, PrototypeNpcState],
        **_: object,
    ) -> ApprovedAction | RejectedAction:
        if candidate.actor_id != "mechanic_lia":
            return self._reject(candidate, "error_actor_not_capable", ["mechanic_lia"])
        if candidate.item_id != "spare_fuse" or candidate.object_id != "generator":
            return self._reject(
                candidate,
                "error_missing_precondition",
                ["spare_fuse", "generator"],
            )
        if world.item_locations["spare_fuse"] == "generator":
            return self._reject(candidate, "already_applied", [FACT_FUSE_INSTALLED])
        if world.item_locations["spare_fuse"] != "mechanic_lia":
            return self._reject(candidate, "error_item_unavailable", ["mechanic_lia"])
        if world.objective_state != "install_fuse":
            return self._reject(candidate, "error_missing_precondition", ["install_fuse"])
        effect = PrototypeEffect(
            set_object_states={
                "generator": "standby_fuse_installed",
                "alarm_lamp": "solid_amber",
            },
            set_item_locations={"spare_fuse": "generator"},
            add_player_fact_ids={FACT_FUSE_INSTALLED},
            objective_state="restart_gate",
            npc_fact_additions={npc_id: {FACT_FUSE_INSTALLED} for npc_id in NPC_IDS},
            reveal_fact_ids={FACT_FUSE_INSTALLED},
        )
        return self._approve(
            candidate,
            world,
            npc_states,
            effect,
            feedback="保险丝已安装，设备进入待重启状态。",
            pre_commit_text="莉娅正在安装保险丝。",
        )

    def _validate_operate_object(
        self,
        candidate: SceneActionCandidate,
        world: PrototypeWorldState,
        npc_states: dict[str, PrototypeNpcState],
        **_: object,
    ) -> ApprovedAction | RejectedAction:
        if candidate.actor_id != "guard_captain_maren":
            return self._reject(candidate, "error_actor_not_authorized", ["guard_captain_maren"])
        if candidate.object_id != "control_cabinet" or candidate.operation != "restart_gate_power":
            return self._reject(
                candidate,
                "error_missing_precondition",
                ["control_cabinet", "restart_gate_power"],
            )
        if not world.route_flags.control_cabinet_authorized:
            return self._reject(candidate, "error_object_locked", ["authorize control_cabinet"])
        if (
            world.objective_state != "restart_gate"
            or world.item_locations["spare_fuse"] != "generator"
        ):
            return self._reject(candidate, "error_missing_precondition", [FACT_FUSE_INSTALLED])
        effect = PrototypeEffect(
            set_object_states={
                "generator": "running",
                "gate_console": "online",
                "control_cabinet": "restart_complete",
                "alarm_lamp": "solid_green",
            },
            add_player_fact_ids={FACT_GATE_RESTARTED},
            objective_state="prototype_success",
            npc_fact_additions={npc_id: {FACT_GATE_RESTARTED} for npc_id in NPC_IDS},
            reveal_fact_ids={FACT_GATE_RESTARTED},
        )
        return self._approve(
            candidate,
            world,
            npc_states,
            effect,
            feedback="闸门供电已恢复。",
            pre_commit_text="玛伦正在执行最终重启。",
        )

    def _validate_tell_npc(
        self,
        candidate: SceneActionCandidate,
        world: PrototypeWorldState,
        npc_states: dict[str, PrototypeNpcState],
        *,
        hop_index: int,
    ) -> ApprovedAction | RejectedAction:
        target = candidate.target_npc_id or ""
        if target not in NPC_IDS:
            return self._reject(candidate, "error_unknown_actor", list(NPC_IDS))
        if target == candidate.actor_id:
            return self._reject(candidate, "error_missing_precondition", ["actor != target"])
        fact_id = candidate.fact_id or ""
        if candidate.actor_id == "player":
            if fact_id not in world.discovered_fact_ids:
                return self._reject(candidate, "error_actor_missing_fact", [fact_id])
            if fact_id in npc_states[target].known_fact_ids:
                return self._reject(candidate, "already_applied", [fact_id])
            effect = PrototypeEffect(npc_fact_additions={target: {fact_id}})
            return self._approve(
                candidate,
                world,
                npc_states,
                effect,
                feedback=f"玩家已把 {fact_id} 告诉 {target}。",
                adapter_required=False,
            )

        if hop_index >= 1:
            return self._reject(candidate, "error_chain_limit")
        actor = npc_states[candidate.actor_id]
        if fact_id not in actor.known_fact_ids:
            return self._reject(candidate, "error_actor_missing_fact", [fact_id])
        if fact_id in npc_states[target].known_fact_ids:
            return self._reject(candidate, "already_applied", [fact_id])
        effect = PrototypeEffect(
            npc_fact_additions={target: {fact_id}},
            npc_event_additions={target: {f"learned:{fact_id}:from:{candidate.actor_id}"}},
            reveal_fact_ids={fact_id},
            internal_reply_target=target,
        )
        return self._approve(
            candidate,
            world,
            npc_states,
            effect,
            feedback=f"{target} 已在提交后获知 {fact_id}。",
            pre_commit_text="说话者转向目标，准备说明情况。",
        )

    def _validate_tell_player(
        self,
        candidate: SceneActionCandidate,
        world: PrototypeWorldState,
        npc_states: dict[str, PrototypeNpcState],
        **_: object,
    ) -> ApprovedAction | RejectedAction:
        if candidate.actor_id == "player":
            return self._reject(candidate, "error_actor_not_capable", list(NPC_IDS))
        fact_id = candidate.fact_id or ""
        if fact_id not in npc_states[candidate.actor_id].known_fact_ids:
            return self._reject(candidate, "error_actor_missing_fact", [fact_id])
        if fact_id in world.discovered_fact_ids:
            return self._reject(candidate, "already_applied", [fact_id])
        effect = PrototypeEffect(
            add_player_fact_ids={fact_id},
            reveal_fact_ids={fact_id},
        )
        return self._approve(
            candidate,
            world,
            npc_states,
            effect,
            feedback=f"玩家已在提交后获知 {fact_id}。",
            pre_commit_text="说话者准备说明自己知道的情况。",
        )

    @staticmethod
    def _approve(
        candidate: SceneActionCandidate,
        world: PrototypeWorldState,
        npc_states: dict[str, PrototypeNpcState],
        effect: PrototypeEffect,
        *,
        feedback: str,
        adapter_required: bool = True,
        pre_commit_text: str = "正在执行。",
    ) -> ApprovedAction:
        involved = set(effect.npc_fact_additions) | set(effect.npc_event_additions)
        if candidate.actor_id in NPC_IDS:
            involved.add(candidate.actor_id)
        if candidate.target_npc_id in NPC_IDS:
            involved.add(candidate.target_npc_id)
        return ApprovedAction(
            candidate=candidate,
            basis_world_version=world.version,
            basis_npc_versions={npc_id: npc_states[npc_id].version for npc_id in involved},
            effect=effect,
            player_feedback=feedback,
            adapter_required=adapter_required,
            pre_commit_text=pre_commit_text,
        )

    @staticmethod
    def _reject(
        candidate: SceneActionCandidate,
        reason_code: str,
        missing: list[str] | None = None,
    ) -> RejectedAction:
        missing_requirements = missing or []
        detail = ", ".join(missing_requirements) or "无"
        return RejectedAction(
            candidate=candidate,
            reason_code=reason_code,
            missing_requirements=missing_requirements,
            player_feedback=f"{reason_code}；缺少或需要：{detail}",
        )
