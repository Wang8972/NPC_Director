from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from hashlib import sha256
from typing import Any

from npc_director.contracts import (
    BodyAction,
    DirectorInput,
    FacePreset,
    SceneSnapshot,
    TurnRequest,
)

__all__ = [
    "ActionPolicyViolation",
    "AgentBudget",
    "CapabilityResolver",
    "PolicyDigestMismatch",
    "StateCapabilities",
    "TurnPolicy",
    "clip_actions",
    "is_action_allowed",
    "resolve_turn_policy",
    "validate_actions",
]


ALL_BODY_ACTIONS = tuple(BodyAction)
ALL_FACE_PRESETS = tuple(FacePreset)
_MISSING = object()
_GLOB_CHARACTERS = frozenset("*?[")


class ActionPolicyViolation(ValueError):
    """Raised when a generated body action is outside the trusted turn policy."""


class PolicyDigestMismatch(ValueError):
    """Raised when trusted capabilities no longer match their recorded digest."""


@dataclass(frozen=True, slots=True)
class AgentBudget:
    """Deterministic limits for one turn's dynamic main/sub-agent execution."""

    max_tool_calls: int = 4
    max_specialist_calls: int = 4
    max_handoffs: int = 1

    def __post_init__(self) -> None:
        for name in ("max_tool_calls", "max_specialist_calls", "max_handoffs"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ValueError(f"{name} must be a non-negative integer")


@dataclass(frozen=True, slots=True)
class StateCapabilities:
    """Exact state paths and opaque capability tokens granted for a turn.

    Paths are deliberately exact: wildcard permission patterns belong at the
    governance boundary, while an agent should receive only concrete operations
    it can propose for the current NPC and scene.
    """

    allowed_paths: frozenset[str] = field(default_factory=frozenset)
    tokens: frozenset[str] = field(default_factory=frozenset)

    def __post_init__(self) -> None:
        paths = _normalize_names(self.allowed_paths, label="state path")
        wildcard_paths = sorted(path for path in paths if _contains_glob(path))
        if wildcard_paths:
            rendered = ", ".join(wildcard_paths)
            raise ValueError(f"state paths must be exact, got wildcard paths: {rendered}")
        object.__setattr__(self, "allowed_paths", paths)
        object.__setattr__(
            self,
            "tokens",
            _normalize_names(self.tokens, label="state capability token"),
        )

    def allows_path(self, path: str) -> bool:
        return path in self.allowed_paths

    def allows_token(self, token: str) -> bool:
        return token in self.tokens


@dataclass(frozen=True, slots=True)
class TurnPolicy:
    """Immutable, trusted capabilities resolved before model orchestration."""

    allowed_actions: tuple[BodyAction, ...] = ALL_BODY_ACTIONS
    allowed_faces: tuple[FacePreset, ...] = ALL_FACE_PRESETS
    state: StateCapabilities = field(default_factory=StateCapabilities)
    budget: AgentBudget = field(default_factory=AgentBudget)
    catalog_version: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "allowed_actions", _normalize_actions(self.allowed_actions))
        object.__setattr__(self, "allowed_faces", _normalize_faces(self.allowed_faces))
        if self.catalog_version is not None:
            catalog_version = self.catalog_version.strip()
            object.__setattr__(self, "catalog_version", catalog_version or None)

    @property
    def allowed_state_paths(self) -> frozenset[str]:
        return self.state.allowed_paths

    @property
    def state_tokens(self) -> frozenset[str]:
        return self.state.tokens

    def allows_action(self, action: BodyAction | str) -> bool:
        return is_action_allowed(action, self)

    @property
    def digest(self) -> str:
        payload = {
            "actions": [item.value for item in self.allowed_actions],
            "faces": [item.value for item in self.allowed_faces],
            "state_paths": sorted(self.allowed_state_paths),
            "state_tokens": sorted(self.state_tokens),
            "budget": {
                "tools": self.budget.max_tool_calls,
                "specialists": self.budget.max_specialist_calls,
                "handoffs": self.budget.max_handoffs,
            },
            "catalog_version": self.catalog_version,
        }
        canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        return sha256(canonical.encode()).hexdigest()


class CapabilityResolver:
    """Resolve per-turn capabilities from typed inputs and scene metadata.

    Every supplied action source is treated as a boundary, so the effective
    catalog is their intersection. This lets an engine-side scene catalog narrow
    a legacy ``DirectorInput`` that still contains all ``BodyAction`` values.
    If no source exists, all enum actions remain available for compatibility.
    """

    def __init__(
        self,
        *,
        default_actions: Iterable[BodyAction | str] = ALL_BODY_ACTIONS,
        default_faces: Iterable[FacePreset | str] = ALL_FACE_PRESETS,
        default_state_paths: Iterable[str] = (),
        default_state_tokens: Iterable[str] = (),
        default_budget: AgentBudget | None = None,
    ) -> None:
        self._default_actions = _normalize_actions(default_actions)
        self._default_faces = _normalize_faces(default_faces)
        self._default_state = StateCapabilities(
            allowed_paths=frozenset(default_state_paths),
            tokens=frozenset(default_state_tokens),
        )
        self._default_budget = default_budget or AgentBudget()

    def resolve(
        self,
        director_input: DirectorInput | Mapping[str, Any] | None = None,
        scene: SceneSnapshot | TurnRequest | Mapping[str, Any] | None = None,
        *,
        available_actions: Iterable[BodyAction | str] | BodyAction | str | None = None,
        allowed_actions: Iterable[BodyAction | str] | BodyAction | str | None = None,
        available_faces: Iterable[FacePreset | str] | FacePreset | str | None = None,
        allowed_faces: Iterable[FacePreset | str] | FacePreset | str | None = None,
        allowed_state_paths: Iterable[str] | str | None = None,
        state_tokens: Iterable[str] | str | None = None,
        settings: object | Mapping[str, Any] | None = None,
        max_tool_calls: int | None = None,
        max_specialist_calls: int | None = None,
        max_handoffs: int | None = None,
    ) -> TurnPolicy:
        scene_value = _unwrap_scene(scene)
        metadata = _scene_metadata(scene_value)

        # Defaults are a server-owned upper bound. Explicit/typed/client
        # catalogs may narrow them, but can never introduce a capability that
        # the resolver itself does not know or grant.
        action_sources: list[tuple[BodyAction, ...]] = [self._default_actions]
        _append_action_source(action_sources, available_actions)
        _append_action_source(action_sources, allowed_actions)
        _append_named_action_sources(action_sources, scene_value)
        _append_named_action_sources(action_sources, metadata)
        _append_named_action_sources(action_sources, director_input)

        permitted = set(action_sources[0])
        for source in action_sources[1:]:
            permitted.intersection_update(source)
        resolved_actions = tuple(action for action in BodyAction if action in permitted)

        face_sources: list[tuple[FacePreset, ...]] = [self._default_faces]
        _append_face_source(face_sources, available_faces)
        _append_face_source(face_sources, allowed_faces)
        _append_named_face_sources(face_sources, scene_value)
        _append_named_face_sources(face_sources, metadata)
        _append_named_face_sources(face_sources, director_input)
        permitted_faces = set(face_sources[0])
        for source in face_sources[1:]:
            permitted_faces.intersection_update(source)
        resolved_faces = tuple(face for face in FacePreset if face in permitted_faces)

        # SceneSnapshot is supplied by the client/engine. It may safely narrow
        # actions and budgets, but it must never grant state authority.
        resolved_paths = _first_present(
            allowed_state_paths,
            _read_first(director_input, "allowed_state_paths", "state_paths"),
        )
        resolved_tokens = _first_present(
            state_tokens,
            _read_first(director_input, "state_tokens", "state_capability_tokens"),
        )
        state = StateCapabilities(
            allowed_paths=(
                self._default_state.allowed_paths
                if resolved_paths is _MISSING
                else _normalize_names(resolved_paths, label="state path")
            ),
            tokens=(
                self._default_state.tokens
                if resolved_tokens is _MISSING
                else _normalize_names(resolved_tokens, label="state capability token")
            ),
        )

        budget_metadata = _nested_mapping(metadata, "agent_budget", "budgets", "budget")
        budget = AgentBudget(
            max_tool_calls=_resolve_budget(
                explicit=max_tool_calls,
                settings=settings,
                setting_names=("max_tool_calls",),
                metadata=metadata,
                metadata_names=("max_tool_calls", "tool_call_budget", "tool_budget"),
                nested=budget_metadata,
                nested_names=("max_tool_calls", "tool_calls", "tools"),
                fallback=self._default_budget.max_tool_calls,
            ),
            max_specialist_calls=_resolve_budget(
                explicit=max_specialist_calls,
                settings=settings,
                setting_names=("max_specialist_calls",),
                metadata=metadata,
                metadata_names=(
                    "max_specialist_calls",
                    "specialist_call_budget",
                    "specialist_budget",
                ),
                nested=budget_metadata,
                nested_names=("max_specialist_calls", "specialist_calls", "specialists"),
                fallback=self._default_budget.max_specialist_calls,
            ),
            max_handoffs=_resolve_budget(
                explicit=max_handoffs,
                settings=settings,
                setting_names=("max_handoffs",),
                metadata=metadata,
                metadata_names=("max_handoffs", "handoff_budget"),
                nested=budget_metadata,
                nested_names=("max_handoffs", "handoffs"),
                fallback=self._default_budget.max_handoffs,
            ),
        )
        catalog_version = _first_present(
            _read_first(scene_value, "catalog_version"),
            _read_first(metadata, "catalog_version"),
            _read_first(director_input, "catalog_version"),
        )
        policy = TurnPolicy(
            allowed_actions=resolved_actions,
            allowed_faces=resolved_faces,
            state=state,
            budget=budget,
            catalog_version=None if catalog_version is _MISSING else str(catalog_version),
        )
        recorded_digest = _read_first(director_input, "policy_digest")
        if (
            recorded_digest is not _MISSING
            and recorded_digest is not None
            and recorded_digest != policy.digest
        ):
            raise PolicyDigestMismatch(
                f"turn policy digest mismatch: expected {recorded_digest}, got {policy.digest}"
            )
        return policy


def resolve_turn_policy(
    director_input: DirectorInput | Mapping[str, Any] | None = None,
    scene: SceneSnapshot | TurnRequest | Mapping[str, Any] | None = None,
    **kwargs: Any,
) -> TurnPolicy:
    """Convenience wrapper around the default ``CapabilityResolver``."""

    return CapabilityResolver().resolve(director_input, scene, **kwargs)


def is_action_allowed(
    action: BodyAction | str,
    policy_or_actions: TurnPolicy | Iterable[BodyAction | str],
) -> bool:
    """Return whether one action is both known and granted by the policy."""

    candidate = _coerce_action(action)
    if candidate is None:
        return False
    return candidate in _policy_actions(policy_or_actions)


def validate_actions(
    actions: Iterable[BodyAction | str],
    policy_or_actions: TurnPolicy | Iterable[BodyAction | str],
) -> tuple[BodyAction, ...]:
    """Validate actions and return their typed representation without mutation."""

    allowed = frozenset(_policy_actions(policy_or_actions))
    validated: list[BodyAction] = []
    rejected: list[str] = []
    for raw_action in actions:
        action = _coerce_action(raw_action)
        if action is None or action not in allowed:
            rejected.append(str(raw_action))
        else:
            validated.append(action)
    if rejected:
        raise ActionPolicyViolation("actions are not allowed: " + ", ".join(rejected))
    return tuple(validated)


def clip_actions(
    actions: Iterable[BodyAction | str],
    policy_or_actions: TurnPolicy | Iterable[BodyAction | str],
) -> tuple[BodyAction, ...]:
    """Purely drop unknown or disallowed actions, preserving order and duplicates."""

    allowed = frozenset(_policy_actions(policy_or_actions))
    clipped: list[BodyAction] = []
    for raw_action in actions:
        action = _coerce_action(raw_action)
        if action is not None and action in allowed:
            clipped.append(action)
    return tuple(clipped)


def _normalize_actions(
    values: Iterable[BodyAction | str] | BodyAction | str,
) -> tuple[BodyAction, ...]:
    if isinstance(values, (str, BodyAction)):
        values = (values,)
    resolved = {_coerce_action(value) for value in values}
    resolved.discard(None)
    return tuple(action for action in BodyAction if action in resolved)


def _coerce_action(value: BodyAction | str) -> BodyAction | None:
    if isinstance(value, BodyAction):
        return value
    try:
        return BodyAction(value)
    except (TypeError, ValueError):
        return None


def _normalize_faces(
    values: Iterable[FacePreset | str] | FacePreset | str,
) -> tuple[FacePreset, ...]:
    if isinstance(values, (str, FacePreset)):
        values = (values,)
    resolved = {_coerce_face(value) for value in values}
    resolved.discard(None)
    return tuple(face for face in FacePreset if face in resolved)


def _coerce_face(value: FacePreset | str) -> FacePreset | None:
    if isinstance(value, FacePreset):
        return value
    try:
        return FacePreset(value)
    except (TypeError, ValueError):
        return None


def _policy_actions(
    policy_or_actions: TurnPolicy | Iterable[BodyAction | str],
) -> tuple[BodyAction, ...]:
    if isinstance(policy_or_actions, TurnPolicy):
        return policy_or_actions.allowed_actions
    return _normalize_actions(policy_or_actions)


def _append_action_source(
    sources: list[tuple[BodyAction, ...]],
    value: object,
) -> None:
    if value is not None and value is not _MISSING:
        sources.append(_normalize_actions(value))  # type: ignore[arg-type]


def _append_named_action_sources(
    sources: list[tuple[BodyAction, ...]],
    value: object,
) -> None:
    if value is None or value is _MISSING:
        return
    for name in ("available_actions", "allowed_actions"):
        candidate = _read(value, name)
        if candidate is not _MISSING and candidate is not None:
            _append_action_source(sources, candidate)


def _append_face_source(
    sources: list[tuple[FacePreset, ...]],
    value: object,
) -> None:
    if value is not None and value is not _MISSING:
        sources.append(_normalize_faces(value))  # type: ignore[arg-type]


def _append_named_face_sources(
    sources: list[tuple[FacePreset, ...]],
    value: object,
) -> None:
    if value is None or value is _MISSING:
        return
    for name in ("available_faces", "allowed_faces"):
        candidate = _read(value, name)
        if candidate is not _MISSING and candidate is not None:
            _append_face_source(sources, candidate)


def _unwrap_scene(value: object) -> object:
    if value is None:
        return None
    nested = _read(value, "scene")
    return value if nested is _MISSING else nested


def _scene_metadata(scene: object) -> Mapping[str, Any]:
    metadata = _read(scene, "metadata")
    if metadata is _MISSING or metadata is None:
        return {}
    if not isinstance(metadata, Mapping):
        raise ValueError("scene metadata must be a mapping")
    capabilities = _nested_mapping(metadata, "capabilities", "turn_policy")
    if not capabilities:
        return metadata
    return {**metadata, **capabilities}


def _nested_mapping(value: object, *names: str) -> Mapping[str, Any]:
    candidate = _read_first(value, *names)
    if candidate is _MISSING or candidate is None:
        return {}
    if not isinstance(candidate, Mapping):
        raise ValueError(f"{names[0]} must be a mapping")
    return candidate


def _read(value: object, name: str) -> object:
    if value is None or value is _MISSING:
        return _MISSING
    if isinstance(value, Mapping):
        return value.get(name, _MISSING)
    return getattr(value, name, _MISSING)


def _read_first(value: object, *names: str) -> object:
    for name in names:
        candidate = _read(value, name)
        if candidate is not _MISSING:
            return candidate
    return _MISSING


def _first_present(*values: object) -> object:
    return next(
        (value for value in values if value is not _MISSING and value is not None),
        _MISSING,
    )


def _resolve_budget(
    *,
    explicit: int | None,
    settings: object,
    setting_names: tuple[str, ...],
    metadata: Mapping[str, Any],
    metadata_names: tuple[str, ...],
    nested: Mapping[str, Any],
    nested_names: tuple[str, ...],
    fallback: int,
) -> int:
    trusted_candidates = (
        explicit,
        _read_first(settings, *setting_names),
    )
    trusted = [
        candidate
        for candidate in trusted_candidates
        if candidate is not _MISSING and candidate is not None
    ]
    trusted_limit = min(_validated_budgets(trusted, setting_names[0])) if trusted else fallback

    # Scene metadata crosses the client boundary. It can request a smaller
    # budget (for example because a platform is under load), never a larger one.
    untrusted = [
        candidate
        for candidate in (
            _read_first(metadata, *metadata_names),
            _read_first(nested, *nested_names),
        )
        if candidate is not _MISSING and candidate is not None
    ]
    return min([trusted_limit, *_validated_budgets(untrusted, setting_names[0])])


def _validated_budgets(values: Iterable[object], label: str) -> list[int]:
    validated: list[int] = []
    for value in values:
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise ValueError(f"{label} must be a non-negative integer")
        validated.append(value)
    return validated


def _normalize_names(values: object, *, label: str) -> frozenset[str]:
    if isinstance(values, str):
        values = (values,)
    if not isinstance(values, Iterable):
        raise ValueError(f"{label}s must be an iterable of strings")
    normalized: set[str] = set()
    for value in values:
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"{label}s must contain only non-empty strings")
        normalized.add(value.strip())
    return frozenset(normalized)


def _contains_glob(value: str) -> bool:
    return any(character in value for character in _GLOB_CHARACTERS)
