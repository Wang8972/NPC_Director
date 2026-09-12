"""Transactional event encoding and derived, private memory lifecycle."""

from __future__ import annotations

import hashlib
import json
import time
from datetime import UTC, datetime

from npc_director.agents.memory_consolidator import encode_memory_input
from npc_director.contracts.cognition import (
    BehaviorState,
    MemoryConsolidation,
    MemoryRecord,
)
from npc_director.contracts.episodes import EpisodeRecord
from npc_director.rag.index import LexicalLoreIndex, LoreDocument
from npc_director.state._sqlite import SQLiteStore, datetime_text


def identifier(*parts: str) -> str:
    return "cog:" + hashlib.sha256("\0".join(parts).encode()).hexdigest()[:40]


class CognitionStore(SQLiteStore):
    def __init__(self, database, *, half_life=32, dormant_threshold=0.1, reflect_after=8):
        super().__init__(database)
        self.half_life = half_life
        self.dormant_threshold = dormant_threshold
        self.reflect_after = reflect_after
        self._indexes = {}
        self.initial_mode_provider = None
        self.protected_refs_provider = None
        self.migrate_scoped_memories()

    @staticmethod
    def ensure_actor(conn, session, npc):
        conn.execute(
            "INSERT OR IGNORE INTO cognition_actors(session_id,npc_id) VALUES (?,?)", (session, npc)
        )

    @staticmethod
    def put(conn, record: MemoryRecord):
        conn.execute(
            "INSERT OR REPLACE INTO cognition_memories VALUES (?,?,?,?)",
            (record.session_id, record.npc_id, record.memory_id, record.model_dump_json()),
        )

    @staticmethod
    def link(conn, session, npc, source, target, relation):
        if source != target:
            conn.execute(
                "INSERT OR IGNORE INTO cognition_links VALUES (?,?,?,?,?)",
                (session, npc, source, target, relation),
            )

    def migrate_scoped_memories(self):
        with self.transaction() as conn:
            for row in conn.execute("SELECT * FROM scoped_long_term_memories").fetchall():
                key = (row["session_id"], row["npc_id"])
                self.ensure_actor(conn, *key)
                if conn.execute(
                    "SELECT 1 FROM cognition_memories WHERE session_id=? AND "
                    "npc_id=? AND memory_id=?",
                    (*key, row["memory_id"]),
                ).fetchone():
                    continue
                record = MemoryRecord(
                    memory_id=row["memory_id"],
                    session_id=key[0],
                    npc_id=key[1],
                    kind="experience",
                    content=row["content"][:2000],
                    epistemic_status="legacy_unverified",
                    importance=row["importance"],
                    source_turn_ids=json.loads(row["source_turn_ids_json"]),
                )
                self.put(conn, record)
                conn.execute(
                    "UPDATE cognition_actors SET revision=revision+1 WHERE "
                    "session_id=? AND npc_id=?",
                    key,
                )

    def observe(self, event, *, connection=None):
        if connection is None:
            with self.transaction() as conn:
                return self.observe(event, connection=conn)
        if event.status == "interrupted" or (event.origin == "npc" and event.status != "completed"):
            return
        owners = set(event.audience) - {"player", "world"}
        if event.origin == "npc":
            owners.add(event.speaker_id)
        for npc in sorted(owners):
            self._encode(connection, event, npc)

    def _encode(self, conn, event, npc):
        session = event.session_id
        key = (session, npc)
        self.ensure_actor(conn, *key)
        if conn.execute(
            "SELECT 1 FROM cognition_sources WHERE session_id=? AND npc_id=? AND event_id=?",
            (*key, event.event_id),
        ).fetchone():
            return
        if self.initial_mode_provider is not None:
            conn.execute(
                "UPDATE cognition_actors SET behavior_json=? "
                "WHERE session_id=? AND npc_id=? AND sequence=0",
                (
                    BehaviorState(mode_id=self.initial_mode_provider(npc)).model_dump_json(),
                    session,
                    npc,
                ),
            )
        conn.execute(
            "UPDATE cognition_actors SET sequence=sequence+1,revision=revision+1 "
            "WHERE session_id=? AND npc_id=?",
            key,
        )
        actor = conn.execute(
            "SELECT * FROM cognition_actors WHERE session_id=? AND npc_id=?", key
        ).fetchone()
        seq = actor["sequence"]
        conn.execute(
            "INSERT INTO cognition_sources VALUES (?,?,?,?,?,?)",
            (*key, event.event_id, seq, event.episode_id, event.model_dump_json()),
        )
        label = "玩家说" if event.origin == "player" else f"{event.speaker_id}报告"
        record = MemoryRecord(
            memory_id=identifier(session, npc, event.event_id),
            session_id=session,
            npc_id=npc,
            kind="experience",
            content=f"{label}：{event.text}"[:2000],
            source_event_ids=[event.event_id],
            source_turn_ids=[event.turn_id],
            entity_ids=[event.speaker_id],
            goal_ids=[claim.content_id for claim in event.claims],
            created_seq=seq,
            reinforced_seq=seq,
        )
        if self.protected_refs_provider is not None:
            protected = set(self.protected_refs_provider(npc))
            record.pinned = bool(protected & {record.memory_id, event.event_id, *record.goal_ids})
            record.pin_reasons = ["configured"] if record.pinned else []
        self.put(conn, record)
        prior = self._records(conn, session, npc)
        for old in sorted(prior, key=lambda m: m.created_seq, reverse=True):
            if (set(old.entity_ids) & set(record.entity_ids)) - {"player", "world"}:
                self.link(conn, session, npc, record.memory_id, old.memory_id, "same_entity")
            if set(old.goal_ids) & set(record.goal_ids):
                self.link(conn, session, npc, record.memory_id, old.memory_id, "same_goal")
            if old.validity in {"active", "dormant"}:
                old.activation = (
                    1 if old.pinned else 0.5 ** ((seq - old.reinforced_seq) / self.half_life)
                )
                old.validity = "dormant" if old.activation < self.dormant_threshold else "active"
                self.put(conn, old)

    @staticmethod
    def _records(conn, session, npc):
        return [
            MemoryRecord.model_validate_json(row[0])
            for row in conn.execute(
                "SELECT record_json FROM cognition_memories WHERE session_id=? AND npc_id=? "
                "ORDER BY memory_id",
                (session, npc),
            )
        ]

    def records(self, session, npc):
        with self.connection() as conn:
            return self._records(conn, session, npc)

    def valid_records(self, conn, session, npc):
        records = self._records(conn, session, npc)
        sources = {
            row[0]: json.loads(row[1])
            for row in conn.execute(
                "SELECT event_id,payload_json FROM cognition_sources "
                "WHERE session_id=? AND npc_id=?",
                (session, npc),
            )
        }
        now = datetime.now(UTC)
        for memory in records:
            for eid in memory.source_event_ids:
                source = sources.get(eid)
                if source is None or any(
                    c.get("expires_at")
                    and datetime.fromisoformat(c["expires_at"].replace("Z", "+00:00")) <= now
                    for c in source.get("claims", [])
                ):
                    memory.validity = "expired"
        return records

    def snapshot(self, session, npc):
        with self.connection() as conn:
            row = conn.execute(
                "SELECT * FROM cognition_actors WHERE session_id=? AND npc_id=?", (session, npc)
            ).fetchone()
            memories = self.valid_records(conn, session, npc)
            sources = [
                dict(x)
                for x in conn.execute(
                    "SELECT event_id,sequence,payload_json FROM cognition_sources "
                    "WHERE session_id=? AND npc_id=? "
                    "ORDER BY sequence DESC LIMIT 32",
                    (session, npc),
                )
            ]
            links = [
                dict(x)
                for x in conn.execute(
                    "SELECT source_id,target_id,relation FROM cognition_links WHERE session_id=? "
                    "AND npc_id=? ORDER BY source_id,target_id,relation",
                    (session, npc),
                )
            ]
            jobs = [
                dict(x)
                for x in conn.execute(
                    "SELECT job_id,status,attempts,last_error,usage_json FROM cognition_jobs "
                    "WHERE session_id=? AND npc_id=? ORDER BY rowid",
                    (session, npc),
                )
            ]
        return {
            "version": "memory-v1",
            "revision": row["revision"] if row else 0,
            "sequence": row["sequence"] if row else 0,
            "behavior": json.loads(row["behavior_json"]) if row else BehaviorState().model_dump(),
            "visible_event_ids": [s["event_id"] for s in sources],
            "visible_events": [
                {
                    "event_id": s["event_id"],
                    "turn_id": json.loads(s["payload_json"])["turn_id"],
                    "text": json.loads(s["payload_json"])["text"][:240],
                }
                for s in sources
            ],
            "memories": [m.model_dump(mode="json") for m in memories],
            "links": links,
            "jobs": jobs,
        }

    def recall(
        self, session, npc, query, *, entity_ids=(), goal_ids=(), limit=6, token_budget=1600
    ):
        from npc_director.context.token_budget import _encoding

        encoding = _encoding("o200k_base")

        def estimate_tokens(text):
            return (
                len(encoding.encode(text, disallowed_special=()))
                if encoding
                else len(text.encode())
            )

        snapshot = self.snapshot(session, npc)
        records = [
            MemoryRecord.model_validate(m)
            for m in snapshot["memories"]
            if m["validity"] in {"active", "dormant"}
        ]
        cache_key = (session, npc)
        cached = self._indexes.get(cache_key)
        if cached is None or cached[0] != snapshot["revision"]:
            index = LexicalLoreIndex(LoreDocument(ref=m.memory_id, text=m.content) for m in records)
            self._indexes[cache_key] = (snapshot["revision"], index)
            if len(self._indexes) > 128:
                self._indexes.pop(next(iter(self._indexes)))
        else:
            index = cached[1]
        hits = {h.ref: h.score for h in index.search(query, top_k=len(records) or 1)}
        direct = {
            m.memory_id
            for m in records
            if set(m.entity_ids) & set(entity_ids) or set(m.goal_ids) & set(goal_ids)
        }
        seeds = set(hits) | direct
        associated = {edge["target_id"] for edge in snapshot["links"] if edge["source_id"] in seeds}
        associated |= {
            edge["source_id"] for edge in snapshot["links"] if edge["target_id"] in seeds
        }
        candidates = [m for m in records if m.memory_id in seeds | associated]
        candidates.sort(
            key=lambda m: (
                -int(m.memory_id in direct),
                -hits.get(m.memory_id, 0),
                -m.activation,
                -m.importance,
                -m.created_seq,
                m.memory_id,
            )
        )
        result, spent, seen = [], 0, set()
        for memory in candidates:
            if memory.content in seen:
                continue
            size = estimate_tokens(memory.model_dump_json())
            if spent + size > token_budget:
                continue
            result.append(memory.model_dump(mode="json"))
            seen.add(memory.content)
            spent += size
            if len(result) == limit:
                break
        return result

    def commit_state(
        self,
        conn,
        session,
        npc,
        turn_id,
        *,
        behavior=None,
        expected_version=0,
        memory_refs=(),
        commitments=(),
        goals=(),
        episode_id=None,
        significant=False,
    ):
        self.ensure_actor(conn, session, npc)
        if not conn.execute(
            "INSERT OR IGNORE INTO cognition_effects VALUES (?,?,?)", (session, npc, turn_id)
        ).rowcount:
            return
        actor = conn.execute(
            "SELECT * FROM cognition_actors WHERE session_id=? AND npc_id=?", (session, npc)
        ).fetchone()
        previous = BehaviorState.model_validate_json(actor["behavior_json"])
        if behavior is not None:
            if previous.version != expected_version:
                raise ValueError("behavior version changed before completion")
            state = BehaviorState.model_validate(behavior)
            state.version = previous.version + 1
            state.source_turn_id = turn_id
            conn.execute(
                "UPDATE cognition_actors SET behavior_json=? WHERE session_id=? AND npc_id=?",
                (state.model_dump_json(), session, npc),
            )
        changed = significant
        for memory in self._records(conn, session, npc):
            if memory.memory_id in memory_refs and memory.validity in {"active", "dormant"}:
                memory.activation = 1
                memory.reinforced_seq = actor["sequence"]
                memory.validity = "active"
                memory.version += 1
                self.put(conn, memory)
        for item in commitments:
            text = item.get("text", "")
            if not text:
                continue
            mid = identifier(session, npc, "commitment", text)
            existing = conn.execute(
                "SELECT record_json FROM cognition_memories WHERE session_id=? "
                "AND npc_id=? AND memory_id=?",
                (session, npc, mid),
            ).fetchone()
            pinned = item.get("status", "open") == "open"
            source_turn = item.get("source_turn_id", turn_id)
            source = conn.execute(
                "SELECT event_id FROM cognition_sources WHERE session_id=? "
                "AND npc_id=? AND json_extract(payload_json,'$.turn_id')=?",
                (session, npc, source_turn),
            ).fetchall()
            if existing:
                memory = MemoryRecord.model_validate_json(existing[0])
                changed |= memory.pinned != pinned
                memory.pinned = pinned
                memory.pin_reasons = ["open_commitment"] if pinned else []
                memory.version += 1
            else:
                changed = True
                memory = MemoryRecord(
                    memory_id=mid,
                    session_id=session,
                    npc_id=npc,
                    kind="commitment",
                    content=text[:2000],
                    pinned=pinned,
                    pin_reasons=["open_commitment"] if pinned else [],
                    source_event_ids=[x[0] for x in source],
                    importance=0.9,
                    created_seq=actor["sequence"],
                    reinforced_seq=actor["sequence"],
                )
            if not memory.source_turn_ids:
                memory.source_turn_ids = [source_turn]
            self.put(conn, memory)
            for related in self._records(conn, session, npc):
                if set(memory.source_event_ids) & set(related.source_event_ids):
                    self.link(conn, session, npc, memory.memory_id, related.memory_id, "same_event")
        active_goals = {g.get("id") for g in goals if g.get("status") != "completed"}
        all_memories = self._records(conn, session, npc)
        for memory in all_memories:
            if turn_id in memory.source_turn_ids:
                memory.goal_ids = sorted(
                    set(memory.goal_ids) | {g["id"] for g in goals if g.get("id")}
                )
                for related in all_memories:
                    if set(memory.goal_ids) & set(related.goal_ids):
                        self.link(
                            conn, session, npc, memory.memory_id, related.memory_id, "same_goal"
                        )
            memory.pin_reasons = [
                reason for reason in memory.pin_reasons if reason != "active_goal"
            ]
            if set(memory.goal_ids) & active_goals:
                memory.pin_reasons.append("active_goal")
            memory.pinned = bool(memory.pin_reasons)
            self.put(conn, memory)
        conn.execute(
            "UPDATE cognition_actors SET revision=revision+1 WHERE session_id=? AND npc_id=?",
            (session, npc),
        )
        if episode_id and (
            changed or actor["sequence"] - actor["consolidated_seq"] >= self.reflect_after
        ):
            self.enqueue(conn, session, npc, episode_id)

    def enqueue(self, conn, session, npc, episode_id):
        if conn.execute(
            "SELECT 1 FROM cognition_jobs WHERE session_id=? AND npc_id=? "
            "AND status IN ('pending','running')",
            (session, npc),
        ).fetchone():
            return
        actor = conn.execute(
            "SELECT * FROM cognition_actors WHERE session_id=? AND npc_id=?", (session, npc)
        ).fetchone()
        sources = sorted(
            self.valid_records(conn, session, npc), key=lambda m: m.created_seq, reverse=True
        )
        sources = [
            m
            for m in sources
            if m.validity in {"active", "dormant"} and m.epistemic_status != "legacy_unverified"
        ][:32]
        if not sources:
            return
        payload = json.dumps(
            {"memories": [m.model_dump(mode="json") for m in sources]}, ensure_ascii=False
        )
        job_id = identifier(session, npc, str(actor["revision"]))
        reservation = job_id + ":1"
        reserve = len(encode_memory_input(payload)[0].encode()) + 8192
        row = conn.execute(
            "SELECT record_json FROM episodes WHERE episode_id=?", (episode_id,)
        ).fetchone()
        if row is None:
            return
        episode = EpisodeRecord.model_validate_json(row[0])
        if (
            episode.status in {"cancelled", "failed", "budget_exhausted", "unsupported"}
            or episode.used_model_calls >= episode.budget.max_model_calls
            or episode.used_tokens + episode.reserved_tokens + reserve
            > episode.budget.max_total_tokens
            or episode.active_seconds >= episode.budget.max_active_seconds
        ):
            return
        conn.execute(
            "INSERT INTO episode_reservations(episode_id,operation_id,resource,role,"
            "token_reservation,status,created_at) "
            "VALUES (?,?,'model_call','memory',?,'reserved',?)",
            (episode_id, reservation, reserve, datetime_text()),
        )
        episode.used_model_calls += 1
        episode.reserved_tokens += reserve
        episode.revision += 1
        conn.execute(
            "UPDATE episodes SET record_json=?,revision=? WHERE episode_id=?",
            (episode.model_dump_json(), episode.revision, episode_id),
        )
        conn.execute(
            "INSERT INTO cognition_jobs(job_id,session_id,npc_id,episode_id,input_revision,"
            "input_seq,snapshot_json,reservation_id) VALUES (?,?,?,?,?,?,?,?)",
            (
                job_id,
                session,
                npc,
                episode_id,
                actor["revision"],
                actor["sequence"],
                payload,
                reservation,
            ),
        )

    def claim(self, worker, *, session_id=None, lease_seconds=120):
        with self.transaction() as conn:
            rows = conn.execute(
                "SELECT * FROM cognition_jobs WHERE status='pending' "
                "AND (? IS NULL OR session_id=?) ORDER BY rowid LIMIT 1",
                (session_id, session_id),
            ).fetchall()
            if not rows:
                return None
            job = dict(rows[0])
            conn.execute(
                "UPDATE cognition_jobs SET status='running',attempts=attempts+1,claimed_by=?,"
                "lease_until=? WHERE job_id=?",
                (worker, time.time() + lease_seconds, job["job_id"]),
            )
            job["claimed_by"] = worker
            return job

    def retry_failed(self, job_id):
        """A retry is a new, pre-reserved model call, never a reused payment."""
        with self.transaction() as conn:
            row = conn.execute("SELECT * FROM cognition_jobs WHERE job_id=?", (job_id,)).fetchone()
            if row is None or row["status"] != "failed" or row["attempts"] >= 2:
                return False
            actor = conn.execute(
                "SELECT revision FROM cognition_actors WHERE session_id=? AND npc_id=?",
                (row["session_id"], row["npc_id"]),
            ).fetchone()
            if actor[0] != row["input_revision"]:
                conn.execute(
                    "UPDATE cognition_jobs SET status='obsolete' WHERE job_id=?", (job_id,)
                )
                return False
            parent = conn.execute(
                "SELECT record_json FROM episodes WHERE episode_id=?", (row["episode_id"],)
            ).fetchone()
            episode = EpisodeRecord.model_validate_json(parent[0])
            reserve = len(encode_memory_input(row["snapshot_json"])[0].encode()) + 8192
            if (
                episode.status in {"cancelled", "failed", "budget_exhausted", "unsupported"}
                or episode.used_model_calls >= episode.budget.max_model_calls
                or episode.used_tokens + episode.reserved_tokens + reserve
                > episode.budget.max_total_tokens
                or episode.active_seconds >= episode.budget.max_active_seconds
            ):
                return False
            operation = job_id + ":" + str(row["attempts"] + 1)
            conn.execute(
                "INSERT INTO episode_reservations(episode_id,operation_id,resource,role,"
                "token_reservation,status,created_at) "
                "VALUES (?,?,'model_call','memory',?,'reserved',?)",
                (episode.id, operation, reserve, datetime_text()),
            )
            episode.used_model_calls += 1
            episode.reserved_tokens += reserve
            episode.revision += 1
            conn.execute(
                "UPDATE episodes SET record_json=?,revision=? WHERE episode_id=?",
                (episode.model_dump_json(), episode.revision, episode.id),
            )
            conn.execute(
                "UPDATE cognition_jobs SET status='pending',reservation_id=?,claimed_by=NULL,"
                "lease_until=NULL WHERE job_id=?",
                (operation, job_id),
            )
            return True

    def refresh_obsolete(self, session, npc):
        """Coalesce new observations into a fresh snapshot without waking gameplay."""
        with self.transaction() as conn:
            latest = conn.execute(
                "SELECT episode_id FROM cognition_sources WHERE session_id=? AND npc_id=? "
                "AND episode_id IS NOT NULL ORDER BY sequence DESC LIMIT 1",
                (session, npc),
            ).fetchone()
            actor = conn.execute(
                "SELECT * FROM cognition_actors WHERE session_id=? AND npc_id=?", (session, npc)
            ).fetchone()
            if latest and actor["sequence"] > actor["consolidated_seq"]:
                exists = conn.execute(
                    "SELECT 1 FROM cognition_jobs WHERE session_id=? AND npc_id=? "
                    "AND input_revision=?",
                    (session, npc, actor["revision"]),
                ).fetchone()
                if not exists:
                    self.enqueue(conn, session, npc, latest[0])

    def finish(self, job, output: MemoryConsolidation | None, *, error=None, usage=None):
        with self.transaction() as conn:
            current = conn.execute(
                "SELECT * FROM cognition_jobs WHERE job_id=?", (job["job_id"],)
            ).fetchone()
            if (
                current["status"] != "running"
                or current["claimed_by"] != job["claimed_by"]
                or current["lease_until"] < time.time()
            ):
                return False
            key = (job["session_id"], job["npc_id"])
            actor = conn.execute(
                "SELECT * FROM cognition_actors WHERE session_id=? AND npc_id=?", key
            ).fetchone()
            status = "failed" if error else "completed"
            if actor["revision"] != job["input_revision"]:
                status = "obsolete"
            if output is not None and status == "completed":
                inputs = {
                    m["memory_id"]: MemoryRecord.model_validate(m)
                    for m in json.loads(job["snapshot_json"])["memories"]
                }
                valid = {
                    m.memory_id for m in self.valid_records(conn, *key) if m.validity != "expired"
                }
                if not inputs.keys() <= valid:
                    raise ValueError("reflection source expired or disappeared")
                for insight in output.insights:
                    if not set(insight.source_memory_ids) <= inputs.keys():
                        raise ValueError("reflection references invisible memories")
                    for target in insight.supersedes + insight.contradicts:
                        if target not in inputs or inputs[target].kind not in {"belief", "summary"}:
                            raise ValueError(
                                "reflection cannot revise original experience or commitment"
                            )
                        if not any(
                            inputs[mid].created_seq > inputs[target].created_seq
                            for mid in insight.source_memory_ids
                        ):
                            raise ValueError("reflection revision requires new evidence")
                for i, insight in enumerate(output.insights):
                    evidence = [inputs[mid] for mid in insight.source_memory_ids]
                    memory = MemoryRecord(
                        memory_id=identifier(job["job_id"], str(i)),
                        session_id=key[0],
                        npc_id=key[1],
                        kind=insight.kind,
                        content=insight.content,
                        epistemic_status="inferred",
                        source_memory_ids=insight.source_memory_ids,
                        source_event_ids=sorted({x for m in evidence for x in m.source_event_ids}),
                        entity_ids=sorted({x for m in evidence for x in m.entity_ids}),
                        goal_ids=sorted({x for m in evidence for x in m.goal_ids}),
                        created_seq=job["input_seq"],
                        reinforced_seq=job["input_seq"],
                    )
                    self.put(conn, memory)
                    for mid in insight.source_memory_ids:
                        self.link(conn, *key, memory.memory_id, mid, "supports")
                    for relation, targets in (
                        ("supersedes", insight.supersedes),
                        ("contradicts", insight.contradicts),
                    ):
                        for mid in targets:
                            old = inputs[mid].model_copy(deep=True)
                            old.validity = "superseded" if relation == "supersedes" else "disputed"
                            old.version += 1
                            self.put(conn, old)
                            self.link(conn, *key, memory.memory_id, mid, relation)
                conn.execute(
                    "UPDATE cognition_actors SET consolidated_seq=?,revision=revision+1 "
                    "WHERE session_id=? AND npc_id=?",
                    (job["input_seq"], *key),
                )
            conn.execute(
                "UPDATE cognition_jobs SET status=?,last_error=?,usage_json=?,lease_until=NULL "
                "WHERE job_id=?",
                (status, error, json.dumps(usage or {}), job["job_id"]),
            )
            return status == "completed"
