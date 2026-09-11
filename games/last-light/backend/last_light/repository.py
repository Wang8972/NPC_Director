"""Versioned JSON storage with atomic replacement and an explicit prior backup."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import tempfile
from datetime import datetime, timezone

from .engine import WorldEngine
from .models import validate_session_id, validate_state

MAX_SAVE_BYTES = 16 * 1024 * 1024


def _canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def _unique_keys(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate JSON key in save")
        result[key] = value
    return result


class Repository:
    def __init__(self, data_dir):
        self.data_dir = Path(data_dir).expanduser().resolve()
        self.data_dir.mkdir(parents=True, exist_ok=True)

    def _path(self, sid, backup=False):
        return self.data_dir / (validate_session_id(sid) + (".backup.json" if backup else ".json"))

    @staticmethod
    def _encode(state):
        state = validate_state(state)
        document = {"repository_version": 1, "state": state,
                    "sha256": hashlib.sha256(_canonical(state)).hexdigest()}
        data = _canonical(document)
        if len(data) > MAX_SAVE_BYTES:
            raise ValueError("Save exceeds storage limit")
        return data

    def _read(self, path, sid):
        if path.is_symlink():
            raise ValueError("Save symlinks are not accepted")
        if path.stat().st_size > MAX_SAVE_BYTES:
            raise ValueError("Save exceeds storage limit")
        try:
            document = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=_unique_keys)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError("Save is not valid UTF-8 JSON") from exc
        if not isinstance(document, dict) or document.get("repository_version") != 1:
            raise ValueError("Unsupported repository format")
        state = validate_state(document.get("state"))
        if state["session_id"] != sid:
            raise ValueError("Save session id does not match its filename")
        if hashlib.sha256(_canonical(state)).hexdigest() != document.get("sha256"):
            raise ValueError("Save checksum mismatch")
        return state

    def _atomic_write(self, path, data):
        fd, name = tempfile.mkstemp(prefix=".lastlight-", suffix=".tmp", dir=self.data_dir)
        try:
            with os.fdopen(fd, "wb") as stream:
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(name, path)
            if hasattr(os, "O_DIRECTORY"):
                directory = os.open(self.data_dir, os.O_RDONLY | os.O_DIRECTORY)
                try:
                    os.fsync(directory)
                finally:
                    os.close(directory)
        finally:
            if os.path.exists(name):
                os.unlink(name)

    def create(self, mode="live"):
        engine = WorldEngine(mode=mode)
        self.save(engine)
        return engine

    def get(self, sid):
        sid = validate_session_id(sid)
        return WorldEngine(state=self._read(self._path(sid), sid))

    def save(self, engine):
        state = validate_state(engine.state)
        sid = state["session_id"]
        path = self._path(sid)
        data = self._encode(state)
        if path.exists() or path.is_symlink():
            previous = self._read(path, sid)
            old_data = self._encode(previous)
            if old_data == data:
                return
            self._atomic_write(self._path(sid, backup=True), old_data)
        self._atomic_write(path, data)

    def restore(self, sid):
        """Restore the preceding distinct autosave, without silently falling back."""
        sid = validate_session_id(sid)
        restored = self._read(self._path(sid, backup=True), sid)
        primary = self._path(sid)
        try:
            previous = self._read(primary, sid)
        except (ValueError, OSError):
            previous = None
        if previous is not None:
            self._atomic_write(self._path(sid, backup=True), self._encode(previous))
        self._atomic_write(primary, self._encode(restored))
        return WorldEngine(state=restored)

    def list_sessions(self):
        results = []
        for path in self.data_dir.glob("*.json"):
            if path.name.endswith(".backup.json"):
                continue
            sid = path.stem
            try:
                validate_session_id(sid)
                state = self._read(path, sid)
                engine = WorldEngine(state=state)
                updated = datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).isoformat()
            except (ValueError, OSError):
                continue
            results.append({"session_id": sid, "updated_at": updated, "chapter": engine.chapter,
                            "tick": state["tick"], "mode": state["mode"]})
        return sorted(results, key=lambda item: item["updated_at"], reverse=True)
