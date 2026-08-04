from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from npc_director.config import Settings
from npc_director.context import DirectorContextBuilder, compact_history
from npc_director.contracts import DirectorInput, NPCDomainState, TurnRequest
from npc_director.orchestration.turn_policy import CapabilityResolver
from npc_director.rag import LoreRetriever


class LongTermMemoryReader(Protocol):
    async def alist_for_npc(self, npc_id: str, *, limit: int = 20): ...


@dataclass(frozen=True, slots=True)
class BuiltTurnContext:
    director_input: DirectorInput
    snapshot: dict[str, object]
    available_lore_refs: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class _SceneCatalog:
    version: str | None
    capabilities: Mapping[str, object]


class DefaultContextBuilder:
    def __init__(
        self,
        *,
        lore_retriever: LoreRetriever | None = None,
        memory_reader: LongTermMemoryReader | None = None,
        character_root: Path = Path("data/characters"),
        scene_root: Path = Path("data/scenes"),
        settings: Settings | None = None,
        lore_top_k: int = 4,
        lore_token_budget: int = 1_200,
        history_limit: int = 8,
    ) -> None:
        self.lore_retriever = lore_retriever
        self.memory_reader = memory_reader
        self.character_root = character_root
        self.scene_root = scene_root
        self.settings = settings
        self.lore_top_k = lore_top_k
        self.lore_token_budget = lore_token_budget
        self.history_limit = history_limit
        self.builder = DirectorContextBuilder()

    async def build(
        self,
        request: TurnRequest,
        domain_state: NPCDomainState,
    ) -> BuiltTurnContext:
        # Client metadata is consumed only by deterministic capability/budget
        # narrowing below; arbitrary metadata text must never enter model context.
        scene_summary = json.dumps(
            request.scene.model_dump(mode="json", exclude={"metadata"}),
            ensure_ascii=False,
        )
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
        catalog = self._scene_catalog(request.scene.location)
        capabilities = catalog.capabilities
        catalog_matches = (
            catalog.version is not None and request.scene.catalog_version == catalog.version
        )
        allowed_state_paths = sorted(
            set(self._domain_state_paths(domain_state))
            | set(_string_list(capabilities.get("allowed_state_paths")))
        )
        policy = CapabilityResolver().resolve(
            scene={
                # An empty root value deliberately masks any client-provided
                # catalog version when the server has no trusted catalog.
                "catalog_version": catalog.version or "",
                "metadata": request.scene.metadata,
            },
            available_actions=(
                _string_list(capabilities.get("available_actions")) if catalog_matches else []
            ),
            allowed_faces=(
                _string_list(capabilities.get("available_faces")) if catalog_matches else []
            ),
            allowed_state_paths=allowed_state_paths,
            state_tokens=_string_list(capabilities.get("state_tokens")),
            settings=self.settings,
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
            allowed_actions=policy.allowed_actions,
            allowed_faces=policy.allowed_faces,
            allowed_state_paths=sorted(policy.allowed_state_paths),
            state_tokens=sorted(policy.state_tokens),
            response_obligations=_string_list(capabilities.get("response_obligations")),
            policy_digest=policy.digest,
            catalog_version=policy.catalog_version,
            max_tool_calls=policy.budget.max_tool_calls,
            max_specialist_calls=policy.budget.max_specialist_calls,
            max_handoffs=policy.budget.max_handoffs,
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
                "turn_policy": {
                    "digest": policy.digest,
                    "catalog_version": policy.catalog_version,
                    "allowed_actions": [item.value for item in policy.allowed_actions],
                    "allowed_faces": [item.value for item in policy.allowed_faces],
                    "allowed_state_paths": sorted(policy.allowed_state_paths),
                    "state_tokens": sorted(policy.state_tokens),
                    "max_tool_calls": policy.budget.max_tool_calls,
                    "max_specialist_calls": policy.budget.max_specialist_calls,
                    "max_handoffs": policy.budget.max_handoffs,
                },
                "lore": {
                    "mode": "jit",
                    "refs": [],
                    "used_tokens": 0,
                    "used_chars": 0,
                    "cache_hit": False,
                },
                "memory_refs": [memory.memory_id for memory in memories],
            },
            available_lore_refs=(),
        )

    def _character(self, request: TurnRequest) -> tuple[str, str]:
        path = self.character_root / f"{request.npc_id}.json"
        if not path.exists():
            return request.character_core, ""
        payload = json.loads(path.read_text(encoding="utf-8"))
        return str(payload.get("core") or request.character_core), str(payload.get("style") or "")

    def _scene_catalog(self, location: str) -> _SceneCatalog:
        if Path(location).name != location:
            return _SceneCatalog(None, {})
        path = self.scene_root / f"{location}.json"
        if not path.exists():
            return _SceneCatalog(None, {})
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            return _SceneCatalog(None, {})
        if not isinstance(payload, dict):
            return _SceneCatalog(None, {})
        raw_version = payload.get("catalog_version")
        version = raw_version.strip() if isinstance(raw_version, str) else None
        capabilities = payload.get("capabilities", {})
        return _SceneCatalog(
            version or None,
            capabilities if isinstance(capabilities, dict) else {},
        )

    @staticmethod
    def _domain_state_paths(domain_state: NPCDomainState) -> list[str]:
        paths = [f"flags.{name}" for name in domain_state.world_flags]
        paths.extend(f"quests.{quest_id}.status" for quest_id in domain_state.quests)
        if "trust" in domain_state.relationship:
            paths.append("relationship.trust_delta")
        if "affinity" in domain_state.relationship:
            paths.append("relationship.affinity_delta")
        return paths


def _string_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item.strip() for item in value if isinstance(item, str) and item.strip()]
