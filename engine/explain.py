"""Optional plain-English explanation of one grower-season, written by any chat model.

Provider-agnostic: talks to the OpenAI-compatible chat completions endpoint that Gemini, OpenAI,
Anthropic, Ollama, LM Studio, llama.cpp, vLLM and most other servers expose, over plain HTTP.
No vendor SDK, so switching provider, or running a model locally, is configuration only.

Off the scoring path by design: the score and label are computed before this runs and are
never changed by it. The model only restates the evidence and lists what an analyst should
rule out before acting on it.

Configuration (environment variables; unset TRUEACRE_LLM_PROVIDER = explanations disabled):
  TRUEACRE_LLM_PROVIDER  a key of PROVIDERS below
  TRUEACRE_LLM_MODEL     model name exactly as that provider expects it
  TRUEACRE_LLM_BASE_URL  overrides the provider's base URL (required for "custom"; handy for a remote Ollama)
  TRUEACRE_LLM_API_KEY   overrides the provider's key variable; local servers need no key
"""
import json
import os
from dataclasses import dataclass

import httpx

PROVIDERS = {  # provider -> (OpenAI-compatible base URL, environment variable holding its API key)
    "gemini": ("https://generativelanguage.googleapis.com/v1beta/openai", "GEMINI_API_KEY"),
    "openai": ("https://api.openai.com/v1", "OPENAI_API_KEY"),
    "anthropic": ("https://api.anthropic.com/v1", "ANTHROPIC_API_KEY"),  # not exercised by this repo's tests
    "ollama": ("http://localhost:11434/v1", None),
    "lmstudio": ("http://localhost:1234/v1", None),
    "custom": (None, None),
}
MAX_TOKENS = 2048  # explanations are short; the headroom is for models that count thinking tokens here
TEMPERATURE = 0.2  # restating given numbers should be steady, not creative
TIMEOUT = float(os.environ.get("TRUEACRE_LLM_TIMEOUT", "120"))  # seconds; a local model on a laptop can take a while

SYSTEM = """You write for a compliance analyst at a seed company. You receive JSON evidence about one
grower and one season: seed purchases, the acreage report, elevator receipts, the county yield
reference, and a computed Fair-Play Score with a label.

Write plain text, under 200 words, no headings or markdown:
1. Two or three sentences saying what the numbers show, in everyday language.
2. A short list of innocent explanations the analyst must rule out before contacting the grower
   (for example seed bought from a dealer outside the system, another company's or conventional
   seed when the grower has no seed statement on file, carryover seed from last year,
   custom-farmed land, grain delivered on behalf of a landlord or neighbor, a records error).
3. One sentence naming the single record that would settle it.

The label is not a verdict. Never say or imply the grower did something wrong. Do not repeat every
number; cite only the two or three that matter."""


class ExplainError(RuntimeError):
    """The model did not return usable text."""


@dataclass
class LLMClient:
    """Minimal chat-completions client. `transport` exists so tests can stand in for the server."""

    provider: str
    base_url: str
    model: str
    api_key: str | None = None
    transport: httpx.BaseTransport | None = None

    @classmethod
    def from_env(cls) -> "LLMClient | None":
        provider = os.environ.get("TRUEACRE_LLM_PROVIDER")
        if not provider:
            return None
        if provider not in PROVIDERS:
            raise ValueError(f"TRUEACRE_LLM_PROVIDER must be one of {sorted(PROVIDERS)}, not {provider!r}")
        model = os.environ.get("TRUEACRE_LLM_MODEL")
        if not model:
            raise ValueError("TRUEACRE_LLM_MODEL is required when TRUEACRE_LLM_PROVIDER is set")
        default_url, key_var = PROVIDERS[provider]
        base_url = os.environ.get("TRUEACRE_LLM_BASE_URL") or default_url
        if not base_url:
            raise ValueError("TRUEACRE_LLM_BASE_URL is required for the custom provider")
        api_key = os.environ.get("TRUEACRE_LLM_API_KEY") or (os.environ.get(key_var) if key_var else None)
        return cls(provider, base_url.rstrip("/"), model, api_key)

    def complete(self, system: str, user: str) -> str:
        headers = {"Authorization": f"Bearer {self.api_key}"} if self.api_key else {}
        body = {
            "model": self.model,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
            "max_tokens": MAX_TOKENS,
            "temperature": TEMPERATURE,
        }
        with httpx.Client(timeout=TIMEOUT, transport=self.transport) as http:
            response = http.post(f"{self.base_url}/chat/completions", json=body, headers=headers)
        response.raise_for_status()
        choice = response.json()["choices"][0]
        text = (choice["message"].get("content") or "").strip()
        if not text:
            raise ExplainError(f"the model returned no text (finish reason: {choice.get('finish_reason')})")
        return text


def explain(evidence: dict, client: LLMClient) -> str:
    """Return a plain-English explanation of an evidence bundle from the API's grower endpoint."""
    return client.complete(SYSTEM, json.dumps(evidence, indent=1, sort_keys=True))
