"""Optional plain-English explanation of one grower-season, written by Claude.

Off the scoring path by design: the score and label are computed before this runs and are
never changed by it. The model only restates the evidence and lists what an analyst should
rule out before acting on it.

Enabled only when ANTHROPIC_API_KEY is set (see api/main.py). Each call sends roughly 1.5K
input tokens and returns at most MAX_TOKENS output tokens; at claude-opus-5 rates that is
about $0.02 per explanation. Override the model with TRUEACRE_EXPLAIN_MODEL.
"""
import json
import os

import anthropic

MODEL = os.environ.get("TRUEACRE_EXPLAIN_MODEL", "claude-opus-5")
MAX_TOKENS = 1024  # explanations are short by design
EFFORT = "low"  # restating given numbers needs no deep reasoning

SYSTEM = """You write for a compliance analyst at a seed company. You receive JSON evidence about one
grower and one season: seed purchases, the acreage report, elevator receipts, the county yield
reference, and a computed Fair-Play Score with a label.

Write plain text, under 200 words, no headings or markdown:
1. Two or three sentences saying what the numbers show, in everyday language.
2. A short list of innocent explanations the analyst must rule out before contacting the grower
   (for example seed bought from a dealer outside the system, carryover seed from last year,
   custom-farmed land, grain delivered on behalf of a landlord or neighbor, a records error).
3. One sentence naming the single record that would settle it.

The label is not a verdict. Never say or imply the grower did something wrong. Do not repeat every
number; cite only the two or three that matter."""


class ExplainError(RuntimeError):
    """The model did not return usable text."""


def explain(evidence: dict, client: anthropic.Anthropic) -> str:
    """Return a plain-English explanation of an evidence bundle from the API's grower endpoint."""
    response = client.messages.create(
        model=MODEL,
        max_tokens=MAX_TOKENS,
        system=SYSTEM,
        output_config={"effort": EFFORT},
        messages=[{"role": "user", "content": json.dumps(evidence, indent=1, sort_keys=True)}],
    )
    if response.stop_reason == "refusal":
        raise ExplainError("the model declined to write an explanation")
    text = "".join(block.text for block in response.content if block.type == "text").strip()
    if not text:
        raise ExplainError("the model returned no text")
    return text
