# Security

## Reporting a vulnerability

Email the maintainer at ygtdalkilic@gmail.com with the subject "TrueAcre security". Please do not open a public issue. You will get an acknowledgement within a few days. Give reasonable time for a fix before disclosing publicly.

## What is in place

- Sign-in only through Google; ID tokens verified server-side. No passwords are stored anywhere.
- Sessions are signed, HttpOnly, SameSite cookies. "Sign out everywhere" invalidates all of them.
- Every request is scoped to the signed-in user's company; a test proves companies cannot see each other's data.
- Uploaded company data is encrypted at rest with AES-256-GCM using a key held in Secret Manager, separate from the database. Transport is TLS everywhere, including to the database.
- Content Security Policy, HSTS, frame denial, same-origin enforcement on state-changing requests, rate limits, and upload size limits.
- The container runs as a non-root user, holds no secrets, and disables development sign-in and API docs in production.
- Every push and a weekly schedule run `pip-audit` and `npm audit` against pinned dependencies; Dependabot opens update pull requests.

## What is not in place

- No system is immune to unknown ("zero-day") vulnerabilities. The measures above shorten the time between a vulnerability becoming public and it being patched here; they cannot prevent one from existing.
- Rate limiting is per server instance, not global.
- No web application firewall and no audit log of user actions yet.
- Database backups are whatever the database provider keeps.

## If a secret leaks

1. Rotate it at the source: Neon for the database password, Google AI Studio for the Gemini key, or generate a new value for `SESSION_SECRET` and `DATA_ENCRYPTION_KEY`.
2. Add a new version in Secret Manager: `printf '%s' "<value>" | gcloud secrets versions add <name> --data-file=-`.
3. Redeploy so the new version is picked up: `gcloud run deploy trueacre --source . --region us-east5`.
4. Rotating `SESSION_SECRET` signs every user out. Rotating `DATA_ENCRYPTION_KEY` makes existing uploads unreadable; companies must re-upload. Rotate that one only if it has actually leaked.
