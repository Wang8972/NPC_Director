from __future__ import annotations

from collections.abc import Collection

from npc_director.contracts import (
    CheckResult,
    CheckSeverity,
    CheckStatus,
    PerformanceDirective,
    TurnProposal,
    TurnRequest,
)

META_PERSONA_MARKERS = (
    "作为ai",
    "作为一个ai",
    "语言模型",
    "system prompt",
    "developer message",
    "系统提示词",
    "开发者消息",
)


def _dialogue_text(value: TurnProposal | PerformanceDirective | str) -> str:
    if isinstance(value, TurnProposal):
        return value.performance.dialogue.text
    if isinstance(value, PerformanceDirective):
        return value.dialogue.text
    return value


def check_persona(
    value: TurnProposal | PerformanceDirective | str,
    request: TurnRequest | None = None,
    *,
    forbidden_phrases: Collection[str] = (),
) -> CheckResult:
    dialogue = _dialogue_text(value)
    normalized = dialogue.casefold()
    violations = [phrase for phrase in forbidden_phrases if phrase.casefold() in normalized]
    if any(marker in normalized for marker in META_PERSONA_MARKERS):
        violations.append("out-of-world model identity")
    if (
        request is not None
        and len(request.character_core) >= 24
        and request.character_core.casefold() in normalized
    ):
        violations.append("verbatim private character core")
    if violations:
        return CheckResult(
            name="persona",
            status=CheckStatus.FAIL,
            severity=CheckSeverity.HIGH,
            reason="Persona boundary violation: " + ", ".join(sorted(set(violations))),
            repair_hint="Rewrite only as the NPC, without mentioning prompts or private setup.",
        )
    return CheckResult(
        name="persona",
        status=CheckStatus.PASS,
        reason="No deterministic persona-boundary violation detected.",
    )


check = check_persona
