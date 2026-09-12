import json
from types import SimpleNamespace

import pytest

from engine.explain import MODEL, ExplainError, explain


class FakeMessages:
    def __init__(self, response):
        self.response = response
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return self.response


class FakeClient:
    """Stands in for anthropic.Anthropic so no test ever touches the network."""

    def __init__(self, response):
        self.messages = FakeMessages(response)


def fake_response(stop_reason="end_turn", blocks=()):
    return SimpleNamespace(stop_reason=stop_reason, content=list(blocks))


EVIDENCE = {"score": {"grower_id": "G0001", "season": 2024, "label": "review recommended"}, "purchases": []}


def test_explain_sends_evidence_and_returns_text():
    client = FakeClient(fake_response(blocks=[
        SimpleNamespace(type="thinking", thinking=""),
        SimpleNamespace(type="text", text="  Plain words.  "),
    ]))
    assert explain(EVIDENCE, client) == "Plain words."
    call = client.messages.calls[0]
    assert call["model"] == MODEL
    assert json.loads(call["messages"][0]["content"]) == EVIDENCE
    assert "not a verdict" in call["system"]


def test_refusal_raises():
    with pytest.raises(ExplainError):
        explain(EVIDENCE, FakeClient(fake_response(stop_reason="refusal")))


def test_empty_text_raises():
    with pytest.raises(ExplainError):
        explain(EVIDENCE, FakeClient(fake_response(blocks=[])))
