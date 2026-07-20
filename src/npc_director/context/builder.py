from __future__ import annotations

import json
import threading
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from hashlib import sha256
from typing import Any, Protocol, TypeVar, runtime_checkable

from pydantic import BaseModel

from npc_director.contracts.enums import (
    BodyAction,
    CoarseEmotion,
    FacePreset,
    Intent,
    PrimaryEmotion,
    SpecialistName,
)
from npc_director.contracts.performance import Dialogue
from npc_director.contracts.specialists import (
    DialogueDraft,
    DirectorInput,
    LoreEvidence,
    LoreEvidenceItem,
    LoreInput,
    NarrativeInput,
    PerformanceInput,
    ScreenwriterInput,
)
from npc_director.contracts.state import SceneSnapshot, TurnRequest
from npc_director.rag.retriever import LoreRetrievalResult


class ContextAudience(StrEnum):
    DIRECTOR = "director"
    NARRATIVE_PLANNER = "narrative_planner"
    LORE = "lore"
    SCREENWRITER = "screenwriter"
    PERFORMANCE = "performance"


@dataclass(frozen=True, slots=True)
class ContextSnapshot:
    snapshot_id: str
    turn_id: str
    audience: ContextAudience
    payload: Mapping[str, Any]
    included_fields: tuple[str, ...]
    payload_digest: str
    char_count: int


@runtime_checkable
class ContextSnapshotRecorder(Protocol):
    def record(self, snapshot: ContextSnapshot) -> None: ...


class InMemoryContextSnapshotRecorder:
    def __init__(self) -> None:
        self._snapshots: list[ContextSnapshot] = []
        self._lock = threading.Lock()

    def record(self, snapshot: ContextSnapshot) -> None:
        with self._lock:
            self._snapshots.append(snapshot)

    @property
    def snapshots(self) -> tuple[ContextSnapshot, ...]:
        with self._lock:
            return tuple(self._snapshots)

    def list_for(
        self,
        *,
        turn_id: str | None = None,
        audience: ContextAudience | str | None = None,
    ) -> tuple[ContextSnapshot, ...]:
        resolved_audience = _audience(audience) if audience is not None else None
        return tuple(
            snapshot
            for snapshot in self.snapshots
            if (turn_id is None or snapshot.turn_id == turn_id)
            and (resolved_audience is None or snapshot.audience == resolved_audience)
        )


SpecialistInput = DirectorInput | NarrativeInput | LoreInput | ScreenwriterInput | PerformanceInput
InputModel = TypeVar("InputModel", bound=BaseModel)


class DirectorContextBuilder:
    """Build and trace the minimum contract-shaped context for each agent."""

    def __init__(self, recorder: ContextSnapshotRecorder | None = None) -> None:
        self._recorder = recorder or InMemoryContextSnapshotRecorder()

    @property
    def recorder(self) -> ContextSnapshotRecorder:
        return self._recorder

    @property
    def snapshots(self) -> tuple[ContextSnapshot, ...]:
        snapshots = getattr(self._recorder, "snapshots", ())
        return tuple(snapshots)

    def build_director(
        self,
        request: TurnRequest,
        *,
        character_core: str | None = None,
        character_style: str = "",
        relationship_summary: str = "",
        quest_summary: str = "",
        history_summary: str | None = None,
        relevant_flags: Sequence[str] = (),
        lore_scopes: Sequence[str] = ("public",),
        allowed_actions: Sequence[BodyAction] = (BodyAction.IDLE,),
        allowed_faces: Sequence[FacePreset] = (FacePreset.NEUTRAL,),
        scene_summary: str | None = None,
    ) -> DirectorInput:
        combined_world_state = _join_limited(
            (request.world_state_summary, quest_summary),
            max_chars=1_500,
        )
        model = DirectorInput(
            session_id=request.session_id,
            turn_id=request.turn_id,
            npc_id=request.npc_id,
            player_input=request.player_input,
            scene_summary=scene_summary or summarize_scene(request.scene),
            character_core=character_core or request.character_core,
            character_style=character_style,
            relationship_summary=relationship_summary,
            quest_summary=combined_world_state,
            history_summary=(
                history_summary
                if history_summary is not None
                else _join_limited(request.recent_history, max_chars=3_000)
            ),
            relevant_flags=list(relevant_flags),
            lore_scopes=list(lore_scopes),
            allowed_actions=list(allowed_actions),
            allowed_faces=list(allowed_faces),
        )
        return self._record(request.turn_id, ContextAudience.DIRECTOR, model)

    def build_narrative(
        self,
        *,
        player_intent: Intent,
        scene_summary: str,
        current_quest_summary: str = "",
        relationship_summary: str = "",
        relevant_flags: Sequence[str] = (),
        turn_id: str = "unbound",
    ) -> NarrativeInput:
        model = NarrativeInput(
            player_intent=player_intent,
            scene_summary=scene_summary,
            current_quest_summary=current_quest_summary,
            relationship_summary=relationship_summary,
            relevant_flags=list(relevant_flags),
        )
        return self._record(turn_id, ContextAudience.NARRATIVE_PLANNER, model)

    def build_lore(
        self,
        *,
        queries: Sequence[str],
        scene_summary: str = "",
        allowed_scopes: Sequence[str] = ("public",),
        max_results: int = 4,
        turn_id: str = "unbound",
    ) -> LoreInput:
        model = LoreInput(
            queries=list(queries),
            scene_summary=scene_summary,
            allowed_scopes=list(allowed_scopes),
            max_results=max_results,
        )
        return self._record(turn_id, ContextAudience.LORE, model)

    def build_screenwriter(
        self,
        *,
        character_core: str,
        narrative_objective: str,
        player_input: str,
        character_style: str = "",
        narrative_constraints: Sequence[str] = (),
        lore_evidence: LoreRetrievalResult | LoreEvidence | Sequence[LoreEvidenceItem] = (),
        recent_history: Sequence[str] = (),
        turn_id: str = "unbound",
    ) -> ScreenwriterInput:
        model = ScreenwriterInput(
            character_core=character_core,
            character_style=character_style,
            narrative_objective=narrative_objective,
            narrative_constraints=list(narrative_constraints),
            lore_evidence=_evidence_items(lore_evidence),
            recent_history=list(recent_history),
            player_input=player_input,
        )
        return self._record(turn_id, ContextAudience.SCREENWRITER, model)

    def build_performance(
        self,
        *,
        scene_summary: str = "",
        allowed_actions: Sequence[BodyAction] = (BodyAction.IDLE,),
        allowed_faces: Sequence[FacePreset] = (FacePreset.NEUTRAL,),
        dialogue: Dialogue | None = None,
        coarse_emotion: CoarseEmotion | None = None,
        primary_emotion: PrimaryEmotion | None = None,
        secondary_emotion: PrimaryEmotion | None = None,
        draft: DialogueDraft | None = None,
        turn_id: str = "unbound",
    ) -> PerformanceInput:
        if draft is not None:
            dialogue = draft.dialogue
            coarse_emotion = draft.coarse_emotion
            primary_emotion = draft.primary_emotion
            secondary_emotion = draft.secondary_emotion
        if dialogue is None or coarse_emotion is None or primary_emotion is None:
            raise ValueError("dialogue and primary emotions are required")
        model = PerformanceInput(
            dialogue=dialogue,
            coarse_emotion=coarse_emotion,
            primary_emotion=primary_emotion,
            secondary_emotion=secondary_emotion,
            scene_summary=scene_summary,
            allowed_actions=list(allowed_actions),
            allowed_faces=list(allowed_faces),
        )
        return self._record(turn_id, ContextAudience.PERFORMANCE, model)

    def build_for(
        self,
        audience: ContextAudience | SpecialistName | str,
        **kwargs: Any,
    ) -> SpecialistInput:
        resolved = _audience(audience)
        builders = {
            ContextAudience.DIRECTOR: self.build_director,
            ContextAudience.NARRATIVE_PLANNER: self.build_narrative,
            ContextAudience.LORE: self.build_lore,
            ContextAudience.SCREENWRITER: self.build_screenwriter,
            ContextAudience.PERFORMANCE: self.build_performance,
        }
        return builders[resolved](**kwargs)

    def _record(
        self,
        turn_id: str,
        audience: ContextAudience,
        model: InputModel,
    ) -> InputModel:
        payload = model.model_dump(mode="json")
        canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        payload_digest = sha256(canonical.encode()).hexdigest()
        snapshot_id = sha256(f"{turn_id}\0{audience.value}\0{canonical}".encode()).hexdigest()[:24]
        snapshot = ContextSnapshot(
            snapshot_id=f"context:{snapshot_id}",
            turn_id=turn_id,
            audience=audience,
            payload=json.loads(canonical),
            included_fields=tuple(sorted(payload)),
            payload_digest=payload_digest,
            char_count=len(canonical),
        )
        self._recorder.record(snapshot)
        return model


def summarize_scene(scene: SceneSnapshot) -> str:
    parts = [f"location={scene.location}", f"tension={scene.tension:.2f}"]
    if scene.nearby_entities:
        parts.append(f"nearby={','.join(scene.nearby_entities)}")
    if scene.animator_state:
        parts.append(f"animator={scene.animator_state}")
    if scene.active_actions:
        parts.append(f"active_actions={','.join(scene.active_actions)}")
    return "; ".join(parts)


def _audience(value: ContextAudience | SpecialistName | str) -> ContextAudience:
    raw = value.value if isinstance(value, (ContextAudience, SpecialistName)) else str(value)
    aliases = {
        "narrative": ContextAudience.NARRATIVE_PLANNER,
        "lore_specialist": ContextAudience.LORE,
        "performance_specialist": ContextAudience.PERFORMANCE,
    }
    if raw in aliases:
        return aliases[raw]
    return ContextAudience(raw)


def _join_limited(values: Sequence[str], *, max_chars: int) -> str:
    combined = "\n".join(value.strip() for value in values if value.strip())
    if len(combined) <= max_chars:
        return combined
    return f"{combined[: max_chars - 1].rstrip()}…"


def _evidence_items(
    evidence: LoreRetrievalResult | LoreEvidence | Sequence[LoreEvidenceItem],
) -> list[LoreEvidenceItem]:
    if isinstance(evidence, LoreRetrievalResult):
        return [item.to_contract() for item in evidence.items]
    if isinstance(evidence, LoreEvidence):
        return list(evidence.items)
    return list(evidence)
