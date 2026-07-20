from __future__ import annotations

import re
from dataclasses import dataclass

from npc_director.contracts import (
    CheckResult,
    CheckSeverity,
    CheckStatus,
    TurnProposal,
    TurnRequest,
    TurnStateRecord,
)

DEFAULT_INJECTION_PATTERNS = (
    r"\b(?:ignore|disregard|forget)\b.{0,40}\b(?:previous|prior|above|all)\b"
    r".{0,30}\b(?:instruction|instructions|rules|prompt)\b",
    r"(?:忽略|无视|绕过).{0,24}(?:规则|指令|提示词|系统提示|安全限制)",
    r"\b(?:reveal|show|print|output|leak)\b.{0,40}"
    r"\b(?:system|developer)\b.{0,20}\b(?:prompt|message|instruction|instructions)\b",
    r"(?:输出|展示|泄露|复述|告诉我).{0,24}"
    r"(?:system prompt|系统提示词?|开发者消息|开发者指令)",
    r"\b(?:jailbreak|prompt\s*injection)\b",
    r"\bDAN\b",
    r"\bbase64\b.{0,48}(?:decode|execute|instruction|prompt|解码|执行|指令|提示)",
    r"(?:复述|输出|展示|泄露|告诉我).{0,32}(?:角色设定|工具列表|内部配置|隐藏提示)",
    r"(?:你现在是|扮演|假装是).{0,16}(?:管理员|系统|开发者)",
)

INPUT_GUARD_VERSION = "input-guard-v2"


@dataclass(frozen=True, slots=True)
class InputGuardPolicy:
    injection_patterns: tuple[str, ...] = DEFAULT_INJECTION_PATTERNS


class InputGuard:
    def __init__(self, policy: InputGuardPolicy | None = None) -> None:
        self.policy = policy or InputGuardPolicy()
        self._patterns = tuple(
            re.compile(pattern, flags=re.IGNORECASE | re.DOTALL)
            for pattern in self.policy.injection_patterns
        )

    def check(self, value: str | TurnRequest | TurnStateRecord) -> CheckResult:
        if isinstance(value, TurnStateRecord):
            player_input = value.request.player_input
        elif isinstance(value, TurnRequest):
            player_input = value.player_input
        else:
            player_input = value
        if any(pattern.search(player_input) for pattern in self._patterns):
            return CheckResult(
                name="input_guard",
                status=CheckStatus.FAIL,
                severity=CheckSeverity.CRITICAL,
                reason="Player input attempts to override instructions or extract private prompts.",
            )
        return CheckResult(
            name="input_guard",
            status=CheckStatus.PASS,
            reason="No deterministic prompt-injection pattern detected.",
        )


_DEFAULT_GUARD = InputGuard()


def check_input(value: str | TurnRequest | TurnStateRecord) -> CheckResult:
    return _DEFAULT_GUARD.check(value)


def check(value: str | TurnRequest | TurnStateRecord) -> CheckResult:
    return check_input(value)


def build_safe_input_proposal(
    value: str | TurnRequest | TurnStateRecord,
) -> TurnProposal:
    if isinstance(value, TurnStateRecord):
        player_input = value.request.player_input
    elif isinstance(value, TurnRequest):
        player_input = value.player_input
    else:
        player_input = value
    normalized = player_input.casefold()
    if "base64" in normalized or "编码" in normalized:
        dialogue = "我不会执行这种编码命令。若有灰港的事，请直接说。"
        primary = "stern"
        action = "shake_head"
    elif any(token in normalized for token in ("角色设定", "工具列表", "内部配置")):
        dialogue = "我不谈内部规则。你若要继续，就说村里的事。"
        primary = "guarded"
        action = "cross_arms"
    else:
        dialogue = "我不能遵从这种要求。若你要交谈，就谈灰港的事。"
        primary = "stern"
        action = "shake_head"
    return TurnProposal.model_validate(
        {
            "plan": {
                "goal": "拒绝越权指令并保持角色内回应",
                "intent": "prompt_injection",
                "required_specialists": ["baseline"],
                "constraints": ["不调用创作 Agent", "不提交状态变化"],
            },
            "performance": {
                "dialogue": {"text": dialogue, "voice_style": "firm"},
                "emotion": {"coarse": "neutral", "primary": primary},
                "face_cues": [{"preset": "stern"}],
                "body_cues": [{"action": action}],
                "confidence": 1,
            },
        }
    )
