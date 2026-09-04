from scripts.run_p3_real_mock import _extract_json_object


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
