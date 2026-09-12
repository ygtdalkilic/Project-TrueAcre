# Project-TrueAcre
Protecting Seed Licensing Through Fair-Play Agronomic Analytics

[![CI](https://github.com/ygtdalkilic/Project-TrueAcre/actions/workflows/ci.yml/badge.svg)](https://github.com/ygtdalkilic/Project-TrueAcre/actions/workflows/ci.yml)
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

# Accounts and companies

TrueAcre is multi-tenant. Anyone can sign in with Google and create a company; they become its first admin. Admins invite colleagues by email as `admin` or `analyst`, and the invite turns into a membership the moment that person signs in. A company's data and scores are visible only to its members, and every API request is scoped to the company chosen in the session.

Each company uploads seven CSV tables from the Data page: growers, dealers, varieties, seed purchases, acreage reports, elevator receipts, and county yields. Templates with the exact columns are downloadable there, uploads are validated with row-level error messages, and a one-click sample dataset exists for trying the product.

# Running locally

Everything runs on your machine with free tools. Requires Python 3.12+ and Node 20+.

```
python -m venv .venv
.venv\Scripts\activate          # Windows; on macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
pytest                           # engine, generator, resolver, auth, and API tests

copy .env.example .env           # then edit; at minimum keep TRUEACRE_DEV_LOGIN=1 for local use
uvicorn api.main:app --reload --env-file .env    # API on http://localhost:8000
```

In a second terminal:

```
cd web
npm install
npm run dev                      # dashboard on http://localhost:5173, proxying /api to port 8000
```

Without a Google client ID the sign-in page offers a development sign-in by email, which only exists outside production. The database defaults to a local SQLite file.

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

# Plain-English explanations (optional)

The button asks a chat model to restate the evidence for one grower and list the innocent explanations an analyst must rule out. It never changes the score. The client speaks the OpenAI-compatible chat completions API over plain HTTP, so any provider that exposes it works, cloud or local, with no vendor SDK.

- **Cloud, free tier:** the Gemini block in `.env.example`.
- **Fully local, nothing leaves your machine:** install [Ollama](https://ollama.com), run `ollama pull <model>`, then set `TRUEACRE_LLM_PROVIDER=ollama` and `TRUEACRE_LLM_MODEL=<model>`. LM Studio works the same way with `lmstudio`.
- **Anything else** that speaks the same API (llama.cpp, vLLM, OpenRouter): `custom` plus `TRUEACRE_LLM_BASE_URL`.

Keys live in a gitignored `.env`; start the API with `--env-file .env`.

# Security

What is in place, and what it does not cover.

- **Sign-in.** Google ID tokens are verified server-side against Google's public keys, including audience, issuer, and expiry. Sessions are signed, HttpOnly, SameSite=Lax cookies that expire after seven days. "Sign out everywhere" invalidates every session at once.
- **Authorization.** Every data endpoint is scoped to the company in the session. Admin-only actions check the role. A test proves one company cannot read another's data.
- **Cross-site requests.** State-changing API calls must come from the same origin (Origin and Sec-Fetch-Site are checked) on top of the cookie's SameSite protection.
- **Headers.** A Content Security Policy allows only the app's own files plus Google's sign-in button, and frames are refused. HSTS is on in production.
- **Input.** Uploads are capped at 20 MB and 500,000 rows, must be UTF-8 CSV, and are validated column by column with typed errors. All database access is parameterized through SQLAlchemy.
- **Encryption at rest.** Every uploaded table is encrypted with AES-256-GCM before it is stored, using a key held in Secret Manager and never in the database. A leaked database alone reveals no grower data, and tampering is detected on read.
- **Privacy rights.** Members can remove any table, admins can delete a company with everything it owns, and any user can delete their account. See the Privacy Policy and Terms of Use served at `/privacy.html` and `/terms.html`.
- **Abuse.** Sign-in attempts, uploads, and paid explanation calls are rate limited per server instance.
- **Secrets.** Never in the repo or the image. Locally in `.env`; on Cloud Run in Secret Manager.
- **Dependencies.** `pip-audit` and `npm audit` run on every push and weekly; Dependabot opens update pull requests. See [SECURITY.md](SECURITY.md) for reporting and incident steps.

Not covered: distributed rate limiting across instances, a web application firewall, audit logging of user actions, and backups beyond what Neon provides. No system is immune to unknown vulnerabilities; the measures above shorten the window, they do not close it. Report anything you find.

# Deploying to Google Cloud Run

The container builds the dashboard and serves it with the API from one process. Cloud Run terminates TLS.

```
gcloud run deploy trueacre --source . --region us-east5 --allow-unauthenticated \
  --set-secrets DATABASE_URL=database-url:latest,SESSION_SECRET=session-secret:latest,DATA_ENCRYPTION_KEY=data-encryption-key:latest,GEMINI_API_KEY=gemini-api-key:latest \
  --set-env-vars TRUEACRE_ENV=production,GOOGLE_CLIENT_ID=<client id>,TRUEACRE_LLM_PROVIDER=gemini,TRUEACRE_LLM_MODEL=gemini-3.8-flash
```

Create the four secrets in Secret Manager first (`python -m api.crypto` prints a fresh encryption key). After the first deploy, add the service URL to the OAuth client's authorized JavaScript origins and set `TRUEACRE_ALLOWED_HOSTS` to the service hostname.

# License

Source-available, all rights reserved. The code may be viewed but not copied, modified, redistributed, or used to run a service without written permission. See [LICENSE](LICENSE).

# Layout

```
data/     row schemas and the synthetic generator
engine/   resolve, reconcile, score: pure functions over pandas tables; optional explain
api/      FastAPI: auth and sessions, companies and invites, CSV intake, per-company pipeline, scores
web/      React + Vite dashboard
tests/    pytest suite, run against synthetic ground truth and a throwaway SQLite database
```
