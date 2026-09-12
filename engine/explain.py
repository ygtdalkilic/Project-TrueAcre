"""Optional plain-English explanation of one grower-season, written by Gemini.

Off the scoring path by design: the score and label are computed before this runs and are
never changed by it. The model only restates the evidence and lists what an analyst should
rule out before acting on it.

Enabled only when GEMINI_API_KEY is set (see api/main.py). Each call sends roughly 1.5K input
tokens and returns at most MAX_TOKENS output tokens. On the Gemini API free tier that costs
nothing; on a paid project it is a fraction of a cent with the default Flash model.
Override the model with TRUEACRE_EXPLAIN_MODEL.
"""
import json
import os

from google import genai
from google.genai import types

MODEL = os.environ.get("TRUEACRE_EXPLAIN_MODEL", "gemini-3.8-flash")
MAX_TOKENS = 1024  # explanations are short by design
TEMPERATURE = 0.2  # restating given numbers should be steady, not creative

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


def explain(evidence: dict, client: genai.Client) -> str:
    """Return a plain-English explanation of an evidence bundle from the API's grower endpoint."""
    response = client.models.generate_content(
        model=MODEL,
        contents=json.dumps(evidence, indent=1, sort_keys=True),
        config=types.GenerateContentConfig(
            system_instruction=SYSTEM, max_output_tokens=MAX_TOKENS, temperature=TEMPERATURE
        ),
    )
    text = (response.text or "").strip()
    if not text:
        raise ExplainError(f"the model returned no text (finish reason: {_finish_reason(response)})")
    return text


def _finish_reason(response) -> str | None:
    if response.candidates:
        return str(response.candidates[0].finish_reason)
    if response.prompt_feedback:
        return str(response.prompt_feedback.block_reason)
    return None
