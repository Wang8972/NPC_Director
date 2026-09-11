from last_light.director import _compact_schema
from last_light.director_contracts import TrainMeaning
from npc_director.contracts.content import ContentCandidate
from npc_director.contracts.planning import TurnAnalysis


def assert_machine_constraints_preserved(original, compact, property_map=False):
    if isinstance(original, dict):
        for key, value in original.items():
            if not property_map and key in {"description", "title", "examples"}:
                continue
            assert key in compact, key
            assert_machine_constraints_preserved(value, compact[key], key in {"properties", "patternProperties", "$defs", "definitions"})
    elif isinstance(original, list):
        assert len(original) == len(compact)
        for a, b in zip(original, compact):
            assert_machine_constraints_preserved(a, b)
    else:
        assert original == compact


def test_schema_compaction_does_not_drop_real_title_or_description_fields():
    for contract in (TurnAnalysis, TrainMeaning, ContentCandidate):
        original = contract.model_json_schema()
        compact = _compact_schema(original)
        assert_machine_constraints_preserved(original, compact)
    assert "title" in _compact_schema(ContentCandidate.model_json_schema())["properties"]
