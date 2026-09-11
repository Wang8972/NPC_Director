"""Public presentation contracts and delivery projections; no world effects.

This module deliberately has no provider or NPC Director runtime imports, so
authored rehearsal remains usable without a model connection.
"""
from __future__ import annotations

from copy import deepcopy
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

FACE_PRESETS = ("neutral", "happy", "sad", "angry", "surprised", "relieved_smile", "concerned", "stern", "suspicious")
BODY_ACTIONS = ("idle", "nod", "small_nod", "shake_head", "step_forward", "step_back", "point", "reach_out", "cross_arms", "open_palms")
COARSE_TO_FACE = {"neutral": "neutral", "joy": "happy", "sadness": "sad", "anger": "angry", "fear": "concerned", "surprise": "surprised"}


class PresentationModel(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class PresentedDialogue(PresentationModel):
    text: str = Field(min_length=1, max_length=8000)
    language: Literal["zh-CN", "en-US"] = "zh-CN"
    voice_style: Literal["neutral", "warm", "soft_restrained", "firm", "cold", "anxious", "excited", "solemn", "wary"] = "neutral"


class PresentedEmotion(PresentationModel):
    coarse: Literal["neutral", "joy", "sadness", "anger", "fear", "surprise"] = "neutral"
    primary: Literal["calm", "warm", "relieved", "hopeful", "melancholic", "hurt", "wary", "stern", "irritated", "afraid", "shocked", "curious", "guarded", "grateful"] = "calm"
    secondary: Literal["calm", "warm", "relieved", "hopeful", "melancholic", "hurt", "wary", "stern", "irritated", "afraid", "shocked", "curious", "guarded", "grateful"] | None = None
    intensity: float = Field(default=.5, ge=0, le=1)
    valence: float = Field(default=0, ge=-1, le=1)
    arousal: float = Field(default=.4, ge=0, le=1)


class PresentedFaceCue(PresentationModel):
    preset: Literal["neutral", "happy", "sad", "angry", "surprised", "relieved_smile", "concerned", "stern", "suspicious"]
    intensity: float = Field(default=.5, ge=0, le=1)
    start_ms: int = Field(default=0, ge=0, le=120000)
    duration_ms: int = Field(default=1500, gt=0, le=120000)


class PresentedBodyCue(PresentationModel):
    action: Literal["idle", "nod", "small_nod", "shake_head", "step_forward", "step_back", "point", "reach_out", "cross_arms", "open_palms"]
    layer: Literal["full_body", "upper_body", "additive"] = "full_body"
    priority: int = Field(default=50, ge=0, le=100)
    start_ms: int = Field(default=0, ge=0, le=120000)


class PresentedGaze(PresentationModel):
    target: Literal["player_head", "player_body", "away", "ground", "nearby_threat"] = "player_head"
    mode: Literal["direct", "soft_focus", "avoidant", "scanning"] = "direct"


class PerformancePresentation(PresentationModel):
    schema_version: Literal["1.0"] = "1.0"
    session_id: str = Field(min_length=1, max_length=120)
    turn_id: str = Field(min_length=1, max_length=240)
    npc_id: str = Field(min_length=1, max_length=80)
    dialogue: PresentedDialogue
    emotion: PresentedEmotion
    face_cues: list[PresentedFaceCue] = Field(default_factory=list, max_length=6)
    body_cues: list[PresentedBodyCue] = Field(default_factory=list, max_length=6)
    gaze: PresentedGaze = Field(default_factory=PresentedGaze)
    interrupt_policy: Literal["allow_higher_priority", "allow_any", "uninterruptible"] = "allow_higher_priority"
    confidence: float = Field(default=.5, ge=0, le=1)

    @field_validator("face_cues", "body_cues")
    @classmethod
    def ordered(cls, cues):
        return sorted(cues, key=lambda cue: cue.start_ms)


def visible_performance(directive) -> dict:
    raw = directive.model_dump(mode="json") if hasattr(directive, "model_dump") else directive
    allowed = PerformancePresentation.model_fields
    # Explicit whitelist: runtime_meta, trace, evidence and arbitrary additions
    # cannot enter the public DTO, including during replay of an older job.
    return PerformancePresentation.model_validate({k: raw[k] for k in allowed if k in raw}).model_dump(mode="json")


def legacy_performance(line: dict, session_id: str) -> dict:
    token = line.get("emotion", "neutral")
    face = token if token in FACE_PRESETS else COARSE_TO_FACE.get(token, "neutral")
    coarse, primary = {
        "happy": ("joy", "warm"), "relieved_smile": ("joy", "relieved"),
        "sad": ("sadness", "melancholic"), "angry": ("anger", "irritated"),
        "stern": ("neutral", "stern"), "concerned": ("fear", "wary"),
        "suspicious": ("neutral", "guarded"), "surprised": ("surprise", "shocked"),
    }.get(face, ("neutral", "calm"))
    body = line.get("body_action", "idle")
    if body not in BODY_ACTIONS:
        body = "idle"
    return PerformancePresentation(
        session_id=session_id, turn_id="authored:" + str(line.get("id", "line"))[:220],
        npc_id=line.get("npc_id") or "narrator",
        dialogue=PresentedDialogue(text=line.get("text") or "…"),
        emotion=PresentedEmotion(coarse=coarse, primary=primary),
        face_cues=[PresentedFaceCue(preset=face)], body_cues=[PresentedBodyCue(action=body)],
    ).model_dump(mode="json")


def projected_line(line: dict, session_id: str, delivery: dict | None = None,
                   *, historical: bool = False) -> dict:
    result = {k: deepcopy(line[k]) for k in ("id", "npc_id", "speaker", "text", "source") if k in line}
    performance = visible_performance(line["performance"]) if line.get("performance") else legacy_performance(line, session_id)
    if performance["session_id"] != session_id or performance["npc_id"] != (line.get("npc_id") or "narrator"):
        raise ValueError("performance identity does not match its dialogue line")
    if performance["dialogue"]["text"] != (line.get("text") or "…"):
        raise ValueError("performance text does not match its dialogue line")
    faces, bodies = performance["face_cues"], performance["body_cues"]
    result.update(performance=performance,
        emotion=faces[0]["preset"] if faces else COARSE_TO_FACE[performance["emotion"]["coarse"]],
        body_action=bodies[0]["action"] if bodies else "idle")
    state = (delivery or {}).get("state", "completed" if historical else "pending")
    playback = (delivery or {}).get("playback", {})
    default_playback = "completed" if state == "completed" else state if state in {"interrupted", "error"} else "pending"
    result.update(
        playback_status=playback.get("status", default_playback),
        delivery_status="committing" if state in {"acknowledged", "world_applied"} else state,
        delivered=state == "completed", visuals_skipped=bool(playback.get("visuals_skipped", False)),
        legacy=bool(playback.get("legacy", historical and not line.get("performance"))),
    )
    return result
