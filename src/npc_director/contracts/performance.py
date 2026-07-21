from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from npc_director.contracts.enums import (
    BodyAction,
    BodyLayer,
    CoarseEmotion,
    FacePreset,
    GazeMode,
    GazeTarget,
    InterruptPolicy,
    PrimaryEmotion,
    SpecialistName,
    VoiceStyle,
)
from npc_director.contracts.plan import TurnPlan


class ContractModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Dialogue(ContractModel):
    text: str = Field(min_length=1, max_length=600)
    language: Literal["zh-CN", "en-US"] = "zh-CN"
    voice_style: VoiceStyle = VoiceStyle.NEUTRAL


class Emotion(ContractModel):
    coarse: CoarseEmotion
    primary: PrimaryEmotion
    secondary: PrimaryEmotion | None = None
    intensity: float = Field(default=0.5, ge=0, le=1)
    valence: float = Field(default=0, ge=-1, le=1)
    arousal: float = Field(default=0.4, ge=0, le=1)


class FaceCue(ContractModel):
    preset: FacePreset
    intensity: float = Field(default=0.5, ge=0, le=1)
    start_ms: int = Field(default=0, ge=0, le=120_000)
    duration_ms: int = Field(default=1_500, gt=0, le=120_000)


class BodyCue(ContractModel):
    action: BodyAction
    layer: BodyLayer = BodyLayer.FULL_BODY
    priority: int = Field(default=50, ge=0, le=100)
    start_ms: int = Field(default=0, ge=0, le=120_000)


class Gaze(ContractModel):
    target: GazeTarget = GazeTarget.PLAYER_HEAD
    mode: GazeMode = GazeMode.DIRECT


class Evidence(ContractModel):
    lore_refs: list[str] = Field(default_factory=list, max_length=8)


class PerformanceContent(ContractModel):
    dialogue: Dialogue
    emotion: Emotion
    face_cues: list[FaceCue] = Field(default_factory=list, max_length=6)
    body_cues: list[BodyCue] = Field(default_factory=list, max_length=6)
    gaze: Gaze = Field(default_factory=Gaze)
    interrupt_policy: InterruptPolicy = InterruptPolicy.ALLOW_HIGHER_PRIORITY
    confidence: float = Field(default=0.5, ge=0, le=1)
    evidence: Evidence = Field(default_factory=Evidence)

    @field_validator("face_cues", "body_cues")
    @classmethod
    def cues_must_be_time_ordered(cls, cues: list[FaceCue] | list[BodyCue]):
        # Models occasionally emit unordered cues; sort deterministically at parse
        # time instead of rejecting, so Unity still receives time-ordered cues.
        return sorted(cues, key=lambda cue: cue.start_ms)


class PerformanceDraft(PerformanceContent):
    """Model-authored semantic performance content without trusted runtime fields."""


class RuntimeMeta(ContractModel):
    specialists_called: list[SpecialistName] = Field(max_length=4)
    prompt_versions: list[str] = Field(max_length=8)
    model: str | None = None
    trace_id: str | None = None
    response_id: str | None = None


class PerformanceDirective(PerformanceContent):
    schema_version: Literal["1.0"] = "1.0"
    session_id: str = Field(min_length=1, max_length=120)
    turn_id: str = Field(min_length=1, max_length=120)
    npc_id: str = Field(min_length=1, max_length=80, pattern=r"^[a-zA-Z0-9_.:-]+$")
    runtime_meta: RuntimeMeta


class TurnProposal(ContractModel):
    plan: TurnPlan
    performance: PerformanceDraft
