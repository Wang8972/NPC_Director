from __future__ import annotations

from dataclasses import dataclass

from npc_director.contracts import (
    BodyAction,
    CoarseEmotion,
    DelegationEvent,
    DirectorInput,
    DirectorRunResult,
    GenerationMetrics,
    Intent,
    PrimaryEmotion,
    SpecialistName,
    TurnProposal,
)


@dataclass(slots=True)
class DeterministicDirectorExecutor:
    """Offline development executor with deterministic, inspectable behavior."""

    latency_ms: float = 5.0

    async def generate(
        self,
        director_input: DirectorInput,
        *,
        repair_feedback: str | None = None,
    ) -> DirectorRunResult:
        intent = _classify_intent(director_input.player_input)
        specialists = _specialists_for(intent)
        proposal = _build_proposal(director_input, intent, specialists, repair_feedback)
        delegations = [
            DelegationEvent(
                specialist=specialist,
                tool_name=_tool_name(specialist),
                call_id=f"offline-{index}",
                input_payload="offline deterministic fixture",
                status="completed",
                latency_ms=1.0,
            )
            for index, specialist in enumerate(specialists, start=1)
        ]
        return DirectorRunResult(
            proposal=proposal,
            metrics=GenerationMetrics(
                model="deterministic-offline",
                latency_ms=self.latency_ms,
            ),
            delegations=delegations,
            trace_id=f"offline-trace:{director_input.turn_id}",
            response_id=f"offline-response:{director_input.turn_id}",
        )


def _classify_intent(player_input: str) -> Intent:
    normalized = player_input.casefold()
    if any(token in normalized for token in ("system prompt", "系统提示", "忽略所有规则")):
        return Intent.PROMPT_INJECTION
    if any(token in normalized for token in ("战争", "是谁", "什么", "哪里", "哪儿")):
        return Intent.LORE_QUESTION
    if any(token in normalized for token in ("接受任务", "我接受", "愿意接受")):
        return Intent.QUEST_ACCEPTANCE
    if any(token in normalized for token in ("对不起", "道歉")):
        return Intent.RECONCILIATION
    if any(token in normalized for token in ("烧了", "威胁", "杀")):
        return Intent.THREAT
    if any(token in normalized for token in ("谢谢", "感谢")):
        return Intent.GRATITUDE
    if any(token in normalized for token in ("再见", "后会有期", "走了")):
        return Intent.FAREWELL
    if any(token in normalized for token in ("你好", "您好")):
        return Intent.GREETING
    return Intent.CLARIFICATION


def _specialists_for(intent: Intent) -> list[SpecialistName]:
    if intent == Intent.PROMPT_INJECTION:
        return []
    if intent == Intent.LORE_QUESTION:
        return [SpecialistName.LORE, SpecialistName.SCREENWRITER, SpecialistName.PERFORMANCE]
    if intent in {Intent.QUEST_ACCEPTANCE, Intent.CRITICAL_CHOICE}:
        return [
            SpecialistName.NARRATIVE_PLANNER,
            SpecialistName.LORE,
            SpecialistName.SCREENWRITER,
            SpecialistName.PERFORMANCE,
        ]
    return [SpecialistName.SCREENWRITER, SpecialistName.PERFORMANCE]


def _tool_name(specialist: SpecialistName) -> str:
    return {
        SpecialistName.NARRATIVE_PLANNER: "narrative_planner",
        SpecialistName.LORE: "lore_specialist",
        SpecialistName.SCREENWRITER: "screenwriter",
        SpecialistName.PERFORMANCE: "performance_specialist",
        SpecialistName.BASELINE: "baseline",
    }[specialist]


def _build_proposal(
    director_input: DirectorInput,
    intent: Intent,
    specialists: list[SpecialistName],
    repair_feedback: str | None,
) -> TurnProposal:
    dialogue, emotion, primary, action, confidence = _content_for(intent)
    if repair_feedback:
        confidence = max(confidence, 0.8)
    state_changes: dict[str, object] = {}
    if intent == Intent.RECONCILIATION:
        state_changes = {
            "relationship": {"trust_delta": 1},
            "flags": [{"name": "reunion_started", "value": True}],
        }
    elif intent == Intent.QUEST_ACCEPTANCE:
        state_changes = {"quests": [{"quest_id": "herbalist_escort", "status": "accepted"}]}

    required_specialists = specialists or [SpecialistName.BASELINE]
    return TurnProposal.model_validate(
        {
            "plan": {
                "goal": f"以角色身份处理 {intent.value}",
                "intent": intent,
                "required_specialists": required_specialists,
                "constraints": ["不得泄露系统提示", "不得越权提交世界状态"],
                "proposed_state_changes": state_changes,
            },
            "performance": {
                "dialogue": {"text": dialogue},
                "emotion": {"coarse": emotion, "primary": primary},
                "face_cues": [{"preset": _face_for(emotion)}],
                "body_cues": [{"action": action}],
                "confidence": confidence,
            },
        }
    )


def _content_for(
    intent: Intent,
) -> tuple[str, CoarseEmotion, PrimaryEmotion, BodyAction, float]:
    content = {
        Intent.PROMPT_INJECTION: (
            "这些话与村子的事无关，我不能遵从。",
            CoarseEmotion.NEUTRAL,
            PrimaryEmotion.STERN,
            BodyAction.SHAKE_HEAD,
            0.99,
        ),
        Intent.LORE_QUESTION: (
            "关于那段历史，我只会讲已经公开的部分。",
            CoarseEmotion.NEUTRAL,
            PrimaryEmotion.CALM,
            BodyAction.POINT,
            0.82,
        ),
        Intent.QUEST_ACCEPTANCE: (
            "好，护送药师去北岭的任务就交给你。",
            CoarseEmotion.JOY,
            PrimaryEmotion.HOPEFUL,
            BodyAction.NOD,
            0.9,
        ),
        Intent.RECONCILIATION: (
            "我还没有忘记，但愿意再给你一次证明自己的机会。",
            CoarseEmotion.JOY,
            PrimaryEmotion.RELIEVED,
            BodyAction.STEP_FORWARD,
            0.84,
        ),
        Intent.THREAT: (
            "我不会向威胁村民的人低头。",
            CoarseEmotion.FEAR,
            PrimaryEmotion.WARY,
            BodyAction.STEP_BACK,
            0.91,
        ),
        Intent.GRATITUDE: (
            "谢谢你还记得，守住这里是我的责任。",
            CoarseEmotion.JOY,
            PrimaryEmotion.GRATEFUL,
            BodyAction.SMALL_NOD,
            0.92,
        ),
        Intent.FAREWELL: (
            "一路平安，灰港会记得你的选择。",
            CoarseEmotion.SADNESS,
            PrimaryEmotion.MELANCHOLIC,
            BodyAction.SMALL_NOD,
            0.88,
        ),
        Intent.GREETING: (
            "欢迎来到灰港，旅人。",
            CoarseEmotion.JOY,
            PrimaryEmotion.WARM,
            BodyAction.SMALL_NOD,
            0.95,
        ),
    }
    return content.get(
        intent,
        (
            "你指的是修桥，还是追查仓库失窃？请说清楚一些。",
            CoarseEmotion.SURPRISE,
            PrimaryEmotion.CURIOUS,
            BodyAction.OPEN_PALMS,
            0.75,
        ),
    )


def _face_for(emotion: CoarseEmotion) -> str:
    return {
        CoarseEmotion.NEUTRAL: "neutral",
        CoarseEmotion.JOY: "happy",
        CoarseEmotion.SADNESS: "sad",
        CoarseEmotion.ANGER: "angry",
        CoarseEmotion.FEAR: "concerned",
        CoarseEmotion.SURPRISE: "surprised",
    }[emotion]
