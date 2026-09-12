"""Archive immutable cognition evidence; never run models or alter source reports."""

from __future__ import annotations

import gzip
import hashlib
import json
from pathlib import Path

from eval.token_ledger import TokenLedger

ROOT = Path(__file__).resolve().parents[1]


def main():
    source = ROOT / "artifacts/cognition"
    target = ROOT / "eval/reports/cognition"
    target.mkdir(parents=True, exist_ok=True)
    manifest = []
    for path in sorted(source.glob("*.json")):
        payload = path.read_bytes()
        data = json.loads(payload)
        if "results" not in data:
            continue
        if not data.get("completed_at") and data.get("run_status") != "interrupted":
            continue
        compressed = target / (path.name + ".gz")
        packed = gzip.compress(payload, mtime=0)
        if compressed.exists() and gzip.decompress(compressed.read_bytes()) != payload:
            raise ValueError(f"refusing to replace different archived evidence: {path.name}")
        compressed.write_bytes(packed)
        digest = hashlib.sha256(payload).hexdigest()
        compact = {key: value for key, value in data.items() if key != "results"}
        compact.update(
            archive_representation="summary", full_report=compressed.name, original_sha256=digest
        )
        compact["results"] = []
        for result in data["results"]:
            item = {
                key: result.get(key)
                for key in (
                    "case_id",
                    "repeat",
                    "structural_passed",
                    "goal_passed",
                    "checks",
                    "quality",
                    "quality_status",
                    "fallback_count",
                    "errors",
                    "invariant_errors",
                    "generation_metrics",
                )
            }
            item["cognition"] = {
                world: {
                    npc: {
                        "behavior": state["behavior"],
                        "memory_count": len(state["memories"]),
                        "derived_memories": [
                            m for m in state["memories"] if m["kind"] in {"belief", "summary"}
                        ],
                        "jobs": state["jobs"],
                    }
                    for npc, state in actors.items()
                }
                for world, actors in result.get("cognition", {}).items()
            }
            compact["results"].append(item)
        (target / path.name).write_text(json.dumps(compact, ensure_ascii=False, indent=2) + "\n")
        assert hashlib.sha256(gzip.decompress(compressed.read_bytes())).hexdigest() == digest
        manifest.append(
            {
                "source": str(path.relative_to(ROOT)),
                "archive": compressed.name,
                "sha256": digest,
                "bytes": len(payload),
            }
        )
    ledger_path = source / "live-budget.db"
    if ledger_path.exists():
        ledger = TokenLedger(ledger_path, phase="full")
        snapshot = ledger.snapshot()
        with ledger.connect() as conn:
            snapshot["by_role"] = [
                dict(zip(("phase", "role", "calls", "charged_tokens"), row, strict=True))
                for row in conn.execute(
                    "SELECT phase,role,COUNT(*),SUM(COALESCE(charged,reserved)) "
                    "FROM charges GROUP BY phase,role ORDER BY phase,role"
                )
            ]
        (target / "token-ledger.json").write_text(
            json.dumps(snapshot, ensure_ascii=False, indent=2) + "\n"
        )
    (target / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({"archived_reports": len(manifest)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
