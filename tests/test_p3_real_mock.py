import pytest

from scripts.run_p3_real_mock import _build_codex_telemetry, _extract_json_object


def test_extract_json_object_accepts_plain_and_fenced_output() -> None:
    assert _extract_json_object('{"value": 1}') == '{"value": 1}'
    assert _extract_json_object('```json\n{"value": 1}\n```') == '{"value": 1}'


def test_extract_json_object_rejects_missing_object() -> None:
    try:
        _extract_json_object("not json")
    except ValueError as error:
        assert "no JSON object" in str(error)
    else:
        raise AssertionError("missing JSON object was accepted")


def test_codex_telemetry_splits_stages_and_usage() -> None:
    telemetry = _build_codex_telemetry(
        1.0,
        7.1,
        7.0,
        {
            "thread.started": 1.2,
            "turn.started": 2.0,
            "item:reasoning": 5.0,
            "item:agent_message": 6.5,
            "turn.completed": 6.8,
        },
        {"input_tokens": 100, "cached_input_tokens": 20, "output_tokens": 10},
        0.001,
    )

    assert telemetry["stages_ms"]["cli_startup"] == pytest.approx(200)
    assert telemetry["stages_ms"]["model_reasoning_to_item"] == pytest.approx(3000)
    assert telemetry["usage"]["input_tokens"] == 100
    assert telemetry["estimated_cost_usd"] == 0.001
