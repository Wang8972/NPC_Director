from __future__ import annotations

import html
import re
from pathlib import Path

from npc_director.contracts import EngineEmitReceipt, PerformanceDirective
from npc_director.unity_adapter.base import build_idempotency_key


def _safe_filename(value: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_.-]+", "_", value).strip("._") or "turn"


def render_html(directive: PerformanceDirective) -> str:
    events: list[tuple[int, str, str]] = []
    events.extend(
        (cue.start_ms, "Face", f"{cue.preset} · {cue.intensity:.2f} · {cue.duration_ms} ms")
        for cue in directive.face_cues
    )
    events.extend(
        (cue.start_ms, "Body", f"{cue.action} · {cue.layer} · priority {cue.priority}")
        for cue in directive.body_cues
    )
    events.append((0, "Gaze", f"{directive.gaze.target} · {directive.gaze.mode}"))
    events.sort(key=lambda event: (event[0], event[1]))

    rows = "\n".join(
        "<tr>"
        f"<td>{start_ms}</td><td>{html.escape(kind)}</td>"
        f"<td>{html.escape(description)}</td>"
        "</tr>"
        for start_ms, kind, description in events
    )
    dialogue = html.escape(directive.dialogue.text)
    title = html.escape(f"{directive.npc_id} · {directive.turn_id}")
    emotion = html.escape(f"{directive.emotion.coarse} / {directive.emotion.primary}")
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>NPC Director Timeline</title>
  <style>
    :root {{ color-scheme: dark; font-family: Inter, system-ui, sans-serif; }}
    body {{ margin: 0; background: #10131a; color: #eef2ff; }}
    main {{ width: min(900px, calc(100% - 40px)); margin: 40px auto; }}
    .card {{ background: #191e29; border: 1px solid #2f3747; border-radius: 16px; padding: 24px; }}
    .dialogue {{ font-size: 1.35rem; line-height: 1.6; color: #f6df9b; }}
    .meta {{ color: #9ba7bd; }}
    table {{ width: 100%; border-collapse: collapse; margin-top: 24px; }}
    th, td {{ text-align: left; border-bottom: 1px solid #2f3747; padding: 12px; }}
    th {{ color: #8fd3ff; }}
  </style>
</head>
<body>
  <main>
    <section class="card">
      <h1>{title}</h1>
      <p class="meta">Emotion: {emotion} · Confidence: {directive.confidence:.2f}</p>
      <p class="dialogue">{dialogue}</p>
      <table>
        <thead><tr><th>Start (ms)</th><th>Channel</th><th>Directive</th></tr></thead>
        <tbody>{rows}</tbody>
      </table>
    </section>
  </main>
</body>
</html>
"""


class HtmlEngineAdapter:
    def __init__(self, output_directory: Path) -> None:
        self.output_directory = output_directory

    async def emit(self, directive: PerformanceDirective) -> EngineEmitReceipt:
        self.output_directory.mkdir(parents=True, exist_ok=True)
        output_path = self.output_directory / f"{_safe_filename(directive.turn_id)}.html"
        output_path.write_text(render_html(directive), encoding="utf-8")
        return EngineEmitReceipt(
            turn_id=directive.turn_id,
            idempotency_key=build_idempotency_key(directive),
            status="sent",
            detail=str(output_path),
        )
