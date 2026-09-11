import json
from pathlib import Path
from unittest.mock import patch

import pytest

from last_light.engine import WorldEngine
from last_light.repository import Repository


def test_create_get_and_metadata_are_distinct_objects(tmp_path):
    repo = Repository(tmp_path)
    original = repo.create(mode="rehearsal")
    sid = original.state["session_id"]
    loaded = repo.get(sid)
    assert loaded is not original
    assert loaded.state == original.state
    assert repo.list_sessions()[0]["mode"] == "rehearsal"
    assert repo.list_sessions()[0]["tick"] == 0


def test_previous_distinct_save_and_explicit_restore(tmp_path):
    repo = Repository(tmp_path)
    engine = repo.create(mode="rehearsal")
    sid = engine.state["session_id"]
    engine.state["revision"] = 1
    repo.save(engine)
    repo.save(engine)  # An identical persist must not erase the previous checkpoint.
    assert repo.get(sid).state["revision"] == 1
    assert repo.restore(sid).state["revision"] == 0
    assert repo.get(sid).state["revision"] == 0
    assert repo.restore(sid).state["revision"] == 1


def test_get_never_returns_a_cached_engine(tmp_path):
    repo = Repository(tmp_path)
    engine = repo.create()
    first = repo.get(engine.state["session_id"])
    engine.state["revision"] += 1
    repo.save(engine)
    second = repo.get(engine.state["session_id"])
    assert first.state["revision"] == 0
    assert second.state["revision"] == 1


@pytest.mark.parametrize("sid", ["../outside", "/tmp/outside", "a/b", "a\\b", "", "..", "x" * 81])
def test_session_path_validation(tmp_path, sid):
    repo = Repository(tmp_path)
    with pytest.raises(ValueError):
        repo.get(sid)
    with pytest.raises(ValueError):
        repo.restore(sid)


def test_corrupt_primary_is_rejected_but_explicit_backup_restore_works(tmp_path):
    repo = Repository(tmp_path)
    engine = repo.create()
    sid = engine.state["session_id"]
    engine.state["revision"] = 7
    repo.save(engine)
    repo._path(sid).write_bytes(b'{"truncated":')
    with pytest.raises(ValueError):
        repo.get(sid)
    assert repo.restore(sid).state["revision"] == 0
    assert repo.get(sid).state["revision"] == 0


def test_checksum_detects_valid_json_tampering(tmp_path):
    repo = Repository(tmp_path)
    engine = repo.create()
    path = repo._path(engine.state["session_id"])
    document = json.loads(path.read_text())
    document["state"]["tick"] += 1
    path.write_text(json.dumps(document))
    with pytest.raises(ValueError, match="checksum"):
        repo.get(engine.state["session_id"])


def test_invalid_state_is_rejected_before_overwriting_a_save(tmp_path):
    repo = Repository(tmp_path)
    engine = repo.create()
    sid = engine.state["session_id"]
    before = repo._path(sid).read_bytes()
    engine.state["flags"].append("aux_restored")
    with pytest.raises(ValueError, match="causal"):
        repo.save(engine)
    assert repo._path(sid).read_bytes() == before


def test_atomic_failure_preserves_primary_and_removes_temporary_file(tmp_path):
    repo = Repository(tmp_path)
    engine = repo.create()
    sid = engine.state["session_id"]
    before = repo._path(sid).read_bytes()
    engine.state["revision"] = 1
    with patch("last_light.repository.os.replace", side_effect=OSError("disk interrupted")):
        with pytest.raises(OSError):
            repo.save(engine)
    assert repo._path(sid).read_bytes() == before
    assert not list(tmp_path.glob("*.tmp"))


def test_filename_cannot_select_another_sessions_state(tmp_path):
    repo = Repository(tmp_path)
    engine = repo.create()
    repo._path("other_session").write_bytes(repo._path(engine.state["session_id"]).read_bytes())
    with pytest.raises(ValueError, match="filename"):
        repo.get("other_session")


def test_symlink_saves_are_rejected(tmp_path):
    repo = Repository(tmp_path / "store")
    engine = repo.create()
    outside = tmp_path / "external.json"
    outside.write_bytes(repo._path(engine.state["session_id"]).read_bytes())
    repo._path(engine.state["session_id"]).unlink()
    repo._path(engine.state["session_id"]).symlink_to(outside)
    with pytest.raises(ValueError, match="symlink"):
        repo.get(engine.state["session_id"])


def test_duplicate_json_keys_are_rejected(tmp_path):
    repo = Repository(tmp_path)
    engine = repo.create()
    sid = engine.state["session_id"]
    repo._path(sid).write_text('{"repository_version":1,"repository_version":2}')
    with pytest.raises(ValueError, match="Duplicate"):
        repo.get(sid)


def test_missing_backup_is_not_silently_treated_as_success(tmp_path):
    repo = Repository(tmp_path)
    engine = repo.create()
    with pytest.raises(FileNotFoundError):
        repo.restore(engine.state["session_id"])


def test_listing_omits_corrupt_files_and_backup_duplicates(tmp_path):
    repo = Repository(tmp_path)
    engine = repo.create()
    engine.state["revision"] += 1
    repo.save(engine)
    (tmp_path / "broken.json").write_text("bad json")
    assert [row["session_id"] for row in repo.list_sessions()] == [engine.state["session_id"]]
