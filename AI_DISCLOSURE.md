# Authorship and AI disclosure

**TrueAcre is the work of Yigit Dalkilic, its sole author and owner.** The idea, the problem it sets out to solve, and the decisions that shape it are his. Much of the implementation was written with an AI coding assistant, and this page says plainly who did what.

## Yigit Dalkilic: the idea and the direction

- **The concept.** Detecting unlicensed replanting of patented seed by reconciling three records that already exist (dealer seed receipts, government acreage reports, grain elevator receipts) into a per-grower Fair-Play Score, as a fairer alternative to tip lines and field audits.
- **The design principles** every part of the system follows:
  - scoring is deterministic and explainable, never a black-box model, and every flag shows its evidence;
  - uncertainty is a first-class output: thin data reads as "insufficient data", never as an accusation;
  - false positives are the failure to avoid, and zero false positives is a hard requirement;
  - synthetic data with known ground truth comes first, because real grower data is private;
  - a wrong record match is worse than a missed one;
  - AI stays off the scoring path and may only explain.
- **The decisions.** What to build and in what order, which proposals to accept or reject, the product and security posture, the stack, the deployment, the licensing, and when work is ready to ship. No change enters the project without his explicit approval.

## AI assistance: the implementation, under that direction

Most of the code, tests, and documentation were written by Anthropic's Claude, used through Claude Code, working under Yigit's direction and approval. That includes implementing the engine, API, dashboard, and test suite; researching facts the engine depends on (for example that FSA farm numbers are unique only within a county, and the Census Bureau's county adjacency data); finding bugs by reproducing them in synthetic data before fixing them; and drafting documentation.

Claude also proposed fixes and features, such as the seed-statement approach to other brands' seed, dealer coverage across county lines, "what would clear this", the replant signature, the validation report, and the grower self-check page. Yigit decided which of them to build and how.

## AI inside the product

The product's scores are computed by fixed, published rules ([engine/score.py](engine/score.py)); no AI model decides or changes a score. The one optional AI feature, "Explain in plain English", restates the evidence for an analyst and is off unless an operator configures it (see [README.md](README.md)).

## Why this page exists

To be open about how TrueAcre was made, and to keep a dated, public record, alongside the repository's history, of whose idea and direction it is.
