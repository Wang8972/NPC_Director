from __future__ import annotations

from npc_director.contracts import TurnProposal
from npc_director.contracts.enums import CoarseEmotion, Intent, PrimaryEmotion
from npc_director.orchestration.emotion_policy import INTENT_EMOTION_COMBOS, correct_emotion


def make_proposal(intent: str, coarse: str, primary: str) -> TurnProposal:
    return TurnProposal.model_validate(
        {
            "plan": {
                "goal": "回应玩家",
                "intent": intent,
                "required_specialists": ["baseline"],
            },
            "performance": {
                "dialogue": {"text": "欢迎来到灰港。"},
                "emotion": {
                    "coarse": coarse,
                    "primary": primary,
                    "secondary": "curious",
                    "intensity": 0.7,
                },
                "face_cues": [{"preset": "happy"}],
                "body_cues": [{"action": "small_nod"}],
                "confidence": 0.9,
            },
        }
    )


def test_legal_combo_passes_through_unchanged() -> None:
    proposal = make_proposal("greeting", "joy", "warm")

    corrected = correct_emotion(proposal)

    assert corrected is proposal


def test_illegal_combo_is_replaced_with_intent_default() -> None:
    proposal = make_proposal("greeting", "anger", "stern")

    corrected = correct_emotion(proposal)

    default_coarse, default_primary = INTENT_EMOTION_COMBOS[Intent.GREETING][0]
    assert corrected.performance.emotion.coarse is default_coarse
    assert corrected.performance.emotion.primary is default_primary
    # Only coarse/primary are corrected; the rest of the emotion survives.
    assert corrected.performance.emotion.secondary is PrimaryEmotion.CURIOUS
    assert corrected.performance.emotion.intensity == 0.7
    # The original proposal is untouched.
    assert proposal.performance.emotion.coarse is CoarseEmotion.ANGER


def test_unknown_intent_passes_through() -> None:
    proposal = make_proposal("other", "anger", "stern")

    corrected = correct_emotion(proposal)

    assert corrected is proposal


def test_every_intent_default_is_legal_for_itself() -> None:
    for intent, combos in INTENT_EMOTION_COMBOS.items():
        assert combos, f"{intent} has no combos"
        assert combos[0] in combos
        assert len(set(combos)) == len(combos), f"{intent} has duplicate combos"
