import json

import httpx
import pytest

from engine.explain import PROVIDERS, ExplainError, LLMClient, explain

EVIDENCE = {"score": {"grower_id": "G0001", "season": 2024, "label": "review recommended"}, "purchases": []}


def fake_server(reply=None, status=200, finish_reason="stop"):
    """An OpenAI-compatible chat completions server that records every request it receives."""
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if status != 200:
            return httpx.Response(status, json={"error": {"message": "nope"}})
        return httpx.Response(200, json={
            "choices": [{"finish_reason": finish_reason, "message": {"role": "assistant", "content": reply}}]
        })

    return httpx.MockTransport(handler), seen


def _client(**server):
    transport, seen = fake_server(**server)
    return LLMClient("custom", "http://fake/v1", "test-model", api_key="secret", transport=transport), seen


def test_explain_sends_evidence_and_returns_text():
    client, seen = _client(reply="  Plain words.  ")
    assert explain(EVIDENCE, client) == "Plain words."

    request = seen[0]
    assert request.url == "http://fake/v1/chat/completions"
    assert request.headers["authorization"] == "Bearer secret"
    body = json.loads(request.content)
    assert body["model"] == "test-model"
    assert body["messages"][0]["role"] == "system" and "not a verdict" in body["messages"][0]["content"]
    assert json.loads(body["messages"][1]["content"]) == EVIDENCE


def test_local_server_needs_no_key():
    transport, seen = fake_server(reply="ok")
    LLMClient("ollama", PROVIDERS["ollama"][0], "llama3.2", transport=transport).complete("s", "u")
    assert "authorization" not in seen[0].headers


def test_empty_reply_raises_with_finish_reason():
    client, _ = _client(reply="", finish_reason="length")
    with pytest.raises(ExplainError, match="length"):
        explain(EVIDENCE, client)


def test_http_error_propagates():
    client, _ = _client(status=401)
    with pytest.raises(httpx.HTTPStatusError):
        explain(EVIDENCE, client)


def test_from_env_is_disabled_when_unset(monkeypatch):
    monkeypatch.delenv("TRUEACRE_LLM_PROVIDER", raising=False)
    assert LLMClient.from_env() is None


def test_from_env_provider_presets(monkeypatch):
    for var in ("TRUEACRE_LLM_BASE_URL", "TRUEACRE_LLM_API_KEY"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("TRUEACRE_LLM_PROVIDER", "gemini")
    monkeypatch.setenv("TRUEACRE_LLM_MODEL", "gemini-x")
    monkeypatch.setenv("GEMINI_API_KEY", "k")
    c = LLMClient.from_env()
    assert (c.provider, c.base_url, c.model, c.api_key) == ("gemini", PROVIDERS["gemini"][0], "gemini-x", "k")

    monkeypatch.setenv("TRUEACRE_LLM_PROVIDER", "ollama")
    monkeypatch.setenv("TRUEACRE_LLM_MODEL", "llama3.2")
    monkeypatch.setenv("TRUEACRE_LLM_BASE_URL", "http://gpu-box:11434/v1/")  # remote Ollama, trailing slash
    c = LLMClient.from_env()
    assert (c.base_url, c.api_key) == ("http://gpu-box:11434/v1", None)


def test_from_env_rejects_misconfiguration(monkeypatch):
    monkeypatch.setenv("TRUEACRE_LLM_PROVIDER", "nope")
    monkeypatch.setenv("TRUEACRE_LLM_MODEL", "m")
    with pytest.raises(ValueError, match="must be one of"):
        LLMClient.from_env()

    monkeypatch.setenv("TRUEACRE_LLM_PROVIDER", "openai")
    monkeypatch.delenv("TRUEACRE_LLM_MODEL", raising=False)
    with pytest.raises(ValueError, match="TRUEACRE_LLM_MODEL"):
        LLMClient.from_env()

    monkeypatch.setenv("TRUEACRE_LLM_PROVIDER", "custom")
    monkeypatch.setenv("TRUEACRE_LLM_MODEL", "m")
    monkeypatch.delenv("TRUEACRE_LLM_BASE_URL", raising=False)
    with pytest.raises(ValueError, match="TRUEACRE_LLM_BASE_URL"):
        LLMClient.from_env()
