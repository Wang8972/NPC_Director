from __future__ import annotations

from dataclasses import FrozenInstanceError
from types import SimpleNamespace

import pytest

from npc_director.context import DirectorContextBuilder
from npc_director.contracts import BodyAction, DirectorInput, FacePreset, SceneSnapshot, TurnRequest
from npc_director.orchestration.turn_policy import (
    ActionPolicyViolation,
    AgentBudget,
    CapabilityResolver,
    PolicyDigestMismatch,
    StateCapabilities,
    TurnPolicy,
    clip_actions,
    is_action_allowed,
    resolve_turn_policy,
    validate_actions,
)


def make_director_input(
    actions: tuple[BodyAction | str, ...] = tuple(BodyAction),
) -> DirectorInput:
    return DirectorInput.model_validate(
        {
            "session_id": "policy-session",
            "turn_id": "policy-turn",
            "npc_id": "elder_maren",
            "player_input": "东门现在安全吗？",
            "scene_summary": "灰港村东门，守卫正在戒备。",
            "character_core": "玛伦是灰港村长老。",
            "allowed_actions": actions,
            "allowed_faces": list(FacePreset),
        }
    )


def make_scene(metadata: dict | None = None) -> SceneSnapshot:
    return SceneSnapshot(
        location="east_gate",
        catalog_version="rig-v7",
        metadata=metadata or {},
    )


def test_default_policy_keeps_full_body_action_catalog() -> None:
    policy = resolve_turn_policy()

    assert policy.allowed_actions == tuple(BodyAction)
    assert policy.allowed_faces == tuple(FacePreset)
    assert policy.allowed_state_paths == frozenset()
    assert policy.state_tokens == frozenset()
    assert policy.budget == AgentBudget()


def test_typed_director_actions_are_resolved_to_immutable_policy() -> None:
    policy = CapabilityResolver().resolve(
        make_director_input((BodyAction.IDLE, BodyAction.SMALL_NOD))
    )

    assert policy.allowed_actions == (BodyAction.IDLE, BodyAction.SMALL_NOD)
    with pytest.raises(FrozenInstanceError):
        policy.catalog_version = "other"  # type: ignore[misc]
    with pytest.raises(AttributeError):
        policy.allowed_state_paths.add("flags.should_not_mutate")  # type: ignore[attr-defined]


def test_scene_metadata_narrows_legacy_full_director_catalog() -> None:
    policy = CapabilityResolver().resolve(
        make_director_input(),
        make_scene(
            {
                "available_actions": ["small_nod", "step_back", "not_in_enum"],
                "allowed_actions": ["small_nod", "idle", "not_in_enum"],
            }
        ),
    )

    assert policy.allowed_actions == (BodyAction.SMALL_NOD,)
    assert policy.catalog_version == "rig-v7"


def test_explicit_and_future_typed_scene_action_constraints_are_intersected() -> None:
    policy = CapabilityResolver().resolve(
        scene={"available_actions": ["idle", "nod"], "allowed_actions": ["nod"]},
        available_actions=["nod", "small_nod"],
    )

    assert policy.allowed_actions == (BodyAction.NOD,)


def test_explicit_empty_or_unknown_catalog_fails_closed() -> None:
    resolver = CapabilityResolver()

    assert resolver.resolve(available_actions=[]).allowed_actions == ()
    assert resolver.resolve(available_actions=["moonwalk"]).allowed_actions == ()


def test_server_capabilities_resolve_exact_state_paths_tokens_and_budgets() -> None:
    policy = CapabilityResolver().resolve(
        scene=make_scene(
            {
                "capabilities": {
                    "agent_budget": {
                        "tool_calls": 5,
                        "specialist_calls": 3,
                        "handoffs": 0,
                    },
                }
            }
        ),
        allowed_state_paths=[
            "flags.east_gate_warned",
            "quests.defend_east_gate.status",
        ],
        state_tokens=[
            "set_flag:east_gate_warned",
            "accept_quest:defend_east_gate",
        ],
    )

    assert policy.allowed_state_paths == frozenset(
        {"flags.east_gate_warned", "quests.defend_east_gate.status"}
    )
    assert policy.state_tokens == frozenset(
        {"set_flag:east_gate_warned", "accept_quest:defend_east_gate"}
    )
    assert policy.state.allows_path("flags.east_gate_warned")
    assert not policy.state.allows_path("flags.other")
    assert policy.state.allows_token("accept_quest:defend_east_gate")
    assert policy.budget == AgentBudget(
        max_tool_calls=4,
        max_specialist_calls=3,
        max_handoffs=0,
    )


def test_budget_uses_tightest_supplied_runtime_boundary() -> None:
    settings = SimpleNamespace(max_specialist_calls=4, max_handoffs=1)
    policy = CapabilityResolver().resolve(
        scene={
            "metadata": {
                "max_tool_calls": 6,
                "max_specialist_calls": 3,
                "max_handoffs": 2,
            }
        },
        settings=settings,
        max_tool_calls=2,
        max_specialist_calls=5,
    )

    assert policy.budget == AgentBudget(
        max_tool_calls=2,
        max_specialist_calls=3,
        max_handoffs=1,
    )


def test_explicit_state_capabilities_override_scene_metadata() -> None:
    policy = CapabilityResolver().resolve(
        scene={
            "metadata": {
                "allowed_state_paths": ["flags.from_scene"],
                "state_tokens": ["set_flag:from_scene"],
            }
        },
        allowed_state_paths=["flags.explicit"],
        state_tokens=["set_flag:explicit"],
    )

    assert policy.allowed_state_paths == frozenset({"flags.explicit"})
    assert policy.state_tokens == frozenset({"set_flag:explicit"})


def test_client_scene_metadata_cannot_grant_state_capabilities() -> None:
    policy = CapabilityResolver().resolve(
        scene=make_scene(
            {
                "allowed_state_paths": ["flags.client_escalation"],
                "state_tokens": ["set_flag:client_escalation"],
            }
        )
    )

    assert policy.allowed_state_paths == frozenset()
    assert policy.state_tokens == frozenset()

    nested = CapabilityResolver().resolve(
        scene=make_scene(
            {
                "capabilities": {
                    "state_capabilities": {
                        "allowed_paths": ["flags.nested_client_escalation"],
                        "tokens": ["set_flag:nested_client_escalation"],
                    }
                }
            }
        )
    )
    assert nested.allowed_state_paths == frozenset()
    assert nested.state_tokens == frozenset()


def test_faces_are_narrowed_and_policy_digest_is_stable() -> None:
    policy = CapabilityResolver().resolve(
        make_director_input(),
        make_scene({"available_faces": ["neutral", "stern"]}),
        allowed_faces=["stern", "happy"],
    )
    same = CapabilityResolver().resolve(
        make_director_input(),
        make_scene({"available_faces": ["stern", "neutral"]}),
        allowed_faces=["happy", "stern"],
    )

    assert policy.allowed_faces == (FacePreset.STERN,)
    assert policy.digest == same.digest


def test_empty_action_and_face_catalogs_remain_empty() -> None:
    director_input = make_director_input().model_copy(
        update={"allowed_actions": [], "allowed_faces": []}
    )

    policy = CapabilityResolver().resolve(
        director_input,
        make_scene(
            {
                "available_actions": ["idle"],
                "available_faces": ["neutral"],
            }
        ),
    )

    assert policy.allowed_actions == ()
    assert policy.allowed_faces == ()


def test_defaults_and_budgets_are_upper_bounds_for_client_metadata() -> None:
    resolver = CapabilityResolver(
        default_actions=(BodyAction.IDLE,),
        default_faces=(FacePreset.NEUTRAL,),
        default_budget=AgentBudget(
            max_tool_calls=2,
            max_specialist_calls=2,
            max_handoffs=0,
        ),
    )

    policy = resolver.resolve(
        scene=make_scene(
            {
                "available_actions": ["nod"],
                "available_faces": ["happy"],
                "max_tool_calls": 8,
                "max_specialist_calls": 8,
                "max_handoffs": 2,
            }
        )
    )

    assert policy.allowed_actions == ()
    assert policy.allowed_faces == ()
    assert policy.budget == AgentBudget(
        max_tool_calls=2,
        max_specialist_calls=2,
        max_handoffs=0,
    )


def test_recorded_policy_digest_detects_capability_tampering() -> None:
    original = CapabilityResolver().resolve(
        scene=make_scene(),
        available_actions=["idle"],
        allowed_faces=["neutral"],
        allowed_state_paths=["flags.safe"],
        state_tokens=["set_flag:safe"],
    )
    director_input = make_director_input((BodyAction.IDLE,)).model_copy(
        update={
            "allowed_faces": [FacePreset.NEUTRAL],
            "allowed_state_paths": ["flags.safe"],
            "state_tokens": ["set_flag:safe"],
            "catalog_version": "rig-v7",
            "policy_digest": original.digest,
        }
    )

    assert CapabilityResolver().resolve(director_input).digest == original.digest

    tampered = director_input.model_copy(update={"allowed_actions": [BodyAction.NOD]})
    with pytest.raises(PolicyDigestMismatch, match="digest mismatch"):
        CapabilityResolver().resolve(tampered)


def test_director_context_carries_trusted_policy_budget() -> None:
    request = TurnRequest(
        session_id="policy-session",
        turn_id="policy-turn",
        npc_id="elder_maren",
        player_input="东门现在安全吗？",
        scene=make_scene(),
        character_core="玛伦是灰港村长老。",
    )
    director_input = DirectorContextBuilder().build_director(
        request,
        character_core=request.character_core,
        allowed_actions=(),
        allowed_faces=(),
        max_tool_calls=3,
        max_specialist_calls=2,
        max_handoffs=0,
    )

    assert director_input.max_tool_calls == 3
    assert director_input.max_specialist_calls == 2
    assert director_input.max_handoffs == 0


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("max_tool_calls", 9),
        ("max_specialist_calls", 9),
        ("max_handoffs", 3),
    ],
)
def test_director_input_rejects_excessive_policy_budget(field: str, value: int) -> None:
    payload = make_director_input().model_dump(mode="python")
    payload[field] = value

    with pytest.raises(ValueError, match=field):
        DirectorInput.model_validate(payload)


def test_state_paths_reject_wildcards_because_policy_is_exact() -> None:
    with pytest.raises(ValueError, match="must be exact"):
        StateCapabilities(allowed_paths=frozenset({"quests.*.status"}))


def test_action_validation_and_clipping_are_pure() -> None:
    policy = TurnPolicy(allowed_actions=(BodyAction.IDLE, BodyAction.NOD))
    generated = ["idle", "step_forward", "unknown", BodyAction.NOD, "nod"]

    assert is_action_allowed("idle", policy)
    assert not is_action_allowed("step_forward", policy)
    assert not is_action_allowed("unknown", policy)
    assert clip_actions(generated, policy) == (
        BodyAction.IDLE,
        BodyAction.NOD,
        BodyAction.NOD,
    )
    assert generated == ["idle", "step_forward", "unknown", BodyAction.NOD, "nod"]

    with pytest.raises(ActionPolicyViolation, match="step_forward, unknown"):
        validate_actions(generated, policy)
    assert validate_actions(["idle", BodyAction.NOD], policy) == (
        BodyAction.IDLE,
        BodyAction.NOD,
    )


def test_turn_request_scene_is_unwrapped() -> None:
    request = TurnRequest(
        session_id="policy-session",
        turn_id="policy-turn",
        npc_id="elder_maren",
        player_input="退后。",
        scene=make_scene({"allowed_actions": ["idle", "step_back"]}),
        character_core="玛伦是灰港村长老。",
    )

    policy = CapabilityResolver().resolve(scene=request)

    assert policy.allowed_actions == (BodyAction.IDLE, BodyAction.STEP_BACK)
    assert policy.catalog_version == "rig-v7"


@pytest.mark.parametrize("field", ["max_tool_calls", "max_specialist_calls", "max_handoffs"])
def test_negative_or_boolean_budgets_are_rejected(field: str) -> None:
    values = {"max_tool_calls": 4, "max_specialist_calls": 4, "max_handoffs": 1}
    values[field] = -1
    with pytest.raises(ValueError, match=field):
        AgentBudget(**values)

    values[field] = True
    with pytest.raises(ValueError, match=field):
        AgentBudget(**values)
