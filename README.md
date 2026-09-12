# Project-TrueAcre
Protecting Seed Licensing Through Fair-Play Agronomic Analytics
# Description:
Seed companies spend millions developing drought-resistant, high-yield genetics, and farmers sign a Grower Technology Agreement promising to plant those seeds only once. But enforcing that license often relies on neighbor-against-neighbor tip lines, private investigators, or random, stressful field audits. It creates an environment of suspicion rather than partnership.

Project TrueAcre replaces the "gotcha" audit culture with quiet, undeniable math. It operates on a simple truth: you cannot harvest and sell crops that you never legally purchased the seed for.

Instead of treating every farmer like a suspect, the system acts as a digital ledger for the honor system. It pulls together three standard pieces of paperwork—the dealer receipts showing what the farmer bought, the government acreage reports showing what they planted, and the grain elevator receipts showing what they harvested. The AI engine searches this data for "ghost seeds"—instances where a farmer brings a massive harvest to the elevator, but has no purchase history of the patented seed required to grow it.

By calculating a Fair-Play Score based on these basic supply-and-demand metrics, TrueAcre allows seed companies to instantly spot unlicensed seed replication. It protects the intellectual property that funds the future of agriculture, ensures license compliance with surgical precision, and keeps honest, rule-following farmers completely out of the audit crosshairs.

# How it works

For every grower and season the engine runs three deterministic steps. No model, no black box: every number on the dashboard can be recomputed by hand from the evidence shown next to it.

1. **Resolve.** Acreage reports and elevator receipts do not share an ID with the seed company's customer list. Each record is linked to a grower by farm number, then by normalized name and county, then by close name similarity. A link is accepted only when exactly one grower qualifies. Anything ambiguous is refused and listed separately, because a wrong match is worse than a missed one.
2. **Reconcile.** Seed units purchased × seeds per unit ÷ seeds per acre gives the acres the licensed seed could plant. That is compared with declared acres, and with delivered bushels against a generous yield ceiling (county mean + 3 standard deviations).
3. **Score.** The Fair-Play Score is 100 minus the share of declared acres or delivered bushels that no licensed seed can explain. A label then says whether the data supports a conclusion: `consistent`, `insufficient data` (a gap exists but dealer coverage in that county is too thin to rule out an unseen purchase), or `review recommended`.

Real grower-level data is private, so the project ships a synthetic generator with seeded ghost-seed cases and innocent look-alikes as ground truth. The test suite requires zero false positives against it.

# Running locally

Everything runs on your machine with free tools. Requires Python 3.12+ and Node 20+.

```
python -m venv .venv
.venv\Scripts\activate          # Windows; on macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
pytest                           # engine, generator, resolver, and API tests

uvicorn api.main:app --reload    # API on http://localhost:8000
                                 # add --env-file .env to load secrets such as GEMINI_API_KEY
```

In a second terminal:

```
cd web
npm install
npm run dev                      # dashboard on http://localhost:5173
```

Optional settings, all with working defaults:

| Variable | Purpose |
|---|---|
| `TRUEACRE_DATA_DIR` | Load CSVs from a directory (write one with `python -m data.generate`) instead of generating in memory |
| `TRUEACRE_SEED` | RNG seed for the in-memory synthetic dataset |
| `TRUEACRE_CORS_ORIGINS` | Comma-separated browser origins allowed to call the API |
| `VITE_API_URL` | API base URL for the dashboard (put it in `web/.env`, see `web/.env.example`) |
| `GEMINI_API_KEY` | Enables the optional "Explain in plain English" button, which asks Gemini to restate the evidence and list innocent explanations to rule out. Free on the Gemini API free tier; unset means the button is hidden and nothing is ever sent. Put it in a gitignored `.env` (see `.env.example`) and start the API with `--env-file .env` |
| `TRUEACRE_EXPLAIN_MODEL` | Gemini model for explanations (default `gemini-3.8-flash`) |

# Layout

```
data/     row schemas and the synthetic generator
engine/   resolve, reconcile, score: pure functions over pandas tables
api/      FastAPI endpoints for scores, per-grower evidence, and unmatched records
web/      React + Vite dashboard
tests/    pytest suite, run against synthetic ground truth
```
