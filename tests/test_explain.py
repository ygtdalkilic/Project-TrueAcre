import json
from types import SimpleNamespace

import pytest

from engine.explain import MODEL, ExplainError, explain


class FakeModels:
    def __init__(self, response):
        self.response = response
        self.calls = []

    def generate_content(self, **kwargs):
        self.calls.append(kwargs)
        return self.response


class FakeClient:
    """Stands in for google.genai.Client so no test ever touches the network."""

    def __init__(self, response):
        self.models = FakeModels(response)


def fake_response(text=None, finish_reason=None):
    candidates = [SimpleNamespace(finish_reason=finish_reason)] if finish_reason else []
    return SimpleNamespace(text=text, candidates=candidates, prompt_feedback=None)


EVIDENCE = {"score": {"grower_id": "G0001", "season": 2024, "label": "review recommended"}, "purchases": []}


def test_explain_sends_evidence_and_returns_text():
    client = FakeClient(fake_response(text="  Plain words.  "))
    assert explain(EVIDENCE, client) == "Plain words."
    call = client.models.calls[0]
    assert call["model"] == MODEL
    assert json.loads(call["contents"]) == EVIDENCE
    assert "not a verdict" in call["config"].system_instruction


def test_empty_text_raises_with_finish_reason():
    with pytest.raises(ExplainError, match="SAFETY"):
        explain(EVIDENCE, FakeClient(fake_response(text=None, finish_reason="SAFETY")))
