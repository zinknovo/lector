import pytest
from importlib import import_module

from app.agent.llm import get_llm


def clear_llm_env(monkeypatch):
    for name in ("LLM_API_KEY", "LLM_MODEL_NAME", "LLM_BASE_URL", "LLM_TEMPERATURE"):
        monkeypatch.delenv(name, raising=False)


def test_get_llm_uses_deepseek_defaults(monkeypatch):
    clear_llm_env(monkeypatch)
    monkeypatch.setenv("LLM_API_KEY", "sk-test")

    llm = get_llm(load_env=False)

    assert llm.model_name == "deepseek-v4-pro"
    assert str(llm.openai_api_base).rstrip("/") == "https://api.deepseek.com"
    assert llm.temperature == 0.1


def test_get_llm_allows_env_overrides(monkeypatch):
    clear_llm_env(monkeypatch)
    monkeypatch.setenv("LLM_API_KEY", "sk-test")
    monkeypatch.setenv("LLM_MODEL_NAME", "deepseek-reasoner")
    monkeypatch.setenv("LLM_BASE_URL", "https://example.test/v1")
    monkeypatch.setenv("LLM_TEMPERATURE", "0.2")

    llm = get_llm(load_env=False)

    assert llm.model_name == "deepseek-reasoner"
    assert str(llm.openai_api_base).rstrip("/") == "https://example.test/v1"
    assert llm.temperature == 0.2


def test_get_llm_requires_api_key(monkeypatch):
    clear_llm_env(monkeypatch)

    with pytest.raises(RuntimeError, match="LLM_API_KEY"):
        get_llm(load_env=False)


def test_agent_main_module_is_the_cli_entrypoint():
    agent_main = import_module("app.agent.main")

    assert callable(agent_main.main)
