"""Process-safe evaluation ceiling, shared by every model role and retry."""

from __future__ import annotations

import json
import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from uuid import uuid4


class EvaluationBudgetExceeded(RuntimeError):
    pass


class TokenLedger:
    TOTAL = 10_000_000
    PILOT = 300_000

    def __init__(self, path, *, phase="pilot"):
        if phase not in {"pilot", "full"}:
            raise ValueError("invalid evaluation phase")
        self.phase = phase
        self.path = str(path)
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS charges(
                id TEXT PRIMARY KEY, phase TEXT NOT NULL, role TEXT NOT NULL,
                reserved INTEGER NOT NULL, charged INTEGER, usage_known INTEGER);
                CREATE TABLE IF NOT EXISTS stops(phase TEXT PRIMARY KEY, reason TEXT NOT NULL);
            """)

    @contextmanager
    def connect(self):
        conn = sqlite3.connect(self.path, timeout=30)
        try:
            with conn:
                yield conn
        finally:
            conn.close()

    def reserve(self, amount, role):
        if amount < 0:
            raise ValueError("negative reservation")
        with self.connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            total = conn.execute(
                "SELECT COALESCE(SUM(COALESCE(charged,reserved)),0) FROM charges"
            ).fetchone()[0]
            phase = conn.execute(
                "SELECT COALESCE(SUM(COALESCE(charged,reserved)),0) FROM charges WHERE phase=?",
                (self.phase,),
            ).fetchone()[0]
            blocked = conn.execute("SELECT 1 FROM stops WHERE phase=?", (self.phase,)).fetchone()
            if (
                blocked
                or total + amount > self.TOTAL
                or (self.phase == "pilot" and phase + amount > self.PILOT)
            ):
                conn.execute(
                    "INSERT OR REPLACE INTO stops VALUES (?,?)",
                    (self.phase, "reservation_exceeds_ceiling"),
                )
                conn.commit()
                raise EvaluationBudgetExceeded(
                    "evaluation token ceiling reached; no model call issued"
                )
            key = uuid4().hex
            conn.execute(
                "INSERT INTO charges(id,phase,role,reserved) VALUES (?,?,?,?)",
                (key, self.phase, role, amount),
            )
            return key

    def settle(self, key, total=None):
        with self.connect() as conn:
            row = conn.execute("SELECT reserved,charged FROM charges WHERE id=?", (key,)).fetchone()
            if row is None:
                raise ValueError("unknown evaluation reservation")
            charged = row[0] if total is None else total
            if charged < 0:
                raise ValueError("negative usage")
            if row[1] is not None:
                if row[1] != charged:
                    raise ValueError("usage changed on replay")
                return
            conn.execute(
                "UPDATE charges SET charged=?,usage_known=? WHERE id=?",
                (charged, int(total is not None), key),
            )

    def snapshot(self):
        with self.connect() as conn:
            used, count, unknown = conn.execute(
                "SELECT COALESCE(SUM(COALESCE(charged,reserved)),0),"
                "COUNT(*),COALESCE(SUM(usage_known IS NULL OR usage_known=0),0) FROM charges"
            ).fetchone()
            stopped = bool(
                conn.execute("SELECT 1 FROM stops WHERE phase=?", (self.phase,)).fetchone()
            )
        return {
            "charged_tokens": used,
            "limit": self.TOTAL,
            "pilot_limit": self.PILOT,
            "calls": count,
            "unknown_usage_calls": unknown,
            "phase": self.phase,
            "stopped": stopped,
        }


def configured_ledger():
    path = os.getenv("NPC_DIRECTOR_EVAL_LEDGER")
    return TokenLedger(path, phase=os.getenv("NPC_DIRECTOR_EVAL_PHASE", "pilot")) if path else None


def reservation_size(agent, text, output_type):
    # UTF-8 bytes conservatively bound token input, including schema and prompt.
    schema = json.dumps(output_type.model_json_schema(), ensure_ascii=False)
    return (
        len((str(agent.instructions) + text + schema).encode())
        + agent.model_settings.max_tokens
        + 2048
    )
