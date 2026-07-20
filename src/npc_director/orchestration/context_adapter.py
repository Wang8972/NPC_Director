from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from npc_director.context import DirectorContextBuilder, compact_history
from npc_director.contracts import (
    BodyAction,
    DirectorInput,
    FacePreset,
    NPCDomainState,
    TurnRequest,
)
from npc_director.rag import LoreRetriever


class LongTermMemoryReader(Protocol):
    async def alist_for_npc(self, npc_id: str, *, limit: int = 20): ...


@dataclass(frozen=True, slots=True)
class BuiltTurnContext:
    director_input: DirectorInput
    snapshot: dict[str, object]
    available_lore_refs: tuple[str, ...] = ()


class DefaultContextBuilder:
    def __init__(
        self,
        *,
        lore_retriever: LoreRetriever | None = None,
        memory_reader: LongTermMemoryReader | None = None,
        character_root: Path = Path("data/characters"),
        lore_top_k: int = 4,
        lore_token_budget: int = 1_200,
        history_limit: int = 8,
    ) -> None:
        self.lore_retriever = lore_retriever
        self.memory_reader = memory_reader
        self.character_root = character_root
        self.lore_top_k = lore_top_k
        self.lore_token_budget = lore_token_budget
        self.history_limit = history_limit
        self.builder = DirectorContextBuilder()

    async def build(
        self,
        request: TurnRequest,
        domain_state: NPCDomainState,
    ) -> BuiltTurnContext:
        scene_summary = json.dumps(request.scene.model_dump(mode="json"), ensure_ascii=False)
        relationship_summary = json.dumps(domain_state.relationship, ensure_ascii=False)
        quest_summary = json.dumps(domain_state.quests, ensure_ascii=False)
        memories = (
            await self.memory_reader.alist_for_npc(request.npc_id, limit=12)
            if self.memory_reader is not None
            else []
        )
        compacted = compact_history(
            [*request.recent_history, *(memory.content for memory in memories)],
            recent_limit=self.history_limit,
            max_chars=3_000,
        )
        history_summary = compacted.summary
        relevant_flags = [
            name for name, enabled in sorted(domain_state.world_flags.items()) if enabled
        ]
        character_core, character_style = self._character(request)
        lore_scopes = ["public"]
        if domain_state.world_flags.get("secret_lore_unlocked"):
            lore_scopes.append(f"secret:{request.npc_id}")
        retrieval = (
            self.lore_retriever.retrieve(
                request.player_input,
                allowed_scopes=lore_scopes,
                top_k=self.lore_top_k,
                token_budget=self.lore_token_budget,
                char_budget=self.lore_token_budget * 4,
            )
            if self.lore_retriever is not None
            else None
        )
        director_input = self.builder.build_director(
            request,
            character_core=character_core,
            character_style=character_style,
            relationship_summary=relationship_summary,
            quest_summary=quest_summary,
            history_summary=history_summary,
            relevant_flags=relevant_flags,
            lore_scopes=lore_scopes,
            allowed_actions=list(BodyAction),
            allowed_faces=list(FacePreset),
            scene_summary=scene_summary,
        )
        snapshot = self.builder.snapshots[-1]
        return BuiltTurnContext(
            director_input=director_input,
            snapshot={
                "director": snapshot.payload,
                "included_fields": snapshot.included_fields,
                "payload_digest": snapshot.payload_digest,
                "domain_version": domain_state.version,
                "lore": {
                    "refs": [item.ref for item in retrieval.items] if retrieval else [],
                    "used_tokens": retrieval.used_tokens if retrieval else 0,
                    "used_chars": retrieval.used_chars if retrieval else 0,
                    "cache_hit": retrieval.cache_hit if retrieval else False,
                },
                "memory_refs": [memory.memory_id for memory in memories],
            },
            available_lore_refs=(tuple(item.ref for item in retrieval.items) if retrieval else ()),
        )

    def _character(self, request: TurnRequest) -> tuple[str, str]:
        path = self.character_root / f"{request.npc_id}.json"
        if not path.exists():
            return request.character_core, ""
        payload = json.loads(path.read_text(encoding="utf-8"))
        return str(payload.get("core") or request.character_core), str(payload.get("style") or "")
