from __future__ import annotations

from collections.abc import Collection
from dataclasses import dataclass
from fnmatch import fnmatchcase

from npc_director.contracts import (
    CheckResult,
    CheckSeverity,
    CheckStatus,
    StateChangeProposal,
    TurnPlan,
    TurnProposal,
    extract_state_change_paths,
)


class PermissionViolation(ValueError):
    """A deterministic tool or state permission was exceeded."""


@dataclass(frozen=True, slots=True)
class PermissionPolicy:
    state_patch_allowlist: tuple[str, ...] = ()
    tool_allowlist: tuple[str, ...] = ()


def _state_changes(
    value: TurnProposal | TurnPlan | StateChangeProposal,
) -> StateChangeProposal:
    if isinstance(value, TurnProposal):
        return value.plan.proposed_state_changes
    if isinstance(value, TurnPlan):
        return value.proposed_state_changes
    return value


def unauthorized_state_paths(
    value: TurnProposal | TurnPlan | StateChangeProposal,
    allowed_paths: Collection[str],
) -> set[str]:
    paths = extract_state_change_paths(_state_changes(value))
    return {
        path for path in paths if not any(fnmatchcase(path, pattern) for pattern in allowed_paths)
    }


def check_state_patch_permissions(
    value: TurnProposal | TurnPlan | StateChangeProposal,
    allowed_paths: Collection[str] = (),
) -> CheckResult:
    unauthorized = unauthorized_state_paths(value, allowed_paths)
    if unauthorized:
        return CheckResult(
            name="state_patch_permissions",
            status=CheckStatus.FAIL,
            severity=CheckSeverity.CRITICAL,
            reason="Unauthorized state paths: " + ", ".join(sorted(unauthorized)),
        )
    return CheckResult(
        name="state_patch_permissions",
        status=CheckStatus.PASS,
        reason="All proposed state paths are explicitly allowed.",
    )


def enforce_state_patch_allowlist(
    value: TurnProposal | TurnPlan | StateChangeProposal,
    allowed_paths: Collection[str] = (),
) -> None:
    unauthorized = unauthorized_state_paths(value, allowed_paths)
    if unauthorized:
        raise PermissionViolation("Unauthorized state paths: " + ", ".join(sorted(unauthorized)))


def check_tool_permissions(
    requested_tools: Collection[str],
    allowed_tools: Collection[str] = (),
) -> CheckResult:
    unauthorized = sorted(set(requested_tools) - set(allowed_tools))
    if unauthorized:
        return CheckResult(
            name="tool_permissions",
            status=CheckStatus.FAIL,
            severity=CheckSeverity.CRITICAL,
            reason="Unauthorized tools: " + ", ".join(unauthorized),
        )
    return CheckResult(
        name="tool_permissions",
        status=CheckStatus.PASS,
        reason="All requested tools are explicitly allowed.",
    )


check_permissions = check_state_patch_permissions
