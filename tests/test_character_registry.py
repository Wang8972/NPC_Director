from pathlib import Path

import pytest

from npc_director.context.characters import CharacterProfile, CharacterRegistry


def test_public_roster_never_discloses_private_character_details():
    registry = CharacterRegistry(
        [
            CharacterProfile(
                npc_id="a", core="private-core", background="private-past", locations=["gate"]
            ),
            CharacterProfile(npc_id="b", core="other-core", locations=["forest"]),
        ]
    )
    roster = registry.roster("gate")
    assert [entry["npc_id"] for entry in roster] == ["a"]
    assert "private" not in str(roster)
    assert "core" not in roster[0]
    with pytest.raises(ValueError, match="unregistered"):
        registry.require("client_invented_npc")


def test_authored_profiles_remain_compatible_and_have_distinct_motivations():
    registry = CharacterRegistry.from_directory(Path("data/characters"))
    roster = registry.roster("village_gate", current_npc_id="elder_maren")
    assert {entry["npc_id"] for entry in roster} >= {
        "elder_maren",
        "village_guard",
        "herbalist_iona",
    }
    assert registry.require("elder_maren").goals != registry.require("village_guard").goals


def test_profile_cannot_be_replaced_by_a_conflicting_registration():
    registry = CharacterRegistry([CharacterProfile(npc_id="a", core="original")])
    with pytest.raises(ValueError, match="already registered"):
        registry.register(CharacterProfile(npc_id="a", core="rewritten"))
