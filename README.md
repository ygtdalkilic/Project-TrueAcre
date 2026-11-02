# Project-TrueAcre
Protecting Seed Licensing Through Fair-Play Agronomic Analytics

[![CI](https://github.com/ygtdalkilic/Project-TrueAcre/actions/workflows/ci.yml/badge.svg)](https://github.com/ygtdalkilic/Project-TrueAcre/actions/workflows/ci.yml)
# Description:
Seed companies spend millions developing drought-resistant, high-yield genetics, and farmers sign a Grower Technology Agreement promising to plant those seeds only once. But enforcing that license often relies on neighbor-against-neighbor tip lines, private investigators, or random, stressful field audits. It creates an environment of suspicion rather than partnership.

Project TrueAcre replaces the "gotcha" audit culture with quiet, checkable math. It starts from a simple idea: acres planted with licensed seed should trace back to a purchase of that seed.

Instead of treating every farmer like a suspect, the system acts as a digital ledger for the honor system. It pulls together three standard pieces of paperwork—the dealer receipts showing what the farmer bought, the government acreage reports showing what they planted, and the grain elevator receipts showing what they harvested. The engine searches this data for "ghost seed": cases where a grower declares more acres, or delivers more grain, than their licensed seed purchases can explain.

By calculating a Fair-Play Score based on these basic supply-and-demand metrics, TrueAcre shows seed companies which grower-seasons deserve a closer look, with the evidence behind each one. When the data is too thin to support a conclusion, it says so instead of flagging the grower. The goal is fewer, better-aimed audits that leave honest growers alone.

# How it works

For every grower and season the engine runs three deterministic steps. No model, no black box: every number on the dashboard can be recomputed by hand from the evidence shown next to it.

1. **Resolve.** Acreage reports and elevator receipts do not share an ID with the seed company's customer list. Each record is linked to a grower by FSA farm number within the same county and state (FSA numbers farms per county office, so the same number recurs elsewhere), then by normalized name within that county and state, then by close name similarity within it. A link is accepted only when exactly one grower qualifies. Anything ambiguous is refused and listed separately, because a wrong match is worse than a missed one.
2. **Reconcile.** Seed units purchased × seeds per unit ÷ seeds per acre gives the acres the licensed seed could plant. Acres the grower states were planted with other seed (another company's or conventional) are added to that. The total is compared with declared acres, and with delivered bushels against a generous yield ceiling (county mean + 3 standard deviations).
3. **Score.** The Fair-Play Score is 100 minus the share of declared acres or delivered bushels that neither licensed seed nor the grower's stated other seed can explain. A label then says whether the data supports a conclusion: `consistent`, `insufficient data` (a gap exists, but dealer coverage in the grower's county and the counties bordering it is too thin to rule out an unseen purchase, or the grower has no seed statement on file), or `review recommended`.

Two more things sit next to every score. Neither changes it.

- **What would clear this.** The exact number of acres, and seed units of the grower's main variety, that one more record would need to show for the season to be consistent, plus any missing record that stops a conclusion (a seed statement, or receipts from named non-reporting dealers nearby). It tells an analyst what to ask for, which is usually one receipt, not an audit.
- **Replant signature.** Saved seed rarely starts from nothing: a grower buys licensed seed once, then buys for less of a similar acreage. When purchases explained the declared acres in an earlier season and explain far less of a similar acreage now, the evidence page says so, with both seasons side by side.

Real grower-level data is private, so the project ships a synthetic generator with seeded ghost-seed cases and innocent look-alikes as ground truth: growers who split brands, buy from a dealer that does not report, or buy across a county line, and elevator tickets from people who are not customers at all. The test suite requires zero false positives against it. [docs/VALIDATION.md](docs/VALIDATION.md) reports the current results across 20 synthetic datasets; regenerate it with `python -m engine.validate`.

# Limitations

- **The data names the crop, not the brand.** Acreage reports and elevator receipts say "soybeans", not whose soybeans. Another company's seed, conventional seed, and saved seed look the same in them; only the grower's seed statement tells them apart. Without a statement, a gap is reported as `insufficient data`, never `review recommended`. A false statement is not detected here; that is for the review it leads to.
- **Dealer coverage reaches one county over.** It counts the dealers in the grower's county and in every county bordering it, using the Census Bureau's county adjacency file. A purchase from a non-reporting dealer two counties away is still invisible. A county name the Census list does not recognize falls back to every dealer in the state, which can only lower coverage.
- **Validated on synthetic data only.** The zero-false-positive result holds against the generator's ground truth. No real grower data has been tested yet.
- **Data access is the customer's responsibility.** TrueAcre does not collect data. It assumes the company already holds the dealer receipts, acreage reports, and elevator receipts lawfully, for example through grower consent in the license agreement. Confirm this with counsel before a pilot.

# Accounts and companies

TrueAcre is multi-tenant. Anyone can sign in with Google and create a company; they become its first admin. Admins invite colleagues by email as `admin` or `analyst`, and the invite turns into a membership the moment that person signs in. A company's data and scores are visible only to its members, and every API request is scoped to the company chosen in the session.

**Grower self-check.** An admin can also invite a grower, tied to that grower's record. A grower sees only their own seasons, the same arithmetic and evidence the company sees, and what would clear any gap, and can file their seed statement themselves. They do not see other growers, dealer coverage, or which dealers do not report. A filed statement replaces any uploaded one for that season and survives later uploads. The point is that an honest grower can check their own numbers and close a gap with one entry, before anyone talks about an audit.

Each company uploads seven required CSV tables from the Data page: growers, dealers, varieties, seed purchases, acreage reports, elevator receipts, and county yields. An eighth, seed statements, is optional: each grower's own count of acres planted with seed not bought from the company. Without it the dashboard still scores every grower, but no gap is marked `review recommended`. Templates with the exact columns are downloadable there, uploads are validated with row-level error messages, and a one-click sample dataset exists for trying the product. County yields can also be filled from USDA county statistics with one click when the server has a free NASS API key.

Every crop that appears in the varieties table is scored separately, so a company licensing soybeans and wheat sees a row per grower, season, and crop.

**Links page.** The resolver links an external record to a grower only when exactly one grower fits. Records it refused, and records it linked only by fuzzy name similarity, wait on the Links page with ranked candidate growers. An analyst links a record, confirms a fuzzy link, or rules that it matches nobody. Rulings override the resolver and can be undone.

**Activity.** Every upload, ruling, invite, membership change, evidence view, and grower statement is written to an audit log that admins can read on the Members page. The log outlives the users and companies it describes.

# Running locally

Everything runs on your machine with free tools. Requires Python 3.12+ and Node 20+.

```
python -m venv .venv
.venv\Scripts\activate          # Windows; on macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
pytest                           # engine, generator, resolver, auth, and API tests
python -m engine.validate        # rewrites docs/VALIDATION.md from 20 synthetic datasets

copy .env.example .env           # then edit; at minimum keep TRUEACRE_DEV_LOGIN=1 for local use
uvicorn api.main:app --reload --env-file .env    # API on http://localhost:8000
```

In a second terminal:

```
cd web
npm install
npm run dev                      # dashboard on http://localhost:5173, proxying /api to port 8000
```

Without a Google client ID the sign-in page offers a development sign-in by email, which only exists outside production. The database defaults to a local SQLite file, and the schema is applied by Alembic migrations at startup. After changing `api/models.py`, generate a migration with `alembic revision --autogenerate -m "what changed"`; a test fails if a model change has no migration.

Settings, all read from the environment (put them in `.env`):

| Variable | Purpose |
|---|---|
| `DATABASE_URL` | SQLAlchemy URL. Default `sqlite:///trueacre.db`; use `postgresql+psycopg://...` in the cloud |
| `GOOGLE_CLIENT_ID` | OAuth web client ID from the Google Cloud console. Unset means Google sign-in is off |
| `SESSION_SECRET` | Signs session cookies. Required in production; random per process otherwise |
| `TRUEACRE_ENV` | `production` turns on HSTS and Secure cookies and disables dev login and API docs |
| `TRUEACRE_DEV_LOGIN` | `1` enables email-only sign-in outside production |
| `TRUEACRE_ALLOWED_HOSTS` | Comma-separated Host values the server answers to (default any) |
| `TRUEACRE_LLM_PROVIDER` | Enables the optional "Explain in plain English" button. One of `gemini`, `openai`, `anthropic`, `ollama`, `lmstudio`, `custom`. Unset means the button is hidden and nothing is ever sent |
| `TRUEACRE_LLM_MODEL` | Model name as that provider expects it. Required when a provider is set |
| `TRUEACRE_LLM_BASE_URL` | Overrides the provider's endpoint. Required for `custom`; handy for an Ollama on another machine |
| `TRUEACRE_LLM_API_KEY` | Overrides the provider's own key variable (`GEMINI_API_KEY`, `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`). Local servers need none |
| `NASS_API_KEY` | Free key from quickstats.nass.usda.gov/api. Enables "fill from USDA" for county yields. Unset means the button is hidden |
| `DATA_ENCRYPTION_KEY` | 32 random bytes, urlsafe-base64 (`python -m api.crypto` prints one). Encrypts uploaded tables at rest; required in production |

# Plain-English explanations (optional)

The button asks a chat model to restate the evidence for one grower and list the innocent explanations an analyst must rule out. It never changes the score. The client speaks the OpenAI-compatible chat completions API over plain HTTP, so any provider that exposes it works, cloud or local, with no vendor SDK.

- **Cloud, free tier:** the Gemini block in `.env.example`.
- **Fully local, nothing leaves your machine:** install [Ollama](https://ollama.com), run `ollama pull <model>`, then set `TRUEACRE_LLM_PROVIDER=ollama` and `TRUEACRE_LLM_MODEL=<model>`. LM Studio works the same way with `lmstudio`.
- **Anything else** that speaks the same API (llama.cpp, vLLM, OpenRouter): `custom` plus `TRUEACRE_LLM_BASE_URL`.

Keys live in a gitignored `.env`; start the API with `--env-file .env`.

# Security

What is in place, and what it does not cover.

- **Sign-in.** Google ID tokens are verified server-side against Google's public keys, including audience, issuer, and expiry. Sessions are signed, HttpOnly, SameSite=Lax cookies that expire after seven days. "Sign out everywhere" invalidates every session at once.
- **Authorization.** Every data endpoint is scoped to the company in the session. Admin-only actions check the role. A test proves one company cannot read another's data. Grower accounts are refused by every company route by default, and a test walks every route the app serves to prove it.
- **Cross-site requests.** State-changing API calls must come from the same origin (Origin and Sec-Fetch-Site are checked) on top of the cookie's SameSite protection.
- **Headers.** A Content Security Policy allows only the app's own files plus Google's sign-in button, and frames are refused. HSTS is on in production.
- **Input.** Uploads are capped at 20 MB and 500,000 rows, must be UTF-8 CSV, and are validated column by column with typed errors. All database access is parameterized through SQLAlchemy.
- **Encryption at rest.** Every uploaded table is encrypted with AES-256-GCM before it is stored, using a key held in Secret Manager and never in the database. A leaked database alone reveals no grower data, and tampering is detected on read.
- **Privacy rights.** Members can remove any table, admins can delete a company with everything it owns, and any user can delete their account. See the Privacy Policy and Terms of Use served at `/privacy.html` and `/terms.html`.
- **Audit log.** Who uploaded, ruled, invited, removed, viewed evidence, or filed a seed statement, when, and from where; readable by admins, kept after deletions.
- **Abuse.** Sign-in attempts, uploads, USDA imports, and paid explanation calls are rate limited per server instance.
- **Secrets.** Never in the repo or the image. Locally in `.env`; on Cloud Run in Secret Manager.
- **Dependencies.** `pip-audit` and `npm audit` run on every push, pull request, and week, and a known vulnerability fails the build. Dependabot alerts and automatic security-fix pull requests are on.
- **Code scanning.** GitHub CodeQL analyzes the project's own code for security bugs on every push and pull request.
- **Leaked keys.** GitHub secret scanning with push protection refuses commits that contain a recognizable key or token.
- **Changes.** `main` is protected: no force pushes or deletion, and every change arrives through a pull request that passes the tests, the dependency audit, the dashboard build, and the container build.

Not covered: distributed rate limiting across instances, a web application firewall, and backups beyond what Neon provides. No system is immune to unknown vulnerabilities; the measures above shorten the window, they do not close it. Report anything you find privately, as [SECURITY.md](SECURITY.md) describes.

# Deploying to Google Cloud Run

The container builds the dashboard and serves it with the API from one process. Cloud Run terminates TLS.

```
gcloud run deploy trueacre --source . --region us-east1 --allow-unauthenticated \
  --set-secrets DATABASE_URL=database-url:latest,SESSION_SECRET=session-secret:latest,DATA_ENCRYPTION_KEY=data-encryption-key:latest,GEMINI_API_KEY=gemini-api-key:latest \
  --set-env-vars TRUEACRE_ENV=production,GOOGLE_CLIENT_ID=<client id>,TRUEACRE_LLM_PROVIDER=gemini,TRUEACRE_LLM_MODEL=gemini-3.8-flash
```

Create the four secrets in Secret Manager first (`python -m api.crypto` prints a fresh encryption key). After the first deploy, add the service URL to the OAuth client's authorized JavaScript origins and set `TRUEACRE_ALLOWED_HOSTS` to the service hostname.

# Authorship and AI disclosure

TrueAcre was conceived, directed, and deployed by Yigit Dalkilic, its author and owner, with AI-assisted development (Anthropic's Claude, through Claude Code). [AI_DISCLOSURE.md](AI_DISCLOSURE.md) describes how.

# License

Source-available, all rights reserved. The code may be viewed but not copied, modified, redistributed, or used to run a service without written permission. See [LICENSE](LICENSE).

# Layout

```
data/     row schemas, the synthetic generator, Census county adjacency (geography.py)
engine/   resolve, reconcile, score, clear, replant: pure functions over pandas tables; optional explain;
          validate writes docs/VALIDATION.md
api/      FastAPI: auth and sessions, companies and invites, CSV intake, USDA import, link review, audit log,
          per-company pipeline, scores, the grower's own view (grower.py)
docs/     VALIDATION.md, generated
migrations/  Alembic migrations, applied at startup
web/      React + Vite dashboard
tests/    pytest suite, run against synthetic ground truth and a throwaway SQLite database
```
