from __future__ import annotations

import json
from pathlib import Path

import pytest

from eval.episode_runner import load_codex_auth_environment
from npc_director.context import token_budget


def test_token_reservation_uses_tokenizer_without_charging_chinese_utf8_bytes():
    text = "玩家问巡逻记录是否可靠，守卫只引用亲眼观察的部分。" * 200
    estimate = token_budget.reserve_prompt_tokens(text, model="gpt-test")
    encoding = token_budget._encoding("o200k_base")
    if encoding is None:
        pytest.skip("tokenizer vocabulary unavailable")
    assert len(encoding.encode(text)) < estimate < len(text.encode("utf-8"))


def test_token_reservation_fails_closed_without_vocabulary(monkeypatch):
    monkeypatch.setattr(token_budget, "_encoding", lambda _: None)
    assert token_budget.reserve_prompt_tokens("秘密") == len("秘密".encode()) + 2048


@pytest.fixture
def fake_codex(tmp_path, monkeypatch):
    root = tmp_path / ".codex"
    root.mkdir()
    (root / "config.toml").write_text(
        'model_provider = "test"\n[model_providers.test]\n'
        'env_key = "NPC_TEST_API_TOKEN"\nbase_url = "https://example.invalid/v1"\n'
        'wire_api = "responses"\n'
    )
    (root / "auth.json").write_text(json.dumps({"OPENAI_API_KEY": "fake-file-token"}))
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    for key in (
        "OPENAI_API_KEY",
        "OPENAI_BASE_URL",
        "NPC_TEST_API_TOKEN",
        "NPC_DIRECTOR_OPENAI_API",
    ):
        monkeypatch.delenv(key, raising=False)
    # Avoid changing SDK globals across tests while still checking environment mapping.
    monkeypatch.setattr("agents.set_default_openai_api", lambda _: None)
    monkeypatch.setattr("agents.set_tracing_disabled", lambda _: None)
    return root


def test_codex_provider_auth_maps_in_process_without_writing_or_printing(fake_codex, capsys):
    import os

    before = (fake_codex / "auth.json").read_bytes()
    load_codex_auth_environment(use_sdk=True)
    assert os.environ["NPC_TEST_API_TOKEN"] == "fake-file-token"
    assert os.environ["OPENAI_API_KEY"] == "fake-file-token"
    assert os.environ["OPENAI_BASE_URL"] == "https://example.invalid/v1"
    assert (fake_codex / "auth.json").read_bytes() == before
    assert capsys.readouterr() == ("", "")


def test_explicit_sdk_auth_is_preserved(fake_codex, monkeypatch):
    import os

    monkeypatch.setenv("OPENAI_API_KEY", "explicit-token")
    monkeypatch.setenv("OPENAI_BASE_URL", "https://another.invalid/v1")
    load_codex_auth_environment(use_sdk=True)
    assert os.environ["OPENAI_API_KEY"] == "explicit-token"
    assert os.environ["OPENAI_BASE_URL"] == "https://another.invalid/v1"


def test_codex_auth_cannot_be_mapped_to_unrelated_endpoint(fake_codex, monkeypatch):
    monkeypatch.setenv("OPENAI_BASE_URL", "https://another.invalid/v1")
    with pytest.raises(ValueError, match="endpoint differs"):
        load_codex_auth_environment(use_sdk=True)
