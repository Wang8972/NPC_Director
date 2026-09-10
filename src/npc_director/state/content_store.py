"""Instance-scoped, reviewed content with atomic reservations and publication.

Publication participates in the caller's completed-turn transaction. This store
does not execute game actions, accept quests, or invent domain permissions.
"""

from __future__ import annotations

import hashlib
import sqlite3
from collections.abc import Collection, Sequence
from pathlib import Path
from typing import Any

from npc_director.contracts.content import (
    ContentFact,
    ObjectiveEvent,
    ObjectiveRef,
    ObjectiveStep,
    PublishedQuest,
    ReviewedContent,
    StagedContent,
)
from npc_director.contracts.plan import QuestPatch, StateChangeProposal
from npc_director.governance.content_review import (
    ContentReviewError,
    semantic_key,
    validate_content_review,
)
from npc_director.state._sqlite import SQLiteStore, datetime_text, json_dumps, json_loads, utc_now
from npc_director.state.errors import IdempotencyConflictError

CONTENT_SCHEMA = """
CREATE TABLE IF NOT EXISTS narrative_content_schema (
    version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL
);
INSERT OR IGNORE INTO narrative_content_schema VALUES (1, CURRENT_TIMESTAMP);
CREATE TABLE IF NOT EXISTS narrative_content (
    content_id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL,
    episode_id TEXT NOT NULL,
    turn_id TEXT NOT NULL,
    npc_id TEXT NOT NULL,
    candidate_id TEXT NOT NULL,
    semantic_key TEXT NOT NULL,
    content_kind TEXT NOT NULL,
    status TEXT NOT NULL CHECK(status IN ('staged','published','discarded')),
    quest_id TEXT,
    reviewed_hash TEXT NOT NULL,
    policy_frozen INTEGER NOT NULL DEFAULT 0,
    record_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    published_at TEXT
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_narrative_live_goal
ON narrative_content(session_id, content_kind, semantic_key)
WHERE status IN ('staged','published');
CREATE INDEX IF NOT EXISTS idx_narrative_content_turn
ON narrative_content(session_id, turn_id, status);
CREATE INDEX IF NOT EXISTS idx_narrative_content_owner
ON narrative_content(session_id, npc_id, status);
CREATE TABLE IF NOT EXISTS narrative_quest_reservations (
    content_id TEXT PRIMARY KEY REFERENCES narrative_content(content_id),
    session_id TEXT NOT NULL,
    episode_id TEXT NOT NULL,
    status TEXT NOT NULL CHECK(status IN ('reserved','consumed'))
);
CREATE INDEX IF NOT EXISTS idx_narrative_quest_quota
ON narrative_quest_reservations(session_id, episode_id, status);
CREATE TABLE IF NOT EXISTS narrative_episode_quotas (
    session_id TEXT NOT NULL,
    episode_id TEXT NOT NULL,
    max_new_quests INTEGER NOT NULL CHECK(max_new_quests >= 0),
    PRIMARY KEY(session_id, episode_id)
);
CREATE TABLE IF NOT EXISTS narrative_objectives (
    session_id TEXT NOT NULL,
    objective_id TEXT NOT NULL,
    ref_json TEXT NOT NULL,
    version INTEGER NOT NULL,
    PRIMARY KEY(session_id, objective_id)
);
CREATE TABLE IF NOT EXISTS narrative_quests (
    session_id TEXT NOT NULL,
    quest_id TEXT NOT NULL,
    record_json TEXT NOT NULL,
    PRIMARY KEY(session_id, quest_id)
);
CREATE TABLE IF NOT EXISTS narrative_quest_events (
    session_id TEXT NOT NULL,
    event_id TEXT NOT NULL,
    quest_id TEXT NOT NULL,
    target_status TEXT NOT NULL,
    PRIMARY KEY(session_id, event_id)
);
"""

OBJECTIVE_PLAN_SCHEMA_V2 = """
CREATE TABLE IF NOT EXISTS narrative_objective_plan_commits (
    session_id TEXT NOT NULL,
    turn_id TEXT NOT NULL,
    npc_id TEXT NOT NULL,
    event_id TEXT NOT NULL,
    payload_hash TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY(session_id, turn_id),
    UNIQUE(session_id, event_id)
);
CREATE TABLE IF NOT EXISTS narrative_objective_plans (
    session_id TEXT NOT NULL,
    npc_id TEXT NOT NULL,
    objective_id TEXT NOT NULL,
    ref_json TEXT NOT NULL,
    definition_json TEXT NOT NULL,
    source_turn_id TEXT NOT NULL,
    source_event_id TEXT NOT NULL,
    revision INTEGER NOT NULL CHECK(revision > 0),
    updated_at TEXT NOT NULL,
    PRIMARY KEY(session_id, npc_id, objective_id),
    FOREIGN KEY(session_id, objective_id)
        REFERENCES narrative_objectives(session_id, objective_id),
    FOREIGN KEY(session_id, source_turn_id)
        REFERENCES narrative_objective_plan_commits(session_id, turn_id)
);
INSERT OR IGNORE INTO narrative_content_schema VALUES (2, CURRENT_TIMESTAMP);
"""


class ContentQuotaError(ContentReviewError):
    """The episode's reserved or published new-quest quota is exhausted."""


class DuplicateContentError(ContentReviewError):
    def __init__(self, existing: StagedContent) -> None:
        self.existing = existing
        super().__init__(f"goal already has content {existing.content_id}; reuse or merge it")


def _digest(value: object) -> str:
    return hashlib.sha256(json_dumps(value).encode()).hexdigest()


def _read_record(row: sqlite3.Row) -> StagedContent:
    return StagedContent.model_validate_json(row["record_json"])


def _save_record(connection: sqlite3.Connection, record: StagedContent) -> None:
    connection.execute(
        "UPDATE narrative_content SET status=?, record_json=?, published_at=? WHERE content_id=?",
        (record.status, record.model_dump_json(), record.published_at, record.content_id),
    )


def _references(reviewed: ReviewedContent) -> list[ObjectiveRef]:
    refs: dict[str, ObjectiveRef] = {}
    candidate = reviewed.candidate
    if candidate.scope.parent_objective is not None:
        ref = candidate.scope.parent_objective
        refs[ref.objective_id] = ref
    for item in [*candidate.steps, *candidate.events]:
        if (
            candidate.scope.scope == "side_quest"
            and item.objective.objective_id == candidate.candidate_id
            and item.objective.quest_id is None
        ):
            continue
        refs[item.objective.objective_id] = item.objective
    return list(refs.values())


def _plan_parent_refs(refs: Sequence[ObjectiveRef]) -> dict[str, ObjectiveRef]:
    if len(refs) > 128:
        raise ContentReviewError("objective plan parent reference limit exceeded")
    result: dict[str, ObjectiveRef] = {}
    for item in refs:
        ref = ObjectiveRef.model_validate(item.model_dump())
        if not ref.objective_id.strip():
            raise ContentReviewError("objective plan parent identity must not be blank")
        if ref.objective_id in result and result[ref.objective_id] != ref:
            raise ContentReviewError("objective plan has conflicting parent references")
        result[ref.objective_id] = ref
    return result


class ContentStore(SQLiteStore):
    def __init__(self, database: str | Path) -> None:
        super().__init__(database)
        with self.connection() as connection:
            connection.executescript(CONTENT_SCHEMA)
            connection.executescript(OBJECTIVE_PLAN_SCHEMA_V2)

    def register_objective(self, session_id: str, ref: ObjectiveRef) -> None:
        """Register trusted server state; a stale snapshot cannot rewind a version."""
        with self.transaction() as connection:
            self.register_objective_in_connection(connection, session_id, ref)

    def get_objective(self, session_id: str, objective_id: str) -> ObjectiveRef | None:
        """Read the objective's own version from this instance without creating state."""
        if not session_id.strip():
            raise ValueError("session_id must not be blank")
        if not objective_id.strip():
            raise ValueError("objective_id must not be blank")
        with self.connection() as connection:
            row = connection.execute(
                "SELECT ref_json,version FROM narrative_objectives "
                "WHERE session_id=? AND objective_id=?",
                (session_id, objective_id),
            ).fetchone()
        if row is None:
            return None
        ref = ObjectiveRef.model_validate_json(row["ref_json"])
        if ref.objective_id != objective_id or ref.version != row["version"]:
            raise ContentReviewError("objective registry identity or version mismatch")
        return ref

    def save_objective_plan_in_connection(
        self,
        connection: sqlite3.Connection,
        session_id: str,
        npc_id: str,
        turn_id: str,
        event_id: str,
        *,
        steps: Sequence[ObjectiveStep] = (),
        events: Sequence[ObjectiveEvent] = (),
        current_objective_refs: Sequence[ObjectiveRef],
        allowed_actions: Collection[str],
    ) -> bool:
        """Save approved existing-content definitions in the completion transaction.

        The caller gates author/reviewer content and quality approval. This write
        only defines a plan; it never completes steps or consumes quest quota.
        """
        if not connection.in_transaction:
            raise ValueError("objective plan publication requires a completion transaction")
        for field, value in (
            ("session_id", session_id),
            ("npc_id", npc_id),
            ("turn_id", turn_id),
            ("event_id", event_id),
        ):
            if not value.strip():
                raise ValueError(f"{field} must not be blank")
        if len(steps) > 16 or len(events) > 8:
            raise ContentReviewError("objective plan definition limit exceeded")
        steps = [ObjectiveStep.model_validate(item.model_dump()) for item in steps]
        events = [ObjectiveEvent.model_validate(item.model_dump()) for item in events]
        payload = {
            "steps": [item.model_dump(mode="json") for item in steps],
            "events": [item.model_dump(mode="json") for item in events],
        }
        fingerprint = _digest(payload)
        prior = connection.execute(
            "SELECT * FROM narrative_objective_plan_commits "
            "WHERE session_id=? AND (turn_id=? OR event_id=?)",
            (session_id, turn_id, event_id),
        ).fetchall()
        if prior:
            if len(prior) != 1 or any(
                prior[0][field] != value
                for field, value in (
                    ("turn_id", turn_id),
                    ("event_id", event_id),
                    ("npc_id", npc_id),
                    ("payload_hash", fingerprint),
                )
            ):
                raise IdempotencyConflictError("objective plan completion replay differs")
            return False
        if not steps and not events:
            return False
        allowed_refs = _plan_parent_refs(current_objective_refs)
        refs = _plan_parent_refs([item.objective for item in [*steps, *events]])
        for ref in refs.values():
            if allowed_refs.get(ref.objective_id) != ref:
                raise ContentReviewError("objective plan references an unauthorized parent")
            row = connection.execute(
                "SELECT ref_json,version FROM narrative_objectives "
                "WHERE session_id=? AND objective_id=?",
                (session_id, ref.objective_id),
            ).fetchone()
            if row is None:
                raise ContentReviewError("objective plan parent is not registered in this instance")
            if (
                ObjectiveRef.model_validate_json(row["ref_json"]) != ref
                or row["version"] != ref.version
            ):
                raise ContentReviewError("objective plan references a stale parent objective")
        if any(item.action and item.action not in allowed_actions for item in steps):
            raise ContentReviewError("objective plan requires an unregistered action")
        if len({item.step_id for item in steps}) != len(steps):
            raise ContentReviewError("objective plan contains duplicate step identifiers")
        if len({item.event_id for item in events}) != len(events):
            raise ContentReviewError("objective plan contains duplicate event identifiers")
        by_step = {item.step_id: item for item in steps}
        for item in steps:
            if any(
                dependency not in by_step or by_step[dependency].objective != item.objective
                for dependency in item.depends_on
            ):
                raise ContentReviewError(
                    "objective plan dependency is unknown or has another parent"
                )
        pending = list(steps)
        completed: set[str] = set()
        while pending:
            ready = [item for item in pending if set(item.depends_on).issubset(completed)]
            if not ready:
                raise ContentReviewError("objective plan dependencies contain a cycle")
            for item in ready:
                completed.add(item.step_id)
                pending.remove(item)
        now = datetime_text()
        connection.execute(
            "INSERT INTO narrative_objective_plan_commits VALUES(?,?,?,?,?,?,?)",
            (session_id, turn_id, npc_id, event_id, fingerprint, json_dumps(payload), now),
        )
        for ref in refs.values():
            definition = {
                "steps": [item.model_dump(mode="json") for item in steps if item.objective == ref],
                "events": [
                    item.model_dump(mode="json") for item in events if item.objective == ref
                ],
            }
            connection.execute(
                "INSERT INTO narrative_objective_plans VALUES(?,?,?,?,?,?,?,1,?) "
                "ON CONFLICT(session_id,npc_id,objective_id) DO UPDATE SET "
                "ref_json=excluded.ref_json,definition_json=excluded.definition_json,"
                "source_turn_id=excluded.source_turn_id,source_event_id=excluded.source_event_id,"
                "revision=narrative_objective_plans.revision+1,updated_at=excluded.updated_at",
                (
                    session_id,
                    npc_id,
                    ref.objective_id,
                    ref.model_dump_json(),
                    json_dumps(definition),
                    turn_id,
                    event_id,
                    now,
                ),
            )
        return True

    def list_objective_plans(
        self,
        session_id: str,
        npc_id: str,
        *,
        parent_refs: Sequence[ObjectiveRef],
        limit: int = 8,
    ) -> list[dict[str, Any]]:
        """Read bounded definitions for this actor's current authorized parents."""
        if not session_id.strip() or not npc_id.strip():
            raise ValueError("objective plan session_id and npc_id must not be blank")
        refs = _plan_parent_refs(parent_refs)
        if not refs or limit < 1:
            return []
        placeholders = ",".join("?" for _ in refs)
        with self.connection() as connection:
            # One row per parent and at most 128 authorized parents bounds this read.
            rows = connection.execute(
                "SELECT p.*,o.ref_json AS current_ref_json,o.version AS current_version "
                "FROM narrative_objective_plans p JOIN narrative_objectives o "
                "ON o.session_id=p.session_id AND o.objective_id=p.objective_id "
                "WHERE p.session_id=? AND p.npc_id=? "
                f"AND p.objective_id IN ({placeholders}) "
                "ORDER BY p.updated_at DESC,p.objective_id",
                (session_id, npc_id, *refs),
            ).fetchall()
        result = []
        for row in rows:
            ref = ObjectiveRef.model_validate_json(row["ref_json"])
            if ref.objective_id != row["objective_id"]:
                raise ContentReviewError("objective plan registry identity mismatch")
            if (
                refs[ref.objective_id] != ref
                or ObjectiveRef.model_validate_json(row["current_ref_json"]) != ref
                or row["current_version"] != ref.version
            ):
                continue
            definition = json_loads(row["definition_json"])
            steps = [ObjectiveStep.model_validate(item) for item in definition["steps"]]
            events = [ObjectiveEvent.model_validate(item) for item in definition["events"]]
            if any(item.objective != ref for item in [*steps, *events]):
                raise ContentReviewError("objective plan definition changed parent ownership")
            result.append(
                {
                    "objective": ref.model_dump(mode="json"),
                    "steps": [item.model_dump(mode="json") for item in steps],
                    "events": [item.model_dump(mode="json") for item in events],
                    "source_turn_id": row["source_turn_id"],
                    "source_event_id": row["source_event_id"],
                    "revision": row["revision"],
                }
            )
            if len(result) >= min(limit, 32):
                break
        return result

    @staticmethod
    def register_objective_in_connection(
        connection: sqlite3.Connection,
        session_id: str,
        ref: ObjectiveRef,
    ) -> None:
        row = connection.execute(
            "SELECT ref_json,version FROM narrative_objectives "
            "WHERE session_id=? AND objective_id=?",
            (session_id, ref.objective_id),
        ).fetchone()
        if row is not None:
            prior = ObjectiveRef.model_validate_json(row["ref_json"])
            if prior.quest_id != ref.quest_id:
                raise ContentReviewError("objective identity cannot change quest ownership")
            if prior.version > ref.version:
                raise ContentReviewError("cannot register a stale objective version")
        connection.execute(
            "INSERT INTO narrative_objectives(session_id,objective_id,ref_json,version) "
            "VALUES(?,?,?,?) ON CONFLICT(session_id,objective_id) DO UPDATE SET "
            "ref_json=excluded.ref_json,version=excluded.version",
            (session_id, ref.objective_id, ref.model_dump_json(), ref.version),
        )

    @staticmethod
    def _validate_current_refs(
        connection: sqlite3.Connection,
        session_id: str,
        reviewed: ReviewedContent,
        current_objective_refs: Sequence[ObjectiveRef] | None = None,
    ) -> None:
        for ref in _references(reviewed):
            if current_objective_refs is not None and ref not in current_objective_refs:
                raise ContentReviewError(f"parent objective changed before completion: {ref.key}")
            row = connection.execute(
                "SELECT ref_json FROM narrative_objectives WHERE session_id=? AND objective_id=?",
                (session_id, ref.objective_id),
            ).fetchone()
            if row is None:
                raise ContentReviewError(f"parent objective is not registered: {ref.key}")
            if ObjectiveRef.model_validate_json(row["ref_json"]) != ref:
                raise ContentReviewError(f"stale parent objective: {ref.key}@{ref.version}")

    @staticmethod
    def _check_published_facts(
        connection: sqlite3.Connection,
        session_id: str,
        reviewed: ReviewedContent,
    ) -> None:
        incoming = {
            fact.fact_key: fact.statement.strip()
            for fact in reviewed.candidate.facts
            if fact.epistemic_status == "world_fact"
        }
        if not incoming:
            return
        rows = connection.execute(
            "SELECT record_json FROM narrative_content WHERE session_id=? AND status='published'",
            (session_id,),
        ).fetchall()
        for row in rows:
            record = _read_record(row)
            if record.candidate.expires_at is not None and record.candidate.expires_at <= utc_now():
                continue
            for fact in record.candidate.facts:
                if (
                    fact.epistemic_status == "world_fact"
                    and fact.fact_key in incoming
                    and fact.statement.strip() != incoming[fact.fact_key]
                ):
                    raise ContentReviewError(f"conflicts with published fact: {fact.fact_key}")

    def stage_reviewed(
        self,
        session_id: str,
        episode_id: str,
        turn_id: str,
        npc_id: str,
        reviewed: ReviewedContent,
        *,
        max_new_quests: int | None = None,
        policy_digest: str | None = None,
    ) -> StagedContent:
        if reviewed.policy.session_id != session_id or reviewed.policy.npc_id != npc_id:
            raise ContentReviewError("content policy belongs to another instance or NPC")
        checked = validate_content_review(
            reviewed.need,
            reviewed.submitted_candidate or reviewed.candidate,
            reviewed.review,
            reviewed.policy,
        )
        if checked.candidate != reviewed.candidate:
            raise ContentReviewError("candidate was changed after review")
        candidate = checked.candidate
        quota = checked.policy.max_new_quests
        if max_new_quests is not None:
            if max_new_quests < 0:
                raise ValueError("max_new_quests must not be negative")
            quota = min(quota, max_new_quests)
        identity = [session_id, turn_id, candidate.candidate_id]
        content_id = "content_" + _digest(identity)[:32]
        fingerprint = _digest(checked.model_dump(mode="json"))
        quest_id = "generated_" + _digest([session_id, candidate.objective_key])[:24]
        is_quest = candidate.scope.scope == "side_quest"
        if not is_quest:
            quest_id = None
        paths = [] if quest_id is None else [f"quests.{quest_id}.status"]
        patch = StateChangeProposal(
            quests=[] if quest_id is None else [QuestPatch(quest_id=quest_id, status="offered")],
        )
        frozen_digest = (
            policy_digest
            or checked.policy.policy_digest
            or _digest(
                {
                    "policy": checked.policy.model_dump(mode="json"),
                    "content_id": content_id,
                    "allowed_state_paths": paths,
                }
            )
        )
        record = StagedContent(
            content_id=content_id,
            session_id=session_id,
            episode_id=episode_id,
            turn_id=turn_id,
            npc_id=npc_id,
            reviewed=checked,
            quest_id=quest_id,
            allowed_state_paths=paths,
            proposed_state_changes=patch,
            policy_digest=frozen_digest,
            created_at=datetime_text(),
        )
        with self.transaction() as connection:
            expirable_rows = connection.execute(
                "SELECT record_json FROM narrative_content WHERE session_id=? "
                "AND content_kind!='quest' AND status IN ('staged','published')",
                (session_id,),
            ).fetchall()
            now = utc_now()
            for row in expirable_rows:
                old = _read_record(row)
                if old.candidate.expires_at is not None and old.candidate.expires_at <= now:
                    # Undelivered temporary content must not permanently reserve
                    # its semantic goal. Quests retain their explicit lifecycle.
                    old.status = "discarded"
                    _save_record(connection, old)
            prior = connection.execute(
                "SELECT record_json,reviewed_hash FROM narrative_content WHERE content_id=?",
                (content_id,),
            ).fetchone()
            if prior is not None:
                existing = _read_record(prior)
                if prior["reviewed_hash"] != fingerprint or existing.episode_id != episode_id:
                    raise IdempotencyConflictError("candidate replay differs from staged content")
                if existing.status == "discarded":
                    raise ContentReviewError("discarded turn content cannot be resurrected")
                return existing
            duplicate = connection.execute(
                "SELECT record_json FROM narrative_content WHERE session_id=? AND content_kind=? "
                "AND semantic_key=? AND status IN ('staged','published')",
                (session_id, candidate.content_kind, semantic_key(candidate.objective_key)),
            ).fetchone()
            if duplicate is not None:
                raise DuplicateContentError(_read_record(duplicate))
            self._validate_current_refs(connection, session_id, checked)
            self._check_published_facts(connection, session_id, checked)
            connection.execute(
                "INSERT OR IGNORE INTO narrative_episode_quotas "
                "(session_id,episode_id,max_new_quests) VALUES(?,?,?)",
                (session_id, episode_id, quota),
            )
            # Retrying under a looser policy cannot expand the episode's original quota.
            connection.execute(
                "UPDATE narrative_episode_quotas SET max_new_quests=MIN(max_new_quests,?) "
                "WHERE session_id=? AND episode_id=?",
                (quota, session_id, episode_id),
            )
            quota_row = connection.execute(
                "SELECT max_new_quests FROM narrative_episode_quotas "
                "WHERE session_id=? AND episode_id=?",
                (session_id, episode_id),
            ).fetchone()
            assert quota_row is not None
            if is_quest:
                used = connection.execute(
                    "SELECT COUNT(*) FROM narrative_quest_reservations "
                    "WHERE session_id=? AND episode_id=?",
                    (session_id, episode_id),
                ).fetchone()[0]
                if used >= quota_row["max_new_quests"]:
                    raise ContentQuotaError("new side-quest quota exhausted for this episode")
            connection.execute(
                "INSERT INTO narrative_content "
                "(content_id,session_id,episode_id,turn_id,npc_id,candidate_id,semantic_key,"
                "content_kind,status,quest_id,reviewed_hash,record_json,created_at) "
                "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    content_id,
                    session_id,
                    episode_id,
                    turn_id,
                    npc_id,
                    candidate.candidate_id,
                    semantic_key(candidate.objective_key),
                    candidate.content_kind,
                    "staged",
                    quest_id,
                    fingerprint,
                    record.model_dump_json(),
                    record.created_at,
                ),
            )
            if is_quest:
                connection.execute(
                    "INSERT INTO narrative_quest_reservations VALUES(?,?,?,'reserved')",
                    (content_id, session_id, episode_id),
                )
        return record

    def freeze_turn_policy(self, session_id: str, turn_id: str, policy_digest: str) -> None:
        """Bind staged content once to the final exact turn policy before emission."""
        if not policy_digest:
            raise ValueError("a final policy digest is required")
        with self.transaction() as connection:
            rows = connection.execute(
                "SELECT record_json,policy_frozen FROM narrative_content "
                "WHERE session_id=? AND turn_id=? AND status='staged'",
                (session_id, turn_id),
            ).fetchall()
            for row in rows:
                record = _read_record(row)
                if row["policy_frozen"] and record.policy_digest != policy_digest:
                    raise ContentReviewError("staged content policy is already frozen")
                record.policy_digest = policy_digest
                _save_record(connection, record)
                connection.execute(
                    "UPDATE narrative_content SET policy_frozen=1 WHERE content_id=?",
                    (record.content_id,),
                )

    def get_staged_for_turn(self, session_id: str, turn_id: str) -> list[StagedContent]:
        with self.connection() as connection:
            rows = connection.execute(
                "SELECT record_json FROM narrative_content "
                "WHERE session_id=? AND turn_id=? AND status='staged' ORDER BY content_id",
                (session_id, turn_id),
            ).fetchall()
        return [_read_record(row) for row in rows]

    def publish_turn_in_connection(
        self,
        connection: sqlite3.Connection,
        session_id: str,
        turn_id: str,
        *,
        expected_policy_digest: str | None = None,
        current_objective_refs: Sequence[ObjectiveRef] | None = None,
    ) -> list[StagedContent]:
        if not connection.in_transaction:
            raise ValueError("content publication requires the caller's completed-turn transaction")
        rows = connection.execute(
            "SELECT record_json FROM narrative_content "
            "WHERE session_id=? AND turn_id=? AND status='staged' ORDER BY content_id",
            (session_id, turn_id),
        ).fetchall()
        result: list[StagedContent] = []
        for row in rows:
            record = _read_record(row)
            if record.candidate.expires_at is not None and record.candidate.expires_at <= utc_now():
                raise ContentReviewError("temporary content expired before delivery completed")
            if (
                expected_policy_digest is not None
                and record.policy_digest != expected_policy_digest
            ):
                raise ContentReviewError("completion policy differs from staged content policy")
            self._validate_current_refs(
                connection,
                session_id,
                record.reviewed,
                current_objective_refs,
            )
            self._check_published_facts(connection, session_id, record.reviewed)
            record.status = "published"
            record.published_at = datetime_text()
            _save_record(connection, record)
            if record.quest_id is not None:
                connection.execute(
                    "UPDATE narrative_quest_reservations SET status='consumed' WHERE content_id=?",
                    (record.content_id,),
                )
                quest = PublishedQuest(
                    quest_id=record.quest_id,
                    session_id=session_id,
                    objective_key=record.candidate.objective_key,
                    content_id=record.content_id,
                    status="offered",
                )
                connection.execute(
                    "INSERT INTO narrative_quests(session_id,quest_id,record_json) VALUES(?,?,?)",
                    (session_id, quest.quest_id, quest.model_dump_json()),
                )
                ref = ObjectiveRef(objective_id=quest.quest_id, quest_id=quest.quest_id)
                self.register_objective_in_connection(connection, session_id, ref)
            result.append(record)
        return result

    def discard_turn_in_connection(
        self,
        connection: sqlite3.Connection,
        session_id: str,
        turn_id: str,
    ) -> int:
        if not connection.in_transaction:
            raise ValueError("discard requires a transaction")
        rows = connection.execute(
            "SELECT record_json FROM narrative_content "
            "WHERE session_id=? AND turn_id=? AND status='staged'",
            (session_id, turn_id),
        ).fetchall()
        for row in rows:
            record = _read_record(row)
            record.status = "discarded"
            _save_record(connection, record)
            connection.execute(
                "DELETE FROM narrative_quest_reservations WHERE content_id=? AND status='reserved'",
                (record.content_id,),
            )
        return len(rows)

    def discard_turn(self, session_id: str, turn_id: str) -> int:
        with self.transaction() as connection:
            return self.discard_turn_in_connection(connection, session_id, turn_id)

    def list_published(
        self,
        session_id: str,
        npc_id: str | None = None,
        *,
        limit: int = 100,
    ) -> list[StagedContent]:
        """Internal audit/authorization listing; use visible_context for model inputs."""
        if limit < 1:
            return []
        with self.connection() as connection:
            rows = connection.execute(
                "SELECT record_json FROM narrative_content "
                "WHERE session_id=? AND status='published' ORDER BY published_at,content_id",
                (session_id,),
            ).fetchall()
        records = [_read_record(row) for row in rows]
        records = [
            record
            for record in records
            if record.candidate.expires_at is None or record.candidate.expires_at > utc_now()
        ]
        return [
            record
            for record in records
            if (
                npc_id is None or record.npc_id == npc_id or record.candidate.visibility == "public"
            )
        ][:limit]

    def visible_context(
        self,
        session_id: str,
        npc_id: str,
        *,
        known_content_ids: Collection[str] = (),
    ) -> list[dict[str, Any]]:
        """Publication grants access; only delivery/observation grants NPC knowledge."""
        result: list[dict[str, Any]] = []
        for record in self.list_published(session_id, npc_id):
            if record.npc_id != npc_id and record.content_id not in known_content_ids:
                continue
            candidate = record.candidate
            # Even recipients of a deceptive claim see only the attributed utterance.
            facts = [
                {
                    "fact_key": fact.fact_key,
                    "statement": fact.statement,
                    "epistemic_status": fact.epistemic_status,
                    "source_npc_id": fact.source_npc_id,
                }
                for fact in candidate.facts
            ]
            steps = [step.model_dump(mode="json") for step in candidate.steps]
            events = [event.model_dump(mode="json") for event in candidate.events]
            if record.quest_id is not None:
                local_ref = ObjectiveRef(
                    objective_id=record.quest_id,
                    quest_id=record.quest_id,
                ).model_dump(mode="json")
                for item in [*steps, *events]:
                    if item["objective"]["objective_id"] == candidate.candidate_id:
                        item["objective"] = local_ref
            result.append(
                {
                    "content_id": record.content_id,
                    "quest_id": record.quest_id,
                    "kind": candidate.content_kind,
                    "scope": candidate.scope.scope,
                    "title": candidate.title,
                    "summary": (
                        "；".join(fact.statement for fact in candidate.facts)
                        if record.npc_id != npc_id and candidate.facts
                        else candidate.summary
                    ),
                    "facts": facts,
                    "steps": steps,
                    "events": events,
                }
            )
        return result

    def get_published_facts(self, session_id: str) -> list[ContentFact]:
        """Runtime canonical checks only: never use this as an NPC's knowledge."""
        return [
            fact
            for record in self.list_published(session_id)
            for fact in record.candidate.facts
            if fact.epistemic_status == "world_fact"
        ]

    def list_quests(self, session_id: str, npc_id: str | None = None) -> list[PublishedQuest]:
        visible_ids = {record.content_id for record in self.list_published(session_id, npc_id)}
        with self.connection() as connection:
            rows = connection.execute(
                "SELECT record_json FROM narrative_quests WHERE session_id=? ORDER BY quest_id",
                (session_id,),
            ).fetchall()
        quests = [PublishedQuest.model_validate_json(row["record_json"]) for row in rows]
        return [quest for quest in quests if quest.content_id in visible_ids]

    def advance_quest_in_connection(
        self,
        connection: sqlite3.Connection,
        session_id: str,
        quest_id: str,
        event_id: str,
        target_status: str,
    ) -> PublishedQuest:
        """Trusted accept/complete events are separate from introducing a quest."""
        if not connection.in_transaction:
            raise ValueError("quest lifecycle changes require a caller transaction")
        prior = connection.execute(
            "SELECT quest_id,target_status FROM narrative_quest_events "
            "WHERE session_id=? AND event_id=?",
            (session_id, event_id),
        ).fetchone()
        row = connection.execute(
            "SELECT record_json FROM narrative_quests WHERE session_id=? AND quest_id=?",
            (session_id, quest_id),
        ).fetchone()
        if row is None:
            raise ContentReviewError("quest is not published in this instance")
        quest = PublishedQuest.model_validate_json(row["record_json"])
        if prior is not None:
            if prior["quest_id"] != quest_id or prior["target_status"] != target_status:
                raise IdempotencyConflictError("quest event was reused with a different payload")
            return quest
        allowed = {
            "offered": {"accepted", "declined"},
            "accepted": {"active", "completed", "failed"},
            "active": {"completed", "failed"},
            "completed": set(),
            "failed": set(),
            "declined": set(),
        }
        if target_status not in allowed[quest.status]:
            raise ContentReviewError(f"invalid quest transition: {quest.status} -> {target_status}")
        payload = quest.model_dump()
        payload.update(status=target_status, version=quest.version + 1)
        updated = PublishedQuest.model_validate(payload)
        connection.execute(
            "UPDATE narrative_quests SET record_json=? WHERE session_id=? AND quest_id=?",
            (updated.model_dump_json(), session_id, quest_id),
        )
        connection.execute(
            "INSERT INTO narrative_quest_events VALUES(?,?,?,?)",
            (session_id, event_id, quest_id, target_status),
        )
        self.register_objective_in_connection(
            connection,
            session_id,
            ObjectiveRef(objective_id=quest_id, quest_id=quest_id, version=updated.version),
        )
        return updated

    def advance_quest(
        self,
        session_id: str,
        quest_id: str,
        event_id: str,
        target_status: str,
    ) -> PublishedQuest:
        with self.transaction() as connection:
            return self.advance_quest_in_connection(
                connection,
                session_id,
                quest_id,
                event_id,
                target_status,
            )

    def quota_usage(self, session_id: str, episode_id: str) -> dict[str, int]:
        with self.connection() as connection:
            rows = connection.execute(
                "SELECT status,COUNT(*) AS count FROM narrative_quest_reservations "
                "WHERE session_id=? AND episode_id=? GROUP BY status",
                (session_id, episode_id),
            ).fetchall()
        counts = {"reserved": 0, "consumed": 0}
        counts.update({row["status"]: row["count"] for row in rows})
        return counts
