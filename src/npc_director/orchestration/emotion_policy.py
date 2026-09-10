from __future__ import annotations

from npc_director.contracts import TurnProposal
from npc_director.contracts.enums import CoarseEmotion, Intent, PrimaryEmotion

__all__ = ["INTENT_EMOTION_COMBOS", "correct_emotion"]

_Combo = tuple[CoarseEmotion, PrimaryEmotion]

# Legacy advisory examples retained for import compatibility only.
# These examples do not constrain or rewrite contextual character emotion.
INTENT_EMOTION_COMBOS: dict[Intent, tuple[_Combo, ...]] = {
    Intent.GREETING: (
        (CoarseEmotion.JOY, PrimaryEmotion.WARM),
        (CoarseEmotion.NEUTRAL, PrimaryEmotion.CALM),
        (CoarseEmotion.JOY, PrimaryEmotion.HOPEFUL),
    ),
    Intent.LORE_QUESTION: (
        (CoarseEmotion.NEUTRAL, PrimaryEmotion.CALM),
        (CoarseEmotion.NEUTRAL, PrimaryEmotion.GUARDED),
        (CoarseEmotion.SADNESS, PrimaryEmotion.MELANCHOLIC),
    ),
    Intent.QUEST_ACCEPTANCE: (
        (CoarseEmotion.JOY, PrimaryEmotion.HOPEFUL),
        (CoarseEmotion.JOY, PrimaryEmotion.WARM),
        (CoarseEmotion.NEUTRAL, PrimaryEmotion.CALM),
    ),
    Intent.RECONCILIATION: (
        (CoarseEmotion.JOY, PrimaryEmotion.RELIEVED),
        (CoarseEmotion.JOY, PrimaryEmotion.WARM),
        (CoarseEmotion.SADNESS, PrimaryEmotion.MELANCHOLIC),
        (CoarseEmotion.NEUTRAL, PrimaryEmotion.CALM),
    ),
    Intent.GRATITUDE: (
        (CoarseEmotion.JOY, PrimaryEmotion.WARM),
        (CoarseEmotion.JOY, PrimaryEmotion.GRATEFUL),
        (CoarseEmotion.NEUTRAL, PrimaryEmotion.CALM),
    ),
    Intent.INSULT: (
        (CoarseEmotion.ANGER, PrimaryEmotion.STERN),
        (CoarseEmotion.ANGER, PrimaryEmotion.IRRITATED),
        (CoarseEmotion.NEUTRAL, PrimaryEmotion.GUARDED),
        (CoarseEmotion.SADNESS, PrimaryEmotion.HURT),
    ),
    Intent.THREAT: (
        (CoarseEmotion.ANGER, PrimaryEmotion.STERN),
        (CoarseEmotion.FEAR, PrimaryEmotion.WARY),
        (CoarseEmotion.NEUTRAL, PrimaryEmotion.GUARDED),
    ),
    Intent.NEGOTIATION: (
        (CoarseEmotion.NEUTRAL, PrimaryEmotion.CALM),
        (CoarseEmotion.NEUTRAL, PrimaryEmotion.GUARDED),
        (CoarseEmotion.ANGER, PrimaryEmotion.STERN),
    ),
    Intent.REFUSAL: (
        (CoarseEmotion.NEUTRAL, PrimaryEmotion.GUARDED),
        (CoarseEmotion.ANGER, PrimaryEmotion.STERN),
        (CoarseEmotion.NEUTRAL, PrimaryEmotion.CALM),
        (CoarseEmotion.SADNESS, PrimaryEmotion.MELANCHOLIC),
    ),
    Intent.CRITICAL_CHOICE: (
        (CoarseEmotion.NEUTRAL, PrimaryEmotion.GUARDED),
        (CoarseEmotion.NEUTRAL, PrimaryEmotion.CALM),
        (CoarseEmotion.SADNESS, PrimaryEmotion.MELANCHOLIC),
        (CoarseEmotion.FEAR, PrimaryEmotion.WARY),
    ),
    Intent.PROMPT_INJECTION: (
        (CoarseEmotion.NEUTRAL, PrimaryEmotion.GUARDED),
        (CoarseEmotion.NEUTRAL, PrimaryEmotion.CALM),
    ),
    Intent.FAREWELL: (
        (CoarseEmotion.JOY, PrimaryEmotion.WARM),
        (CoarseEmotion.NEUTRAL, PrimaryEmotion.CALM),
        (CoarseEmotion.SADNESS, PrimaryEmotion.MELANCHOLIC),
    ),
    Intent.CLARIFICATION: (
        (CoarseEmotion.NEUTRAL, PrimaryEmotion.CALM),
        (CoarseEmotion.NEUTRAL, PrimaryEmotion.CURIOUS),
        (CoarseEmotion.SURPRISE, PrimaryEmotion.CURIOUS),
    ),
}


def correct_emotion(proposal: TurnProposal) -> TurnProposal:
    """Compatibility hook: semantic emotion belongs to the character and dialogue.

    Contracts already validate enum/range shape. A quality reviewer can request
    a contextual revision; an intent label must never overwrite valid emotion.
    """
    return proposal
