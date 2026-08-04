from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Literal

from npc_director.prototype.models import (
    FACT_CRATE_CONTAINS_FUSE,
    FACT_GENERATOR_MISSING_FUSE,
    FACT_MANIFEST_FINN_MOVED_C12,
    SceneActionCandidate,
    normalized_success_projection,
    semantic_state_payload,
)
from npc_director.prototype.orchestrator import (
    PrototypeConversationOrchestrator,
    RecordingPrototypeAdapter,
    require_approved,
)
from npc_director.prototype.repository import PrototypeStateRepository


class FakePrototypeRouteHarness:
    """No-model deterministic path exercising the same rules/repository lifecycle."""

    def __init__(self, database: str | Path, session_id: str) -> None:
        self.repository = PrototypeStateRepository(database)
        self.repository.initialize(session_id)
        self.session_id = session_id
        self.adapter = RecordingPrototypeAdapter()
        self.orchestrator = PrototypeConversationOrchestrator(
            self.repository,
            adapter=self.adapter,
        )
        self.sequence = 0
        self.submitted_action_types: list[str] = []

    def close(self) -> None:
        self.repository.close()

    def run(self, route: Literal["cooperation", "procedure"]) -> dict[str, object]:
        self._direct("player", "inspect_object", object_id="gate_console")
        self._action("mechanic_lia", "inspect_object", object_id="generator")

        chain_action_id = self._action(
            "mechanic_lia",
            "tell_npc",
            target_npc_id="guard_captain_maren",
            fact_id=FACT_GENERATOR_MISSING_FUSE,
        )
        if len(self.adapter.internal_reply_plans) != 1:
            raise AssertionError("The common route must create exactly one internal reply")
        self.orchestrator.finish_internal_reply(chain_action_id, "completed")

        if route == "cooperation":
            self._direct(
                "player",
                "tell_npc",
                target_npc_id="porter_finn",
                fact_id=FACT_GENERATOR_MISSING_FUSE,
            )
            self._action(
                "porter_finn",
                "tell_player",
                fact_id=FACT_CRATE_CONTAINS_FUSE,
            )
            self._action(
                "porter_finn",
                "give_item",
                item_id="spare_fuse",
                target_id="mechanic_lia",
                gameplay_intent="cooperation_offer",
            )
        else:
            self._direct("player", "inspect_object", object_id="manifest_board")
            self._direct(
                "player",
                "tell_npc",
                target_npc_id="guard_captain_maren",
                fact_id=FACT_MANIFEST_FINN_MOVED_C12,
            )
            self._action(
                "guard_captain_maren",
                "authorize_object",
                object_id="cargo_crate_c12",
                gameplay_intent="request_authorization",
            )
            self._action(
                "porter_finn",
                "give_item",
                item_id="spare_fuse",
                target_id="mechanic_lia",
            )

        self._action(
            "mechanic_lia",
            "install_item",
            object_id="generator",
            item_id="spare_fuse",
        )
        self._action(
            "guard_captain_maren",
            "authorize_object",
            object_id="control_cabinet",
        )
        self._action(
            "guard_captain_maren",
            "operate_object",
            object_id="control_cabinet",
            operation="restart_gate_power",
        )

        world = self.repository.get_world(self.session_id)
        npc_states = self.repository.get_npcs(self.session_id)
        semantic_payload = semantic_state_payload(world, npc_states)
        semantic_hash = hashlib.sha256(
            json.dumps(
                semantic_payload,
                ensure_ascii=False,
                separators=(",", ":"),
                sort_keys=True,
            ).encode()
        ).hexdigest()
        world_version_sequence = [
            int(item.rsplit(":v", maxsplit=1)[1])
            for item in self.orchestrator.timeline
            if item.startswith("commit:")
        ]
        return {
            "route": route,
            "objective_state": world.objective_state,
            "semantic_state_hash": semantic_hash,
            "normalized_success_projection": normalized_success_projection(world),
            "world_version": world.version,
            "world_version_sequence": world_version_sequence,
            "action_plan_count": len(self.adapter.action_plans),
            "internal_reply_plan_count": len(self.adapter.internal_reply_plans),
            "total_plan_count_for_chain": 2,
            "commit_count": self.repository.count_commits(session_id=self.session_id),
            "submitted_action_types": self.submitted_action_types,
            "input_locked": self.orchestrator.is_input_locked(self.session_id),
            "timeline": self.orchestrator.timeline,
        }

    def _candidate(self, actor_id: str, action_type: str, **kwargs: object) -> SceneActionCandidate:
        self.sequence += 1
        self.submitted_action_types.append(action_type)
        action_id = f"{self.session_id}:a{self.sequence}"
        return SceneActionCandidate(
            session_id=self.session_id,
            turn_id=f"{self.session_id}:t{self.sequence}",
            action_id=action_id,
            actor_id=actor_id,
            action_type=action_type,
            **kwargs,
        )

    def _direct(self, actor_id: str, action_type: str, **kwargs: object) -> str:
        candidate = self._candidate(actor_id, action_type, **kwargs)
        before = len(self.adapter.action_plans)
        result = self.orchestrator.submit(candidate)
        require_approved(result)
        if result.commit is None:
            raise AssertionError("Direct action must commit without a Unity adapter plan")
        if len(self.adapter.action_plans) != before:
            raise AssertionError("Direct player ingest must not enter the adapter")
        return candidate.action_id

    def _action(self, actor_id: str, action_type: str, **kwargs: object) -> str:
        candidate = self._candidate(actor_id, action_type, **kwargs)
        result = self.orchestrator.submit(candidate)
        key = require_approved(result)
        if result.commit is not None:
            raise AssertionError("NPC scene action must wait for completed")
        self.orchestrator.handle_action_event(candidate.action_id, key, "ack")
        self.orchestrator.handle_action_event(candidate.action_id, key, "started")
        self.orchestrator.handle_action_event(candidate.action_id, key, "completed")
        return candidate.action_id
