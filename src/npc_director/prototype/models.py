from __future__ import annotations

import hashlib
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

SCENE_ID = "prototype_gate_repair"
PLAYER_ID = "player"
NPC_IDS = (
    "guard_captain_maren",
    "mechanic_lia",
    "porter_finn",
)
ACTOR_IDS = (PLAYER_ID, *NPC_IDS)
OBJECT_IDS = (
    "gate_console",
    "generator",
    "control_cabinet",
    "cargo_crate_c12",
    "manifest_board",
    "alarm_lamp",
)
ITEM_IDS = ("spare_fuse",)
ACTION_TYPES = (
    "inspect_object",
    "authorize_object",
    "give_item",
    "install_item",
    "operate_object",
    "tell_npc",
    "tell_player",
)

FACT_RESTART_REQUIRES_AUTHORITY = "fact_restart_requires_authority"
FACT_CONSOLE_E17 = "fact_console_e17"
FACT_GENERATOR_MISSING_FUSE = "fact_generator_missing_fuse"
FACT_MANIFEST_FINN_MOVED_C12 = "fact_manifest_finn_moved_c12"
FACT_FUSE_MOVED_TO_C12 = "fact_fuse_moved_to_c12"
FACT_CRATE_SEAL_ANOMALY = "fact_crate_c12_seal_anomaly"
FACT_CRATE_CONTAINS_FUSE = "fact_crate_c12_contains_fuse"
FACT_FUSE_INSTALLED = "fact_fuse_installed"
FACT_GATE_RESTARTED = "fact_gate_restarted"
FACT_FUSE_MATCHES_GENERATOR = "fact_fuse_matches_generator"
FACT_FINN_UNAUTHORIZED_MOVE = "fact_finn_unauthorized_move"


class PrototypeModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class RouteFlags(PrototypeModel):
    fuse_route: Literal["none", "cooperation", "procedure"] = "none"
    crate_c12_authorized: bool = False
    control_cabinet_authorized: bool = False


class PendingActionSummary(PrototypeModel):
    action_id: str
    actor_id: str
    action_type: str
    basis_world_version: int = Field(ge=0)


class PrototypeWorldState(PrototypeModel):
    session_id: str
    current_scene_id: str = SCENE_ID
    version: int = Field(default=0, ge=0)
    objective_state: Literal[
        "investigate_fault",
        "find_fuse",
        "install_fuse",
        "restart_gate",
        "prototype_success",
    ] = "investigate_fault"
    object_states: dict[str, str] = Field(
        default_factory=lambda: {
            "gate_console": "offline_e17",
            "generator": "stopped_fuse_slot_empty",
            "control_cabinet": "locked",
            "cargo_crate_c12": "sealed_anomaly",
            "manifest_board": "readable",
            "alarm_lamp": "flashing_red",
        }
    )
    item_locations: dict[str, str] = Field(
        default_factory=lambda: {"spare_fuse": "cargo_crate_c12"}
    )
    discovered_fact_ids: set[str] = Field(
        default_factory=lambda: {FACT_RESTART_REQUIRES_AUTHORITY}
    )
    route_flags: RouteFlags = Field(default_factory=RouteFlags)
    pending_action: PendingActionSummary | None = None
    ending_id: str | None = None


class PrototypeNpcState(PrototypeModel):
    session_id: str
    npc_id: str
    known_fact_ids: set[str] = Field(default_factory=set)
    observed_event_ids: set[str] = Field(default_factory=set)
    private_flags: set[str] = Field(default_factory=set)
    version: int = Field(default=0, ge=0)


class SceneActionCandidate(PrototypeModel):
    session_id: str
    turn_id: str
    action_id: str
    actor_id: str
    action_type: str
    object_id: str | None = None
    item_id: str | None = None
    target_id: str | None = None
    target_npc_id: str | None = None
    fact_id: str | None = None
    operation: str | None = None
    gameplay_intent: Literal["cooperation_offer", "request_authorization"] | None = None


class PrototypeEffect(PrototypeModel):
    set_object_states: dict[str, str] = Field(default_factory=dict)
    set_item_locations: dict[str, str] = Field(default_factory=dict)
    add_player_fact_ids: set[str] = Field(default_factory=set)
    set_route_flags: dict[str, bool | str] = Field(default_factory=dict)
    objective_state: str | None = None
    npc_fact_additions: dict[str, set[str]] = Field(default_factory=dict)
    npc_event_additions: dict[str, set[str]] = Field(default_factory=dict)
    reveal_fact_ids: set[str] = Field(default_factory=set)
    internal_reply_target: str | None = None

    def changes_world(self) -> bool:
        return bool(
            self.set_object_states
            or self.set_item_locations
            or self.add_player_fact_ids
            or self.set_route_flags
            or self.objective_state is not None
        )


class ApprovedAction(PrototypeModel):
    candidate: SceneActionCandidate
    basis_world_version: int = Field(ge=0)
    basis_npc_versions: dict[str, int] = Field(default_factory=dict)
    effect: PrototypeEffect
    player_feedback: str
    adapter_required: bool = True
    pre_commit_text: str = "正在执行。"


class RejectedAction(PrototypeModel):
    candidate: SceneActionCandidate
    reason_code: str
    missing_requirements: list[str] = Field(default_factory=list)
    player_feedback: str


class PendingActionRecord(PrototypeModel):
    approved: ApprovedAction
    idempotency_key: str
    status: Literal["ready", "ack", "started", "completed", "interrupted", "error"] = (
        "ready"
    )


class ActionCommitResult(PrototypeModel):
    action_id: str
    idempotency_key: str
    world: PrototypeWorldState
    npc_states: dict[str, PrototypeNpcState]
    reveal_fact_ids: set[str] = Field(default_factory=set)
    applied: bool


class ActionPlan(PrototypeModel):
    action_id: str
    session_id: str
    turn_id: str
    actor_id: str
    action_type: str
    idempotency_key: str
    pre_commit_text: str


class InternalReplyPlan(PrototypeModel):
    source_action_id: str
    session_id: str
    target_npc_id: str
    hop_index: Literal[1] = 1
    text: str


class SubmissionResult(PrototypeModel):
    approved: bool
    rejection: RejectedAction | None = None
    commit: ActionCommitResult | None = None
    idempotency_key: str | None = None


def initial_npc_state(session_id: str, npc_id: str) -> PrototypeNpcState:
    facts = {FACT_RESTART_REQUIRES_AUTHORITY}
    private_flags: set[str] = set()
    if npc_id == "mechanic_lia":
        facts.add(FACT_FUSE_MATCHES_GENERATOR)
    elif npc_id == "porter_finn":
        facts.update(
            {
                FACT_FUSE_MOVED_TO_C12,
                FACT_CRATE_CONTAINS_FUSE,
                FACT_FINN_UNAUTHORIZED_MOVE,
            }
        )
        private_flags.add("concerned_about_accountability")
    return PrototypeNpcState(
        session_id=session_id,
        npc_id=npc_id,
        known_fact_ids=facts,
        private_flags=private_flags,
    )


def build_action_idempotency_key(candidate: SceneActionCandidate) -> str:
    raw = f"{candidate.session_id}:{candidate.action_id}:1.0"
    return hashlib.sha256(raw.encode()).hexdigest()


def semantic_state_payload(
    world: PrototypeWorldState,
    npc_states: dict[str, PrototypeNpcState],
) -> dict[str, Any]:
    return {
        "current_scene_id": world.current_scene_id,
        "objective_state": world.objective_state,
        "object_states": dict(sorted(world.object_states.items())),
        "item_locations": dict(sorted(world.item_locations.items())),
        "discovered_fact_ids": sorted(world.discovered_fact_ids),
        "route_flags": world.route_flags.model_dump(mode="json"),
        "pending_action": None
        if world.pending_action is None
        else world.pending_action.model_dump(mode="json"),
        "ending_id": world.ending_id,
        "npc_states": {
            npc_id: {
                "known_fact_ids": sorted(state.known_fact_ids),
                "observed_event_ids": sorted(state.observed_event_ids),
                "private_flags": sorted(state.private_flags),
            }
            for npc_id, state in sorted(npc_states.items())
        },
    }


def normalized_success_projection(world: PrototypeWorldState) -> dict[str, Any]:
    return {
        "current_scene_id": world.current_scene_id,
        "objective_state": world.objective_state,
        "object_states": {
            object_id: world.object_states[object_id]
            for object_id in (
                "generator",
                "gate_console",
                "control_cabinet",
                "alarm_lamp",
            )
        },
        "spare_fuse_location": world.item_locations["spare_fuse"],
        "success_fact_ids": sorted(
            {FACT_FUSE_INSTALLED, FACT_GATE_RESTARTED} & world.discovered_fact_ids
        ),
        "pending_action": None
        if world.pending_action is None
        else world.pending_action.model_dump(mode="json"),
        "ending_id": world.ending_id,
    }
