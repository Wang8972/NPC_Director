from __future__ import annotations

import json
from pathlib import Path

import pytest

from npc_director.contracts import BodyAction, FacePreset, PerformanceDirective
from npc_director.unity_adapter import (
    HtmlEngineAdapter,
    build_idempotency_key,
    render_timeline,
)


def directive_with_dialogue(text: str = "欢迎回来。") -> PerformanceDirective:
    return PerformanceDirective.model_validate(
        {
            "session_id": "session",
            "turn_id": "session:1",
            "npc_id": "elder_maren",
            "dialogue": {"text": text},
            "emotion": {"coarse": "neutral", "primary": "calm"},
            "face_cues": [{"preset": "neutral", "start_ms": 0}],
            "body_cues": [{"action": "nod", "start_ms": 500}],
            "runtime_meta": {
                "specialists_called": ["baseline"],
                "prompt_versions": ["test-v1"],
            },
        }
    )


def test_console_timeline_is_time_ordered() -> None:
    timeline = render_timeline(directive_with_dialogue())

    assert timeline.index("face:") < timeline.index("body:")
    assert "500ms" in timeline


@pytest.mark.asyncio
async def test_html_adapter_escapes_dialogue(tmp_path: Path) -> None:
    adapter = HtmlEngineAdapter(tmp_path)
    ack = await adapter.emit(directive_with_dialogue("<script>alert(1)</script>"))
    rendered = Path(ack.detail or "").read_text(encoding="utf-8")

    assert "<script>alert(1)</script>" not in rendered
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in rendered
    assert ack.status == "sent"


def test_idempotency_key_is_stable_and_session_scoped() -> None:
    directive = directive_with_dialogue()
    same_turn = directive.model_copy(deep=True)
    other_session = directive.model_copy(update={"session_id": "other-session"})

    assert build_idempotency_key(directive) == build_idempotency_key(same_turn)
    assert build_idempotency_key(directive) != build_idempotency_key(other_session)


def test_exported_catalog_matches_contract_enums() -> None:
    catalog = json.loads(Path("data/catalogs/performance_catalog.json").read_text(encoding="utf-8"))

    assert catalog["body_actions"] == [action.value for action in BodyAction]
    assert catalog["face_presets"] == [preset.value for preset in FacePreset]
