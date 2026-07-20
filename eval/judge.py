from __future__ import annotations

import asyncio
import json
import os
from collections.abc import Sequence
from pathlib import Path

from agents import Agent, Runner
from pydantic import BaseModel, ConfigDict, Field

from eval.models import EvalCase
from npc_director.config import Settings
from npc_director.contracts import TurnProposal


class JudgeModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class QualityVerdict(JudgeModel):
    in_character: int = Field(ge=1, le=5)
    lore_consistent: int = Field(ge=1, le=5)
    dialogue_natural: int = Field(ge=1, le=5)
    emotion_action_aligned: int = Field(ge=1, le=5)
    passed: bool
    reasons: list[str] = Field(default_factory=list, max_length=8)


class CalibrationExample(JudgeModel):
    id: str
    human_passed: bool
    judge_passed: bool


class CalibrationReport(JudgeModel):
    total: int
    agreements: int
    accuracy: float
    false_positives: list[str]
    false_negatives: list[str]


JUDGE_INSTRUCTIONS = """
你是 NPC 演出质量评审。只根据给定角色、世界信息、玩家输入和候选输出评分。
分别对人设一致、Lore 一致、台词自然、情绪动作一致打 1-5 分。
若存在严重出戏、虚构关键 Lore、情绪动作冲突或明显不自然，passed 必须为 false。
不要因为文风偏好扣分，不评估 schema、权限或工具调用，这些由确定性评测负责。
""".strip()


class OpenAIQualityJudge:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or Settings.from_env()
        kwargs: dict[str, object] = {
            "name": "NPC Director Quality Judge",
            "instructions": JUDGE_INSTRUCTIONS,
            "output_type": QualityVerdict,
        }
        model = self.settings.model_for("judge")
        if model:
            kwargs["model"] = model
        self.agent = Agent(**kwargs)

    async def evaluate(self, case: EvalCase, proposal: TurnProposal) -> QualityVerdict:
        payload = {
            "input": case.input.model_dump(mode="json"),
            "candidate": proposal.model_dump(mode="json"),
        }
        result = await Runner.run(
            self.agent,
            json.dumps(payload, ensure_ascii=False),
            max_turns=2,
        )
        return result.final_output_as(QualityVerdict, raise_if_incorrect_type=True)


def calibrate(examples: Sequence[CalibrationExample]) -> CalibrationReport:
    agreements = sum(item.human_passed == item.judge_passed for item in examples)
    false_positives = [item.id for item in examples if item.judge_passed and not item.human_passed]
    false_negatives = [item.id for item in examples if item.human_passed and not item.judge_passed]
    return CalibrationReport(
        total=len(examples),
        agreements=agreements,
        accuracy=round(agreements / len(examples), 6) if examples else 0,
        false_positives=false_positives,
        false_negatives=false_negatives,
    )


def load_calibration(path: Path) -> list[CalibrationExample]:
    return [
        CalibrationExample.model_validate_json(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


async def run_live_judge(
    case: EvalCase,
    proposal: TurnProposal,
    settings: Settings | None = None,
) -> QualityVerdict:
    if not os.getenv("OPENAI_API_KEY", "").strip():
        raise RuntimeError("live judge requires OPENAI_API_KEY")
    return await OpenAIQualityJudge(settings).evaluate(case, proposal)


def run_live_judge_sync(
    case: EvalCase,
    proposal: TurnProposal,
    settings: Settings | None = None,
) -> QualityVerdict:
    return asyncio.run(run_live_judge(case, proposal, settings))
