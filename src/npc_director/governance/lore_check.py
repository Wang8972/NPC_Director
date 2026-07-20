from __future__ import annotations

from collections.abc import Collection

from npc_director.contracts import (
    CheckResult,
    CheckSeverity,
    CheckStatus,
    PerformanceDirective,
    TurnProposal,
)


def _content(
    value: TurnProposal | PerformanceDirective,
) -> tuple[str, set[str], bool]:
    if isinstance(value, TurnProposal):
        return (
            value.performance.dialogue.text,
            set(value.performance.evidence.lore_refs),
            bool(value.plan.lore_queries),
        )
    return value.dialogue.text, set(value.evidence.lore_refs), False


def check_lore(
    value: TurnProposal | PerformanceDirective,
    *,
    available_lore_refs: Collection[str] | None = None,
    forbidden_phrases: Collection[str] = (),
) -> CheckResult:
    dialogue, cited_refs, requested_lore = _content(value)
    normalized = dialogue.casefold()
    forbidden = sorted(phrase for phrase in forbidden_phrases if phrase.casefold() in normalized)
    if forbidden:
        return CheckResult(
            name="lore",
            status=CheckStatus.FAIL,
            severity=CheckSeverity.CRITICAL,
            reason="Dialogue discloses forbidden lore: " + ", ".join(forbidden),
        )

    if available_lore_refs is not None:
        unknown_refs = sorted(cited_refs - set(available_lore_refs))
        if unknown_refs:
            return CheckResult(
                name="lore",
                status=CheckStatus.FAIL,
                severity=CheckSeverity.HIGH,
                reason="Unknown lore references: " + ", ".join(unknown_refs),
                repair_hint="Use only retrieved lore references or remove unsupported claims.",
            )
        if requested_lore and not cited_refs:
            return CheckResult(
                name="lore",
                status=CheckStatus.FAIL,
                severity=CheckSeverity.MEDIUM,
                reason=(
                    "The plan requested lore but the performance contains no evidence reference."
                ),
                repair_hint="Ground the response in retrieved lore and include its reference.",
            )

    return CheckResult(
        name="lore",
        status=CheckStatus.PASS,
        reason="Lore references and deterministic disclosure rules are satisfied.",
    )


check = check_lore
