from __future__ import annotations

import asyncio
import inspect
from collections.abc import Awaitable, Callable, Collection, Iterable
from functools import partial

from npc_director.contracts import CheckResult, TurnProposal, TurnRequest, TurnStateRecord
from npc_director.governance.input_guard import check_input
from npc_director.governance.lore_check import check_lore
from npc_director.governance.permissions import (
    check_state_patch_permissions,
    check_tool_permissions,
)
from npc_director.governance.persona_check import check_persona
from npc_director.governance.safety_check import check_safety

CheckCallable = Callable[[], CheckResult | Awaitable[CheckResult]]


async def _execute(check: CheckCallable) -> CheckResult:
    result = await asyncio.to_thread(check)
    if inspect.isawaitable(result):
        result = await result
    if not isinstance(result, CheckResult):
        raise TypeError("Governance checks must return CheckResult")
    return result


async def run_checks(
    proposal: TurnProposal,
    request: TurnRequest | TurnStateRecord,
    *,
    state_patch_allowlist: Collection[str] = (),
    available_lore_refs: Collection[str] | None = None,
    requested_tools: Collection[str] | None = None,
    tool_allowlist: Collection[str] = (),
    persona_forbidden_phrases: Collection[str] = (),
    lore_forbidden_phrases: Collection[str] = (),
    safety_forbidden_phrases: Collection[str] = (),
    include_input_guard: bool = True,
    extra_checks: Iterable[CheckCallable] = (),
) -> list[CheckResult]:
    """Run independent deterministic checks concurrently, preserving stable order."""

    resolved_request = request.request if isinstance(request, TurnStateRecord) else request
    checks: list[CheckCallable] = []
    if include_input_guard:
        checks.append(partial(check_input, resolved_request))
    checks.append(partial(check_state_patch_permissions, proposal, state_patch_allowlist))
    if requested_tools is not None:
        checks.append(partial(check_tool_permissions, requested_tools, tool_allowlist))
    checks.extend(
        (
            partial(
                check_persona,
                proposal,
                resolved_request,
                forbidden_phrases=persona_forbidden_phrases,
            ),
            partial(
                check_lore,
                proposal,
                available_lore_refs=available_lore_refs,
                forbidden_phrases=lore_forbidden_phrases,
            ),
            partial(
                check_safety,
                proposal,
                forbidden_phrases=safety_forbidden_phrases,
            ),
        )
    )
    checks.extend(extra_checks)
    return list(await asyncio.gather(*(_execute(check) for check in checks)))


run_checks_in_parallel = run_checks
