# Authorship and AI disclosure

**TrueAcre is the work of Yigit Dalkilic, its author and owner.** It was built with AI-assisted development, and this page describes how.

## Yigit Dalkilic

- **The concept.** Detecting unlicensed replanting of patented seed by reconciling three records that already exist (dealer seed receipts, government acreage reports, grain elevator receipts) into a per-grower Fair-Play Score, as a fairer alternative to tip lines and field audits.
- **The design principles** every part of the system follows:
  - scoring is deterministic and explainable, never a black-box model, and every flag shows its evidence;
  - uncertainty is a first-class output: thin data reads as "insufficient data", never as an accusation;
  - false positives are the failure to avoid, and zero false positives is a hard requirement;
  - synthetic data with known ground truth comes first, because real grower data is private;
  - a wrong record match is worse than a missed one;
  - AI stays off the scoring path and may only explain.
- **The production system.** Yigit set up and runs TrueAcre's server-side infrastructure on Google Cloud: Cloud Run hosting, the Neon Postgres database, Secret Manager for every key, Google sign-in, and the Google Gemini configuration behind the optional explanations.
- **The decisions.** What to build and in what order, which suggestions to accept or reject, the product and security posture, the stack, the deployment, the licensing, and when work is ready to ship. No change enters the project without his approval.

## AI assistance

Development used Anthropic's Claude, through Claude Code, as a coding assistant working under Yigit's direction: writing and revising code, tests, and documentation; researching technical facts the engine depends on (for example that FSA farm numbers are unique only within a county, and the Census Bureau's county adjacency data); and reproducing bugs in synthetic data before fixing them. Its suggestions were accepted or rejected by Yigit.

## AI inside the product

The product's scores are computed by fixed, published rules ([engine/score.py](engine/score.py)); no AI model decides or changes a score. The one optional AI feature, "Explain in plain English", restates the evidence for an analyst and is off unless an operator configures it (see [README.md](README.md)).

## Why this page exists

To be open about how TrueAcre was made, and to keep a dated, public record, alongside the repository's history, of whose idea and direction it is.
