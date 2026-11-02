# Security

## Reporting a vulnerability

Report it privately through GitHub: [open a private vulnerability report](https://github.com/ygtdalkilic/Project-TrueAcre/security/advisories/new) (the repository's Security tab, "Report a vulnerability"). Only the maintainer sees it. Please do not open a public issue. You will get an acknowledgement within a few days. Give reasonable time for a fix before disclosing publicly.

## Supported versions

Only the current `main` branch and the service deployed from it receive security fixes. There are no versioned releases to backport to.

## What is in place

- Sign-in only through Google; ID tokens verified server-side. No passwords are stored anywhere.
- Sessions are signed, HttpOnly, SameSite cookies. "Sign out everywhere" invalidates all of them.
- Every request is scoped to the signed-in user's company; a test proves companies cannot see each other's data.
- Grower accounts see only their own grower record. Every company route refuses them by default, and a test walks every route the app serves to prove it.
- Uploaded company data is encrypted at rest with AES-256-GCM using a key held in Secret Manager, separate from the database. Transport is TLS everywhere, including to the database.
- Content Security Policy, HSTS, frame denial, same-origin enforcement on state-changing requests, rate limits, and upload size limits.
- The container runs as a non-root user, holds no secrets, and disables development sign-in and API docs in production.
- An audit log records uploads, link rulings, invites, membership changes, evidence views, and grower statements. Admins can read it, and it is kept after deletions.
- Every push, every pull request, and a weekly schedule run `pip-audit` and `npm audit` against pinned dependencies, and a known vulnerability fails the build.
- GitHub Dependabot alerts are on, and Dependabot opens a pull request with the patched version as soon as an advisory affects a dependency. It also opens routine version-update pull requests.
- GitHub CodeQL code scanning analyzes the project's own Python, JavaScript, and workflow files for security bugs on every push and pull request to `main`.
- GitHub secret scanning is on with push protection, so a commit containing a recognizable key or token is refused before it reaches the repository.
- `main` is protected by a repository ruleset: no force pushes, no deletion, and changes only through pull requests that pass every CI check, including the dependency audit.

## What is not in place

- No system is immune to unknown ("zero-day") vulnerabilities. The measures above shorten the time between a vulnerability becoming public and it being patched here; they cannot prevent one from existing.
- Rate limiting is per server instance, not global.
- No web application firewall.
- Database backups are whatever the database provider keeps.
- Seed statements growers file themselves are stored as plain rows (grower ID, season, crop, acres), not encrypted like uploaded tables. They name no person; the grower ID maps to a name only through the encrypted growers table.

## If a secret leaks

1. Rotate it at the source: Neon for the database password, Google AI Studio for the Gemini key, or generate a new value for `SESSION_SECRET` and `DATA_ENCRYPTION_KEY`.
2. Add a new version in Secret Manager: `printf '%s' "<value>" | gcloud secrets versions add <name> --data-file=-`.
3. Redeploy so the new version is picked up: `gcloud run deploy trueacre --source . --region us-east1`.
4. Rotating `SESSION_SECRET` signs every user out. Rotating `DATA_ENCRYPTION_KEY` makes existing uploads unreadable; companies must re-upload. Rotate that one only if it has actually leaked.
