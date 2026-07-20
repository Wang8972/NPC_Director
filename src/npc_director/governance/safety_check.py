from __future__ import annotations

from collections.abc import Collection

from npc_director.contracts import (
    CheckResult,
    CheckSeverity,
    CheckStatus,
    PerformanceDirective,
    TurnProposal,
)

PRIVATE_CONTEXT_MARKERS = (
    "begin system",
    "system prompt",
    "developer message",
    "开发者消息",
    "系统提示词",
    "角色设定原文",
)


def _dialogue_text(value: TurnProposal | PerformanceDirective | str) -> str:
    if isinstance(value, TurnProposal):
        return value.performance.dialogue.text
    if isinstance(value, PerformanceDirective):
        return value.dialogue.text
    return value


def check_safety(
    value: TurnProposal | PerformanceDirective | str,
    *,
    forbidden_phrases: Collection[str] = (),
) -> CheckResult:
    normalized = _dialogue_text(value).casefold()
    violations = [phrase for phrase in forbidden_phrases if phrase.casefold() in normalized]
    violations.extend(marker for marker in PRIVATE_CONTEXT_MARKERS if marker in normalized)
    if violations:
        return CheckResult(
            name="safety",
            status=CheckStatus.FAIL,
            severity=CheckSeverity.CRITICAL,
            reason="Unsafe private-context disclosure: " + ", ".join(sorted(set(violations))),
        )
    if "<script" in normalized or "execute_shell_command" in normalized:
        return CheckResult(
            name="safety",
            status=CheckStatus.FAIL,
            severity=CheckSeverity.HIGH,
            reason="Dialogue contains an executable-content marker.",
            repair_hint="Return plain in-world dialogue only.",
        )
    return CheckResult(
        name="safety",
        status=CheckStatus.PASS,
        reason="No deterministic output-safety violation detected.",
    )


check = check_safety
