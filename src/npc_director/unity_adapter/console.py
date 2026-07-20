from __future__ import annotations

from collections.abc import Callable

from npc_director.contracts import EngineEmitReceipt, PerformanceDirective
from npc_director.unity_adapter.base import build_idempotency_key


def render_timeline(directive: PerformanceDirective) -> str:
    events: list[tuple[int, str]] = [(0, f"dialogue: {directive.dialogue.text}")]
    events.extend(
        (
            cue.start_ms,
            f"face: {cue.preset} intensity={cue.intensity:.2f} duration={cue.duration_ms}ms",
        )
        for cue in directive.face_cues
    )
    events.extend(
        (
            cue.start_ms,
            f"body: {cue.action} layer={cue.layer} priority={cue.priority}",
        )
        for cue in directive.body_cues
    )
    events.append((0, f"gaze: {directive.gaze.target} mode={directive.gaze.mode}"))
    events.sort(key=lambda event: (event[0], event[1]))

    header = (
        f"NPC Director turn={directive.turn_id} npc={directive.npc_id} "
        f"emotion={directive.emotion.coarse}/{directive.emotion.primary}"
    )
    lines = [header, "-" * len(header)]
    lines.extend(f"{start_ms:>6}ms | {description}" for start_ms, description in events)
    return "\n".join(lines)


class ConsoleEngineAdapter:
    def __init__(self, writer: Callable[[str], None] = print) -> None:
        self._writer = writer

    async def emit(self, directive: PerformanceDirective) -> EngineEmitReceipt:
        self._writer(render_timeline(directive))
        return EngineEmitReceipt(
            turn_id=directive.turn_id,
            idempotency_key=build_idempotency_key(directive),
            status="sent",
        )
