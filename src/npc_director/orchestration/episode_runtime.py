"""Integrate durable actor episodes with the existing one-beat service contract."""

from __future__ import annotations

import asyncio
import hashlib
import json
from collections.abc import Callable
from dataclasses import replace
from typing import Any
from uuid import uuid4

from npc_director.context.characters import CharacterRegistry
from npc_director.contracts import (
    DirectorInput,
    TurnRequest,
    TurnStatus,
)
from npc_director.contracts.content import ContentPolicy, ExistingQuest, ObjectiveRef
from npc_director.contracts.episodes import (
    DialogueEvent,
    DialogueState,
    EpisodeBudget,
    EpisodeJob,
    EpisodeRecord,
    EpisodeRequest,
    KnowledgeClaim,
    NpcMessage,
)
from npc_director.orchestration.turn_policy import StateCapabilities
from npc_director.state._sqlite import datetime_text, json_dumps
from npc_director.state.errors import IdempotencyConflictError

_TERMINAL = {"completed", "cancelled", "failed", "unsupported", "budget_exhausted", "no_progress"}
_TURN_TERMINAL = {TurnStatus.COMPLETED, TurnStatus.INTERRUPTED, TurnStatus.FAILED}


def _id(prefix: str, *parts: str) -> str:
    return prefix + ":" + hashlib.sha256("\0".join(parts).encode()).hexdigest()[:40]


def _dump(value: Any) -> Any:
    return value.model_dump(mode="json") if hasattr(value, "model_dump") else value


class EpisodeRuntime:
    """Only trusted events create work; there is no periodic model-thinking loop."""

    def __init__(self, service, store, content_store=None) -> None:
        self.service = service
        self.store = store
        self.content_store = content_store
        self.registry = (
            service.context_builder.character_registry
            or CharacterRegistry.from_directory(service.settings.character_path)
        )
        self._adapters: dict[str, object] = {}
        self._default_adapter = None
        self._locks: dict[str, asyncio.Lock] = {}
        self.worker_id = "director-" + uuid4().hex
        with store.transaction() as connection:
            connection.execute(
                """CREATE TABLE IF NOT EXISTS episode_turn_links (
                turn_id TEXT PRIMARY KEY, episode_id TEXT NOT NULL, session_id TEXT NOT NULL,
                npc_id TEXT NOT NULL, job_id TEXT NOT NULL, request_json TEXT NOT NULL,
                stimulus_json TEXT NOT NULL, generation_json TEXT, created_at TEXT NOT NULL)"""
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_episode_turn_links_episode "
                "ON episode_turn_links(episode_id)"
            )
            columns = {
                row[1] for row in connection.execute("PRAGMA table_info(episode_turn_links)")
            }
            if "delivery_status" not in columns:
                connection.execute(
                    "ALTER TABLE episode_turn_links ADD COLUMN delivery_status "
                    "TEXT DEFAULT 'unknown'"
                )
            connection.execute(
                """CREATE TABLE IF NOT EXISTS dialogue_memory_jobs (
                turn_id TEXT PRIMARY KEY, session_id TEXT NOT NULL, status TEXT NOT NULL,
                attempts INTEGER NOT NULL DEFAULT 0, last_error TEXT, updated_at TEXT NOT NULL)"""
            )

    def attach_adapter(self, adapter, *, session_id: str | None = None) -> None:
        if session_id is None:
            self._default_adapter = adapter
        else:
            self._adapters[session_id] = adapter

    def _lock(self, session_id: str) -> asyncio.Lock:
        return self._locks.setdefault(session_id, asyncio.Lock())

    def episode_for_turn(self, turn_id: str) -> EpisodeRecord | None:
        link = self._link(turn_id)
        return None if link is None else self.store.get_episode(link["episode_id"])

    def _link(self, turn_id: str) -> dict | None:
        with self.store.connection() as connection:
            row = connection.execute(
                "SELECT * FROM episode_turn_links WHERE turn_id = ?", (turn_id,)
            ).fetchone()
        return dict(row) if row is not None else None

    def _update(self, episode_id: str, update: Callable[[EpisodeRecord], EpisodeRecord]):
        with self.store.transaction() as connection:
            record = self.store.get_in_connection(connection, episode_id)
            return self.store.save_in_connection(connection, update(record))

    def _budget(self) -> EpisodeBudget:
        settings = self.service.settings
        return EpisodeBudget(
            max_model_calls=getattr(settings, "max_model_calls", 32),
            max_nodes=getattr(settings, "max_execution_nodes", 32),
            max_plan_revisions=getattr(settings, "max_plan_revisions", 2),
            max_participants=settings.max_episode_participants,
            max_npc_turns=settings.max_autonomous_turns,
            max_new_quests=settings.max_new_quests,
            max_total_tokens=settings.max_total_tokens,
            max_repairs=settings.max_node_repairs,
            max_active_seconds=settings.planning_timeout_seconds,
        )

    def _participants(self, request: EpisodeRequest) -> list[str]:
        self.registry.require(request.npc_id)
        roster = self.registry.roster(request.scene.location, current_npc_id=request.npc_id)
        available = {entry["npc_id"] for entry in roster}
        if any(npc_id not in available for npc_id in request.participants):
            raise ValueError("episode participants must be registered in the current scene")
        selected = request.participants or [entry["npc_id"] for entry in roster]
        return list(dict.fromkeys([request.npc_id, *selected]))[: self._budget().max_participants]

    async def run_player_turn(self, request: TurnRequest, *, adapter):
        self.attach_adapter(adapter, session_id=request.session_id)
        existing = await self.service.turn_store.aget(request.turn_id)
        if existing is not None:
            if existing.request != request:
                raise IdempotencyConflictError("turn id was reused with different player input")
            # Old records keep their original storage and policy recovery path.
            if self._link(request.turn_id) is None or existing.status is not TurnStatus.RUNNING:
                return await self.service._run_single_turn(request, adapter=adapter)
        if self._link(request.turn_id) is None:
            # Preempt before waiting for an in-flight model call's session lock.
            for old in self.store.list_episodes(request.session_id, active_only=True):
                self._cancel(old.id)
        async with self._lock(request.session_id):
            if self._link(request.turn_id) is None:
                event = EpisodeRequest(
                    event_id=request.turn_id,
                    session_id=request.session_id,
                    npc_id=request.npc_id,
                    text=request.player_input,
                    scene=request.scene,
                )
                self._start(event, request=request, preempt=True)
            await self._drain(request.session_id)
            turn = await self.service.turn_store.aget(request.turn_id)
            if turn is None:
                turn = await self.service.turn_store.astart_turn(request)
            return self.service._execution_result(turn)

    async def start_episode(self, request: EpisodeRequest | dict, *, adapter) -> EpisodeRecord:
        event = EpisodeRequest.model_validate(request)
        self.attach_adapter(adapter, session_id=event.session_id)
        async with self._lock(event.session_id):
            episode = self._start(event, preempt=event.origin == "player")
            await self._drain(event.session_id)
            return self.store.get_episode(episode.id)

    async def publish_event(self, request: EpisodeRequest | dict, *, adapter) -> EpisodeRecord:
        event = EpisodeRequest.model_validate(request)
        if event.origin == "player":
            raise ValueError("use run_turn or start_episode for player input")
        if event.origin == "npc":
            # Model-generated NPC messages must travel through a completed parent beat.
            raise ValueError("NPC messages are created by completed delivery, not publish_event")
        return await self.start_episode(event, adapter=adapter)

    def _start(self, event: EpisodeRequest, *, request=None, preempt=False) -> EpisodeRecord:
        if event.origin == "npc":
            raise ValueError("external episode origins must be player or trusted world_event")
        event = event.model_copy(
            update={
                "participants": self._participants(event),
                "speaker_id": "world" if event.origin == "world_event" else "player",
            }
        )
        with self.store.connection() as conn:
            already_existed = (
                conn.execute(
                    "SELECT 1 FROM episodes WHERE session_id=? AND event_id=?",
                    (event.session_id, event.event_id),
                ).fetchone()
                is not None
            )
        episode = self.store.create_episode(event, budget=self._budget())
        if "cognition_version" not in episode.artifacts:
            episode = self._update(
                episode.id,
                lambda e: e.model_copy(
                    update={
                        "artifacts": {
                            **e.artifacts,
                            "cognition_version": "memory-v1"
                            if self.service.settings.cognition_enabled and not already_existed
                            else "off",
                        }
                    }
                ),
            )
        jobs = self.store.list_jobs(episode.id)
        if self.content_store is not None:
            root_objective = ObjectiveRef(objective_id=_id("objective", episode.id, "root"))
            self.content_store.register_objective(event.session_id, root_objective)
            episode = self._update(
                episode.id,
                lambda e: e.model_copy(
                    update={
                        "artifacts": {
                            **e.artifacts,
                            "root_objective": root_objective.model_dump(mode="json"),
                        }
                    }
                ),
            )
        if preempt and not jobs:
            for old in self.store.list_episodes(event.session_id, active_only=True):
                if old.id != episode.id:
                    self._cancel(old.id)
        turn_id = request.turn_id if request is not None else _id("turn", episode.id, "root")
        message = NpcMessage(
            speaker_id=event.speaker_id,
            target_npc_id=event.npc_id,
            text=event.text,
            purpose="respond to triggering event",
        )
        job = self.store.queue_job(
            episode.id,
            message,
            source_event_id=event.event_id,
            dedupe_key="root",
            turn_id=turn_id,
        )
        if request is None:
            request = self._request_for_job(episode, job)
        self._bind(episode, job, request, event.model_dump(mode="json"))
        self.store.record_event(
            episode.id, event.event_id, event.origin, event.model_dump(mode="json")
        )
        if event.origin == "world_event":
            for claim in event.claims:
                self.store.grant_knowledge(
                    event.session_id, event.npc_id, claim, source_event_id=event.event_id
                )
        self.store.record_dialogue(
            DialogueEvent(
                event_id=_id("input", episode.id, turn_id),
                session_id=event.session_id,
                turn_id=turn_id,
                speaker_id=event.speaker_id,
                audience=[event.npc_id],
                text=event.text,
                origin=event.origin,
                status="received",
                episode_id=episode.id,
            )
        )
        self.service.turn_store.start_turn(request)
        return episode

    def _request_for_job(self, episode: EpisodeRecord, job: EpisodeJob) -> TurnRequest:
        profile = self.registry.require(job.message.target_npc_id)
        return TurnRequest(
            session_id=episode.session_id,
            turn_id=job.turn_id,
            npc_id=profile.npc_id,
            player_input=job.message.text,
            scene=episode.request.scene,
            character_core=profile.core,
        )

    def _bind(self, episode, job, request, stimulus) -> None:
        stimulus = {
            **stimulus,
            "cognition_version": episode.artifacts.get("cognition_version", "off"),
        }
        with self.store.transaction() as connection:
            connection.execute(
                "INSERT OR IGNORE INTO episode_turn_links "
                "(turn_id,episode_id,session_id,npc_id,job_id,request_json,"
                "stimulus_json,created_at) "
                "VALUES (?,?,?,?,?,?,?,?)",
                (
                    request.turn_id,
                    episode.id,
                    request.session_id,
                    request.npc_id,
                    job.job_id,
                    request.model_dump_json(),
                    json_dumps(stimulus),
                    datetime_text(),
                ),
            )

    async def resume(self, session_id: str) -> None:
        async with self._lock(session_id):
            await self._drain(session_id)
        await self.retry_memory_jobs(session_id)

    async def _drain(self, session_id: str) -> None:
        adapter = self._adapters.get(session_id, self._default_adapter)
        if adapter is None:
            return
        # claim_job also enforces a database lease across separate service workers.
        for _ in range(16):
            job = self.store.claim_job(
                session_id=session_id,
                worker_id=self.worker_id,
                lease_seconds=max(240, self.service.settings.timeout_seconds * 4),
            )
            if job is None:
                return
            episode = self.store.get_episode(job.episode_id)
            link = self._link(job.turn_id)
            request = (
                TurnRequest.model_validate_json(link["request_json"])
                if link is not None
                else self._request_for_job(episode, job)
            )
            if link is None:
                self._bind(
                    episode,
                    job,
                    request,
                    {
                        "origin": "npc",
                        "speaker_id": job.message.speaker_id,
                        "target_npc_id": job.message.target_npc_id,
                        "text": job.message.text,
                        "purpose": job.message.purpose,
                        "source_event_id": job.source_event_id,
                        "parent_turn_id": job.parent_turn_id,
                        "message_kind": job.message.message_kind,
                        "in_reply_to": job.message.in_reply_to,
                    },
                )
            origin = json.loads(self._link(job.turn_id)["stimulus_json"])["origin"]
            if origin != "player" and not await self.store.reserve_npc_turn(
                episode.id, operation_id="npc-turn:" + job.turn_id
            ):
                self.store.update_job(job.job_id, "cancelled", worker_id=self.worker_id)
                self._update(
                    episode.id,
                    lambda e: e.model_copy(
                        update={
                            "status": "budget_exhausted",
                            "stop_reason": "autonomous turn budget exhausted",
                        }
                    ),
                )
                continue
            self._update(
                episode.id,
                lambda e, turn_id=job.turn_id: e.model_copy(update={"active_turn_id": turn_id}),
            )
            try:
                result = await self.service._run_single_turn(request, adapter=adapter)
            except Exception:
                current_job = self.store.get_job(job.job_id)
                if current_job.status == "cancelled":
                    turn = await self.service.turn_store.aget(job.turn_id)
                    if turn is not None and turn.status not in _TURN_TERMINAL:
                        turn = await self.service.turn_store.aupdate_status(
                            job.turn_id, TurnStatus.INTERRUPTED
                        )
                        self.interrupt_turn(turn)
                    continue
                if current_job.status not in {"cancelled", "failed", "completed"}:
                    self.store.update_job(job.job_id, "failed", worker_id=self.worker_id)
                self._update(
                    episode.id,
                    lambda e: e.model_copy(
                        update={
                            "status": "failed",
                            "active_turn_id": None,
                            "stop_reason": "generation failed",
                        }
                    ),
                )
                raise
            current_job = self.store.get_job(job.job_id)
            if current_job.status in {"cancelled", "failed", "completed"}:
                continue
            if result.status in _TURN_TERMINAL:
                self.store.update_job(
                    job.job_id,
                    "completed" if result.status is TurnStatus.COMPLETED else "failed",
                    worker_id=self.worker_id,
                )
                self._update(episode.id, lambda e: e.model_copy(update={"active_turn_id": None}))
                continue
            waiting = (
                "pending_approval" if result.status is TurnStatus.PENDING_APPROVAL else "waiting"
            )
            self.store.update_job(job.job_id, waiting, worker_id=self.worker_id)
            self._update(
                episode.id,
                lambda e, waiting=waiting: e.model_copy(
                    update={
                        "status": (
                            "waiting_for_approval"
                            if waiting == "pending_approval"
                            else "waiting_for_completion"
                        )
                        if e.status not in _TERMINAL
                        else e.status,
                    }
                ),
            )
            return

    def decorate_context(
        self, request: TurnRequest, director_input: DirectorInput
    ) -> DirectorInput:
        link = self._link(request.turn_id)
        if link is None:
            return director_input
        episode = self.store.get_episode(link["episode_id"])
        engaged = {
            episode.request.npc_id,
            *(
                job.message.target_npc_id
                for job in self.store.list_jobs(episode.id)
                if job.parent_turn_id is not None
            ),
        }
        actor_context = {
            **director_input.actor_context,
            "episode_goal": episode.request.text,
            "conversation_initiator": episode.request.npc_id,
            "conversation_audience": sorted(engaged),
            "scheduled_speakers": [
                {"npc_id": job.message.target_npc_id, "status": job.status}
                for job in self.store.list_jobs(episode.id)
                if job.turn_id != request.turn_id and job.status in {"queued", "claimed", "waiting"}
            ],
        }
        update = {
            "episode_id": episode.id,
            "stimulus": json.loads(link["stimulus_json"]),
            "execution_budget": episode.remaining_budget(),
            "actor_context": actor_context,
        }
        stimulus = update["stimulus"]
        if stimulus.get("origin") == "npc":
            sender = stimulus.get("speaker_id")
            relationships = director_input.actor_context.get("relationships", [])
            relationship = next(
                (
                    item.get("values", {})
                    for item in relationships
                    if item.get("target_actor_id") == sender
                ),
                {},
            )
            update["relationship_summary"] = json_dumps({"target_npc_id": sender, **relationship})
        if self.content_store is not None:
            update["content_policy"] = self.content_policy(request, director_input).model_dump(
                mode="json"
            )
            known = director_input.actor_context.get("known_claims", [])
            visible = self.content_store.visible_context(
                request.session_id,
                request.npc_id,
                known_content_ids=[item["content_id"] for item in known if "content_id" in item],
            )
            update["actor_context"] = {**actor_context, "published_content": visible}
            prior_plans = self.content_store.list_objective_plans(
                request.session_id,
                request.npc_id,
                parent_refs=[
                    ObjectiveRef.model_validate(ref)
                    for ref in update["content_policy"]["objective_refs"]
                ],
            )
            if prior_plans:
                update["actor_context"]["objective_plans"] = prior_plans
        return director_input.model_copy(update=update)

    def content_policy(self, request: TurnRequest, director_input: DirectorInput) -> ContentPolicy:
        raw = director_input.content_policy or {}
        profile = self.registry.require(request.npc_id)
        state = self.service.domain_store.get_or_create(
            request.npc_id, session_id=request.session_id
        )
        refs = [
            self.content_store.get_objective(request.session_id, key)
            or ObjectiveRef(objective_id=key, quest_id=key, version=0)
            for key in state.quests
        ]
        existing = [
            ExistingQuest(
                ref=ref, objective_key=ref.key, summary=ref.key, status=state.quests[ref.key]
            )
            for ref in refs
        ]
        episode = self.episode_for_turn(request.turn_id)
        if episode is not None and episode.artifacts.get("root_objective"):
            refs.append(ObjectiveRef.model_validate(episode.artifacts["root_objective"]))
        known_claims = director_input.actor_context.get("known_claims", [])
        visible = self.content_store.visible_context(
            request.session_id,
            request.npc_id,
            known_content_ids=[item["content_id"] for item in known_claims],
        )
        visible_ids = {item["content_id"] for item in visible}
        for quest in self.content_store.list_quests(request.session_id, request.npc_id):
            if quest.content_id not in visible_ids:
                continue
            ref = ObjectiveRef(
                objective_id=quest.quest_id, quest_id=quest.quest_id, version=quest.version
            )
            refs = [item for item in refs if item.key != ref.key] + [ref]
            existing = [item for item in existing if item.ref.key != ref.key] + [
                ExistingQuest(ref=ref, objective_key=quest.objective_key, status=quest.status)
            ]
        for ref in refs:
            self.content_store.register_objective(request.session_id, ref)
        return ContentPolicy(
            session_id=request.session_id,
            npc_id=request.npc_id,
            catalog_version=director_input.catalog_version or "unknown",
            policy_digest=director_input.policy_digest or "",
            allowed_kinds=raw.get("allowed_kinds", []),
            allowed_actions=raw.get("allowed_actions", []),
            allowed_reward_types=raw.get("allowed_reward_types", []),
            objective_refs=refs,
            existing_quests=existing,
            hard_constraints=[*profile.boundaries, *raw.get("hard_constraints", [])],
            max_new_quests=self.service.settings.max_new_quests,
        )

    def record_generation(self, request, result, policy, *, content_policy=None):
        link = self._link(request.turn_id)
        if link is None:
            return policy
        payload = {
            "trace": _dump(result.execution_trace),
            "messages": [_dump(item) for item in result.collaboration_messages],
            "dialogue_state_delta": _dump(result.dialogue_state_delta),
            "cognitive_commit": result.cognitive_commit,
            "content_candidates": [_dump(item) for item in result.content_candidates],
            "objective_steps": [_dump(item) for item in result.objective_steps],
            "objective_events": [_dump(item) for item in result.objective_events],
            "objective_plan_policy": {
                "objective_refs": (content_policy or {}).get("objective_refs", []),
                "allowed_actions": (content_policy or {}).get("allowed_actions", []),
            },
        }
        with self.store.transaction() as connection:
            connection.execute(
                "UPDATE episode_turn_links SET generation_json = ? WHERE turn_id = ?",
                (json_dumps(payload), request.turn_id),
            )
        if self.content_store is not None:
            staged = self.content_store.get_staged_for_turn(request.session_id, request.turn_id)
            paths = set(policy.allowed_state_paths)
            for item in staged:
                paths.update(item.allowed_state_paths)
            policy = replace(
                policy,
                state=StateCapabilities(allowed_paths=frozenset(paths), tokens=policy.state.tokens),
            )
            if staged:
                self.content_store.freeze_turn_policy(
                    request.session_id, request.turn_id, policy.digest
                )
        return policy

    def _outgoing(self, turn, episode, generation) -> list[NpcMessage]:
        if episode.status in _TERMINAL:
            return []
        roster = set(episode.request.participants) | {episode.request.npc_id}
        known = self.store.get_context(turn.session_id, turn.npc_id)["knowledge"]
        known_refs = {item["content_id"]: item for item in known}
        domain = self.service.domain_store.get_or_create(turn.npc_id, session_id=turn.session_id)
        evidence_fingerprint = _id(
            "evidence",
            json_dumps(
                {
                    "knowledge": sorted(
                        {
                            (item["content_id"], item["text"], item["epistemic_status"])
                            for item in known
                        }
                    ),
                    "flags": domain.world_flags,
                    "quests": domain.quests,
                }
            ),
        )
        messages = []
        for raw in generation.get("messages", []):
            target = raw.get("target_npc_id")
            if target not in roster or target == turn.npc_id:
                continue
            if any(
                job.message.target_npc_id == target
                and job.turn_id != turn.turn_id
                and job.status in {"queued", "claimed", "waiting"}
                for job in self.store.list_jobs(episode.id)
            ):
                # The existing pending actor will read this just-delivered
                # utterance in its own history. Do not enqueue a duplicate beat.
                generation.setdefault("coalesced_audience", []).append(target)
                continue
            claims = []
            used_refs = (generation.get("dialogue_state_delta") or {}).get("used_fact_refs", [])
            for ref in set(raw.get("claim_refs", [])) | set(used_refs):
                if ref in known_refs:
                    claim = KnowledgeClaim.model_validate(known_refs[ref])
                    if claim.shareable:
                        claims.append(
                            claim.model_copy(
                                update={
                                    "epistemic_status": "reported",
                                    "text": turn.directive.dialogue.text,
                                    "source_npc_id": turn.npc_id,
                                }
                            )
                        )
            message = NpcMessage(
                speaker_id=turn.npc_id,
                target_npc_id=target,
                text=turn.directive.dialogue.text,
                purpose=raw.get("purpose", ""),
                claims=claims,
                audience=["player", target],
                message_kind=raw.get("speech_act", "ask"),
                reply_requested=raw.get("speech_act", "ask") in {"ask", "propose"},
                evidence_fingerprint=evidence_fingerprint,
            )
            # Same question to the same actor without new information terminates a loop.
            prior = self.store.list_jobs(episode.id)
            signature = (message.speaker_id, target, message.purpose)
            if any(
                (job.message.speaker_id, job.message.target_npc_id, job.message.purpose)
                == signature
                and job.status == "completed"
                and job.message.evidence_fingerprint == evidence_fingerprint
                for job in prior
            ):
                continue
            messages.append(message)
        return messages[:3]

    async def complete_turn(self, turn, event, policy) -> None:
        link = self._link(turn.turn_id)
        episode = self.store.get_episode(link["episode_id"])
        generation = json.loads(link["generation_json"] or "{}")
        messages = self._outgoing(turn, episode, generation)
        incoming_job = self.store.get_job(link["job_id"])
        reply_outcome = (generation.get("dialogue_state_delta") or {}).get(
            "reply_outcome", "partial"
        )
        reply_to = None
        if (
            incoming_job.message.reply_requested
            and incoming_job.parent_turn_id is not None
            and incoming_job.message.speaker_id in episode.request.participants
            and episode.status not in _TERMINAL
        ):
            reply_to = incoming_job.message.speaker_id
            siblings = self.store.list_jobs(episode.id)
            pending_reply = any(
                job.message.message_kind == "reply"
                and job.message.target_npc_id == reply_to
                and job.message.in_reply_to == incoming_job.parent_turn_id
                and job.status in {"queued", "claimed"}
                for job in siblings
            )
            coordinator_will_summarize = reply_to != episode.request.npc_id and any(
                job.message.message_kind == "reply"
                and job.message.target_npc_id == episode.request.npc_id
                and job.status in {"queued", "claimed"}
                for job in siblings
            )
            if (
                reply_outcome != "pending"
                and not pending_reply
                and not coordinator_will_summarize
                and not any(message.target_npc_id == reply_to for message in messages)
            ):
                messages.append(
                    NpcMessage(
                        speaker_id=turn.npc_id,
                        target_npc_id=reply_to,
                        text=turn.directive.dialogue.text,
                        purpose="回应先前的询问，并让发起者综合已收到的信息",
                        message_kind="reply",
                        in_reply_to=incoming_job.parent_turn_id,
                    )
                )
        context = self.store.get_context(turn.session_id, turn.npc_id)
        state = DialogueState.model_validate(context["dialogue_state"])
        delta = generation.get("dialogue_state_delta") or {}
        delivered_claims = {
            claim.content_id: claim for message in messages for claim in message.claims
        }
        for known in context["knowledge"]:
            if known["content_id"] in delta.get("used_fact_refs", []) and known.get("shareable"):
                claim = KnowledgeClaim.model_validate(known).model_copy(
                    update={
                        "text": turn.directive.dialogue.text,
                        "epistemic_status": "reported",
                        "source_npc_id": turn.npc_id,
                    }
                )
                delivered_claims[claim.content_id] = claim
        trace = generation.get("trace") or {}
        analysis = trace.get("analysis") or {}
        commitments = list(state.commitments)
        verified_refs = {
            item["content_id"]
            for item in context["knowledge"]
            if item.get("epistemic_status") in {"observed", "verified"}
        }
        has_completion_evidence = any(
            goal.get("completion_basis") == "observed_event"
            and set(goal.get("evidence_refs", [])) & verified_refs
            for goal in analysis.get("goals", [])
        )
        if has_completion_evidence:
            for commitment in commitments:
                if commitment.get("text") in delta.get("resolved_commitments", []):
                    commitment.update(status="fulfilled", resolved_by_turn=turn.turn_id)
        for text in delta.get("proposed_commitments", []):
            if not any(item.get("text") == text for item in commitments):
                commitments.append({"text": text, "source_turn_id": turn.turn_id, "status": "open"})
        referents = dict(state.referents)
        for reference in delta.get("referent_updates", []):
            if reference.get("resolved") and reference.get("target_id"):
                referents[reference["meaning"]] = reference["target_id"]
        state = state.model_copy(
            update={
                "topic": analysis.get("objective", state.topic),
                "open_questions": delta.get("pending_questions", state.open_questions),
                "pending_intents": delta.get("open_goals", state.pending_intents),
                "commitments": commitments[-32:],
                "referents": referents,
                "emotion": turn.directive.emotion.model_dump(mode="json"),
                "recent_expressions": [*state.recent_expressions, turn.directive.dialogue.text][
                    -12:
                ],
            }
        )
        audience = list(
            dict.fromkeys(
                [
                    "player",
                    *(m.target_npc_id for m in messages),
                    *([reply_to] if reply_to else []),
                    *generation.get("coalesced_audience", []),
                    # A gathered conversation hears its completed foreground
                    # replies. Potential registry actors who never joined do
                    # not gain access, and hearing alone does not schedule them.
                    episode.request.npc_id,
                    *(
                        job.message.target_npc_id
                        for job in self.store.list_jobs(episode.id)
                        if job.parent_turn_id is not None
                    ),
                ]
            )
        )
        dialogue = DialogueEvent(
            event_id=_id("spoken", episode.id, turn.turn_id),
            session_id=turn.session_id,
            turn_id=turn.turn_id,
            speaker_id=turn.npc_id,
            audience=audience,
            text=turn.directive.dialogue.text,
            episode_id=episode.id,
            claims=list(delivered_claims.values()),
        )
        published_quests = (
            {quest.quest_id: quest for quest in self.content_store.list_quests(turn.session_id)}
            if self.content_store is not None
            else {}
        )

        def commit(connection):
            stimulus = json.loads(link["stimulus_json"])
            changes = turn.proposal.plan.proposed_state_changes
            if stimulus.get("origin") == "npc" and changes.relationship is not None:
                sender = stimulus["speaker_id"]
                previous = next(
                    (
                        item
                        for item in context["relationships"]
                        if item["target_actor_id"] == sender
                    ),
                    {},
                )
                values = dict(previous.get("values", {}))
                values["trust"] = values.get("trust", 0) + changes.relationship.trust_delta
                values["affinity"] = values.get("affinity", 0) + changes.relationship.affinity_delta
                self.store.set_relationship(
                    turn.session_id,
                    turn.npc_id,
                    sender,
                    values,
                    expected_version=previous.get("version", 0),
                    connection=connection,
                )
                changes = changes.model_copy(update={"relationship": None})
            domain_result = self.service.domain_store.commit_completed_in_connection(
                connection,
                turn.turn_id,
                turn.npc_id,
                changes,
                expected_version=turn.domain_version,
                allowed_paths=policy.allowed_state_paths,
                session_id=turn.session_id,
            )
            published = []
            if self.content_store is not None:
                if generation.get("objective_steps") or generation.get("objective_events"):
                    from npc_director.contracts.content import ObjectiveEvent, ObjectiveStep

                    if not self.readonly_quality_approved(turn.turn_id):
                        raise ValueError(
                            "parent plan definitions require successful quality review"
                        )
                    plan_policy = generation.get("objective_plan_policy", {})
                    self.content_store.save_objective_plan_in_connection(
                        connection,
                        turn.session_id,
                        turn.npc_id,
                        turn.turn_id,
                        _id("objective-plan", turn.turn_id),
                        steps=[
                            ObjectiveStep.model_validate(x) for x in generation["objective_steps"]
                        ],
                        events=[
                            ObjectiveEvent.model_validate(x) for x in generation["objective_events"]
                        ],
                        current_objective_refs=[
                            ObjectiveRef.model_validate(x) for x in plan_policy["objective_refs"]
                        ],
                        allowed_actions=plan_policy["allowed_actions"],
                    )
                published = self.content_store.publish_turn_in_connection(
                    connection, turn.session_id, turn.turn_id, expected_policy_digest=policy.digest
                )
                for content in published:
                    self.store.grant_knowledge(
                        turn.session_id,
                        turn.npc_id,
                        KnowledgeClaim(
                            content_id=content.content_id,
                            text=content.candidate.summary,
                            # Narrative prose may describe a belief or a lie. Only
                            # explicitly typed world facts establish canonical truth.
                            epistemic_status="reported",
                            shareable=content.candidate.visibility == "public",
                            source_npc_id=turn.npc_id,
                            expires_at=content.candidate.expires_at,
                        ),
                        source_event_id=_id("publication", turn.turn_id, content.content_id),
                        connection=connection,
                    )
                for patch in turn.proposal.plan.proposed_state_changes.quests:
                    prior = published_quests.get(patch.quest_id)
                    if prior is not None and prior.status != patch.status:
                        self.content_store.advance_quest_in_connection(
                            connection,
                            turn.session_id,
                            patch.quest_id,
                            _id("quest-event", turn.turn_id, patch.quest_id),
                            patch.status,
                        )
            completed = turn.model_copy(update={"status": TurnStatus.COMPLETED})
            connection.execute(
                "UPDATE turns SET status = ?, record_json = ?, revision = revision + 1, "
                "updated_at = ? WHERE turn_id = ?",
                (
                    completed.status.value,
                    completed.model_dump_json(),
                    datetime_text(),
                    turn.turn_id,
                ),
            )
            connection.execute(
                "INSERT OR IGNORE INTO dialogue_memory_jobs "
                "(turn_id,session_id,status,updated_at) VALUES(?,?, 'pending', ?)",
                (turn.turn_id, turn.session_id, datetime_text()),
            )
            terminal = {
                "budget_exhausted": "budget_exhausted",
                "deadline": "budget_exhausted",
                "node_failed": "failed",
                "invalid_plan": "failed",
                "quality_failed": "failed",
                "unsupported": "unsupported",
                "no_progress": "no_progress",
            }.get(trace.get("stop_reason"))
            current_episode = self.store.get_in_connection(connection, episode.id)
            if terminal is not None and current_episode.status not in _TERMINAL:
                self.store.save_in_connection(
                    connection,
                    current_episode.model_copy(
                        update={
                            "status": terminal,
                            "stop_reason": trace["stop_reason"],
                            "active_turn_id": None,
                        }
                    ),
                )
            return {
                "domain_version": domain_result.version,
                "published": [_dump(item) for item in published],
            }

        await asyncio.to_thread(
            self.store.commit_completed,
            episode.id,
            turn.turn_id,
            dialogue=dialogue,
            dialogue_state=state,
            next_messages=messages,
            event_id=_id("completed", episode.id, turn.turn_id),
            idempotency_key=event.idempotency_key,
            callback=commit,
            finish_episode=(
                not messages
                and reply_outcome != "pending"
                and not state.open_questions
                and not state.pending_intents
                and not any(
                    job.turn_id != turn.turn_id
                    and job.status in {"queued", "claimed", "waiting", "pending_approval"}
                    for job in self.store.list_jobs(episode.id)
                )
            ),
            waiting_status="waiting_for_event"
            if reply_outcome == "pending"
            else "waiting_for_player",
        )

    def interrupt_turn(self, turn) -> None:
        link = self._link(turn.turn_id)
        if link is None:
            return
        job = self.store.get_job(link["job_id"])
        if job.status not in {"completed", "cancelled", "failed"}:
            self.store.update_job(link["job_id"], "cancelled")
        if self.content_store is not None:
            self.content_store.discard_turn(turn.session_id, turn.turn_id)
        self._update(
            link["episode_id"],
            lambda e: e.model_copy(
                update={
                    "status": "cancelled",
                    "stop_reason": "performance interrupted",
                    "active_turn_id": None,
                }
            ),
        )

    async def cancel_episode(self, episode_id: str) -> EpisodeRecord:
        return self._cancel(episode_id, reason="explicit cancellation")

    def _cancel(self, episode_id: str, *, reason: str = "player_preempted") -> EpisodeRecord:
        with self.store.transaction() as connection:
            episode = self.store.cancel_episode(episode_id, reason=reason, connection=connection)
            rows = connection.execute(
                "SELECT j.record_json,l.delivery_status FROM episode_jobs j "
                "LEFT JOIN episode_turn_links l ON j.turn_id=l.turn_id WHERE j.episode_id=?",
                (episode_id,),
            ).fetchall()
            for row in rows:
                job = EpisodeJob.model_validate_json(row["record_json"])
                if job.status == "waiting" and row["delivery_status"] == "queued":
                    job = job.model_copy(update={"status": "cancelled"})
                    self.store._save_job(connection, job)
                if job.status == "cancelled":
                    if self.content_store is not None:
                        self.content_store.discard_turn_in_connection(
                            connection, episode.session_id, job.turn_id
                        )
                    turn_row = connection.execute(
                        "SELECT record_json FROM turns WHERE turn_id=?", (job.turn_id,)
                    ).fetchone()
                    if turn_row is not None:
                        record = json.loads(turn_row["record_json"])
                        if record["status"] not in {"completed", "interrupted", "failed"}:
                            record.update(status="interrupted", updated_at=datetime_text())
                            connection.execute(
                                "UPDATE turns SET status='interrupted',record_json=?,"
                                "revision=revision+1,"
                                "updated_at=? WHERE turn_id=?",
                                (json_dumps(record), datetime_text(), job.turn_id),
                            )
                connection.execute(
                    "UPDATE outbox SET status='dead',last_error='episode cancelled',updated_at=? "
                    "WHERE status='pending' AND idempotency_key IN "
                    "(SELECT json_extract(record_json,'$.idempotency_key') "
                    "FROM turns WHERE turn_id=?)",
                    (datetime_text(), job.turn_id),
                )
            return episode

    def record_delivery(self, turn_id: str, status: str):
        with self.store.transaction() as connection:
            connection.execute(
                "UPDATE episode_turn_links SET delivery_status=? WHERE turn_id=? "
                "AND delivery_status NOT IN ('sent','duplicate')",
                (status, turn_id),
            )

    def inspect_episode(self, episode_id: str):
        episode = self.store.get_episode(episode_id)
        if episode is None:
            return None
        with self.store.connection() as connection:
            rows = connection.execute(
                "SELECT turn_id,npc_id,stimulus_json,generation_json FROM episode_turn_links "
                "WHERE episode_id=? ORDER BY created_at,turn_id",
                (episode_id,),
            ).fetchall()
        turns = [
            {
                "turn_id": row["turn_id"],
                "npc_id": row["npc_id"],
                "stimulus": json.loads(row["stimulus_json"]),
                "generation": json.loads(row["generation_json"] or "{}"),
            }
            for row in rows
        ]
        return episode.model_copy(
            update={
                "artifacts": {
                    **episode.artifacts,
                    "turns": turns,
                    "nodes": [
                        node.model_dump(mode="json") for node in self.store.list_nodes(episode_id)
                    ],
                }
            }
        )

    def is_cancelled(self, turn_id: str) -> bool:
        episode = self.episode_for_turn(turn_id)
        return episode is not None and episode.status in {"cancelled", "failed"}

    def automatically_reviewed_story(self, turn_id: str, proposal) -> bool:
        """An intent label alone must not pause an approved content presentation."""
        from npc_director.contracts import extract_state_change_paths

        if not self.readonly_quality_approved(turn_id):
            return False
        paths = set(extract_state_change_paths(proposal.plan.proposed_state_changes))
        if not paths:
            return True
        turn = self.service.turn_store.get(turn_id)
        # record_generation has already frozen the exact trusted policy, including
        # any reviewed content paths. Intent is not an additional capability gate.
        return turn is not None and paths <= set(turn.allowed_state_paths)

    def readonly_quality_approved(self, turn_id: str) -> bool:
        link = self._link(turn_id)
        if link is None:
            return False
        trace = json.loads(link["generation_json"] or "{}").get("trace") or {}
        quality = trace.get("quality") or {}
        return (
            bool(quality)
            and not any(issue.get("blocking", True) for issue in quality.get("issues", []))
            and min(
                quality.get("naturalness", 0),
                quality.get("persona_consistency", 0),
                quality.get("response_coverage", 0),
            )
            >= 3
        )

    def mark_memory_job(self, turn_id: str, *, succeeded: bool, error: str | None = None):
        with self.store.transaction() as connection:
            connection.execute(
                "UPDATE dialogue_memory_jobs SET status=?,attempts=attempts+1,last_error=?,"
                "updated_at=? WHERE turn_id=?",
                ("completed" if succeeded else "pending", error, datetime_text(), turn_id),
            )

    async def retry_memory_jobs(self, session_id: str):
        with self.store.connection() as connection:
            rows = connection.execute(
                "SELECT turn_id FROM dialogue_memory_jobs WHERE session_id=? AND status='pending' "
                "AND attempts < 3 ORDER BY updated_at LIMIT 4",
                (session_id,),
            ).fetchall()
        for row in rows:
            turn = await self.service.turn_store.aget(row["turn_id"])
            if turn is None or turn.status is not TurnStatus.COMPLETED:
                continue
            try:
                await self.service._distill_long_term_memory(turn)
                self.mark_memory_job(turn.turn_id, succeeded=True)
            except Exception as error:
                self.mark_memory_job(turn.turn_id, succeeded=False, error=type(error).__name__)
