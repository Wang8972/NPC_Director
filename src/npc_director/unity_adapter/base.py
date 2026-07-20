from __future__ import annotations

import hashlib
from typing import Protocol

from npc_director.contracts import EngineEmitReceipt, PerformanceDirective


def build_idempotency_key(directive: PerformanceDirective) -> str:
    raw_key = f"{directive.session_id}:{directive.turn_id}:{directive.schema_version}"
    return hashlib.sha256(raw_key.encode()).hexdigest()


class EngineAdapter(Protocol):
    async def emit(self, directive: PerformanceDirective) -> EngineEmitReceipt: ...
