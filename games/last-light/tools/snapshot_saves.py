"""Snapshot world saves, SQLite memory and checkpoints without credentials or WAL files."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sqlite3
import tempfile
import zipfile


def snapshot(source: Path, output: Path):
    source = source.expanduser().resolve()
    output = output.expanduser().resolve()
    if output.is_relative_to(source):
        raise ValueError("Archive must be outside the live save directory")
    files = sorted(p for p in source.rglob("*") if p.is_file() and
                   not p.name.endswith(("-wal", "-shm", "-journal")))
    if not files or not (source / "world").is_dir():
        raise ValueError("Expected a saves directory with world/ and director/")
    plain = {}
    databases = []
    for path in files:
        if path.is_symlink():
            raise ValueError("Save symlinks are not supported")
        rel = path.relative_to(source).as_posix()
        with path.open("rb") as stream:
            header = stream.read(16)
        if header == b"SQLite format 3\x00":
            databases.append((path, rel))
        elif path.suffix == ".json":
            data = path.read_bytes()
            json.loads(data)
            plain[rel] = data
        else:
            raise ValueError("Unexpected save file: " + rel)
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="lastlight-snapshot-") as temp:
        root = Path(temp)
        payload = dict(plain)
        for path, rel in databases:
            target = root / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            origin = sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)
            copy = sqlite3.connect(target)
            try:
                origin.backup(copy)
                if copy.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                    raise ValueError("Invalid SQLite snapshot: " + rel)
            finally:
                copy.close()
                origin.close()
            payload[rel] = target.read_bytes()
        if any((source / rel).read_bytes() != data for rel, data in plain.items()):
            raise RuntimeError("World saves changed during capture; close the game/backend and retry")
        manifest = {
            "kind": "world saves + NPC memory + checkpoints; no model credentials",
            "sqlite_databases": len(databases),
            "files": [{"path": rel, "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}
                      for rel, data in sorted(payload.items())],
        }
        with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
            for rel, data in sorted(payload.items()):
                archive.writestr(rel, data)
        with zipfile.ZipFile(output) as archive:
            if archive.testzip() is not None:
                raise ValueError("Archive verification failed")
    manifest["archive_sha256"] = hashlib.sha256(output.read_bytes()).hexdigest()
    output.with_suffix(".manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
    return {"files": len(manifest["files"]), "sqlite_databases": len(databases),
            "archive": str(output), "bytes": output.stat().st_size}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(snapshot(args.source, args.output), ensure_ascii=False))
