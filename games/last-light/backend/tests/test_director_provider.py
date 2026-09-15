from last_light.director import DirectorUnavailable, ProviderConfig, _compatible_wire
from last_light.director import _provider_config


def test_codex_opt_in_ignores_unrelated_inherited_openai_credentials(monkeypatch, tmp_path):
    monkeypatch.setenv("CODEX_HOME", str(tmp_path))
    monkeypatch.setenv("LAST_LIGHT_USE_CODEX_AUTH", "1")
    monkeypatch.setenv("LAST_LIGHT_API_KEY", "")
    monkeypatch.setenv("LAST_LIGHT_BASE_URL", "")
    monkeypatch.setenv("OPENAI_API_KEY", "unrelated-test-key")
    monkeypatch.setenv("OPENAI_BASE_URL", "https://unrelated.invalid/v1")
    monkeypatch.setenv("IDEALAB_TEST_KEY", "provider-test-key")
    (tmp_path / "config.toml").write_text('model_provider="idealab"\n[model_providers.idealab]\nbase_url="https://idealab.alibaba-inc.com/api/openai/v1"\nwire_api="responses"\nenv_key="IDEALAB_TEST_KEY"\n')
    config = _provider_config(load_secret=True)
    assert config.api_key == "provider-test-key"
    assert config.base_url == "https://idealab.alibaba-inc.com/api/openai/v1"


def test_generic_openai_configuration_remains_available_without_codex_opt_in(monkeypatch):
    monkeypatch.setenv("LAST_LIGHT_USE_CODEX_AUTH", "0")
    monkeypatch.setenv("LAST_LIGHT_API_KEY", "")
    monkeypatch.setenv("LAST_LIGHT_BASE_URL", "")
    monkeypatch.setenv("OPENAI_API_KEY", "generic-test-key")
    monkeypatch.setenv("OPENAI_BASE_URL", "https://generic.invalid/v1")
    config = _provider_config(load_secret=True)
    assert config.api_key == "generic-test-key"
    assert config.base_url == "https://generic.invalid/v1"


def test_idealab_qwen_uses_chat_completions_even_when_codex_advertises_responses():
    config = ProviderConfig("present", "https://idealab.alibaba-inc.com/api/openai/v1", "responses")
    assert _compatible_wire("qwen3.8-max", config) == "chat_completions"


def test_other_models_and_providers_preserve_configured_wire():
    assert _compatible_wire("gpt-5", ProviderConfig("present", "https://example.test/v1", "responses")) == "responses"
    assert _compatible_wire("qwen3.8-max", ProviderConfig("present", "https://example.test/v1", "responses")) == "responses"


def test_unknown_wire_is_rejected_before_network_request():
    try:
        _compatible_wire("qwen3.8-max", ProviderConfig("present", "https://example.test/v1", "unknown"))
    except DirectorUnavailable as error:
        assert "不支持的模型协议" in str(error)
    else:
        raise AssertionError("unknown wire must fail closed")
