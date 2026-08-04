from __future__ import annotations

import argparse
import json
import platform
import shutil
import sqlite3
import subprocess
from datetime import UTC, datetime
from pathlib import Path

from npc_director.prototype.spikes import run_backend_spikes


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run NPC Director prototype backend spikes")
    parser.add_argument(
        "--workdir",
        type=Path,
        default=Path("artifacts/prototype-spikes/work"),
        help="Directory for temporary SQLite evidence",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("artifacts/prototype-spikes/backend-report.json"),
        help="JSON evidence report",
    )
    return parser.parse_args()


def git_commit() -> str:
    if shutil.which("git") is None:
        return "unavailable"
    result = subprocess.run(
        ["git", "rev-parse", "--short", "HEAD"],
        check=False,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip() or "unavailable"


def main() -> int:
    args = parse_args()
    report = run_backend_spikes(args.workdir)
    report["environment"] = {
        "recorded_at": datetime.now(UTC).isoformat(),
        "python": platform.python_version(),
        "sqlite": sqlite3.sqlite_version,
        "platform": platform.platform(),
        "commit": git_commit(),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    summary = {
        "status": report["status"],
        "output": str(args.output),
        "spikes": {
            name: details["status"] for name, details in report["reports"].items()
        },
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if report["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
