# Teammate handoff: Supabase and Penny production hardening

Final integration update: use the tested release from **main** after promotion,
and read [FINAL_MAIN_VALIDATION.md](FINAL_MAIN_VALIDATION.md). The public HTTPS
deployment address is now
`https://mainstreet-penny-aurin.belgiumcentral.cloudapp.azure.com`.
This supersedes historical statements below that no deployment address exists.
Password sign-in is independently tested; production confirmation/reset redirect
configuration and a fresh hosted real-account A/B check remain separate acceptance
items. Never change project auth settings merely to make a test pass.

Updated 2026-11-08. Start from the latest **aurin-test** commit, which contains
this document and `backend/scripts/check_two_accounts.py`. Put `git rev-parse HEAD`
in anything you report back. Make your own branch for changes, e.g. `auth-production`.

## Live two-account release evidence

**2026-11-08 giri-test update:** The owner supplied two existing QA accounts through ignored local configuration and replaced the initially unconfirmed second account. The real two-account checker completed against integrated application commit `6c3ff31`, with `complete: true` and **26/26 checks passed**. Real Supabase and Redis were used; Hermes/model calls were faked, with zero paid model spend. See `AURIN_SUPABASE_INTEGRATION.md` for scope and limits. This supersedes the historical missing-account blocker below. The subsequent email sign-in test was accepted by Supabase and the owner confirmed receipt and successful local sign-in. Production redirects and staging deployment still require separate evidence; the fallback Site URL remains localhost:3000. A subsequent fresh signup through the real app UI was confirmed by email and independently verified server-side with successful password login and app account identity. See the integration report for the exact scope. Only the production HTTPS redirect and deployment remain outstanding in this auth check set.

2026-11-08 update on `giri-test`: account-owned favourites and a 30-day chat
retention policy now supersede the original short cache policy. See
`FAVOURITES_AND_RETENTION.md`. The new two-account browser journey uses a
synthetic identity-provider seam with real API/SQLite/Redis, so it does not
resolve the live second-account Supabase check below.

Later SMTP session update: custom **Mailjet SMTP** was configured in the Creed
Supabase project. The owner confirmed receiving the confirmation email in spam
and then successfully signing in. This supersedes the earlier pre-SMTP setup
notes for the development project; production sender/domain/redirect checks
and a second real-mailbox signup remain unverified. The old HTTP429 result is
historical, not a fresh statement about the current quota. Two mock-email
browser identities pass isolation checks but do not exercise SMTP delivery.

Own production authentication/signup/cache/plan-access hardening and its release
evidence. Claude continues agent/discovery work under CLAUDE_WXX_RESUME.md. This is
a tested integration baseline, not a claim that public production is ready.

Aurin's incoming handoff reports that isolation checks with **two real Supabase accounts** were still outstanding. Account A
is real and has passed everything. Account B has only ever been a mock, because the
second test user was never created (sign-in returns `invalid_credentials`; an
earlier signup attempt hit HTTP 429). You own the Supabase project, so you can
close this with one zero-cost run. Steps are in "Run the two-account check" below.

## Historical baseline at 1d249b9

- Supabase email/password identity verified server-side; supplied invalid tokens
  never become guests. Identity verification is independent of Redis.
- Account-owned persistent plans and one initial owner workspace per verified
  Supabase subject. Browser-only session creation is deprecated. Old plans need
  explicit valid-token proof to import; account anchors cannot be used as tokens.
- Immediate persisted app-session revocation on logout. Last active session's
  logout gives its conversation a 30-day recovery window. A new login to the
  same account can recover inside that window; other active sessions remain
  usable. Active conversation inactivity TTL is 30 days, not durable storage.
- Account-owned favourites persist in the app database until removed. They do
  not depend on Redis or chat retention. Owners can delete cached chat history
  independently, with queued writes serialized before deletion.
- Account changes clear/remount workspace/chat/plans and cancel old requests.
  Private responses are no-store. Rapid history updates are coalesced.
- Grounded OpenRouter-only Penny: model selects allowed claim IDs; backend owns
  package binding, mandatory uncertainty, references/winners and rendering.
  Signed-in/guest identity is checked server-side; tokens/IDs are not model input.

- 997 backend tests, 33 frontend tests, `npm run build` clean.
- This commit adds the checker and 7 offline tests for its refusal rules.

| What | Evidence | Real or mocked |
|---|---|---|
| A signs in, is a verified account, guest sees nothing private | sandbox run, 21 of 21 | real Supabase A, real Redis |
| Forged token, tampered `sub`, flipped signature rejected | same run | real Supabase |
| Expired token rejected | same run, app clock moved 2 h | real token, simulated clock |
| Expiry after a real wait (305.8 s) | earlier auth stage | real A |
| Logout revokes at once, revoked token gets 401 on plans, history, chat | same run | real A |
| Logout during a chat run stops Hermes, user sees `session_expired`, no text delivered | same run | real A, fake Hermes |
| Re-login restored own conversation under the former 5-minute policy, plans persist | same run | real A |
| B cannot list, read or refresh A's plans, or restore A's conversation | same run | **mocked B** |
| B writing the same conversation ID leaves A's copy alone | same run | **mocked B** |
| The new checker's whole matrix runs end to end | dry run, 26 of 26 | real A, **B faked at sign-in** |
| Account switch clears old chat and plans in the UI | `frontend/tests/account-history.test.cjs`, `account-plans.test.cjs` | **mocked jsdom** |
| No account IDs, tokens or emails reach the model payload | sandbox run | real A, fake Hermes |

Do not report two-account isolation as passed until the checker below finishes
with `"complete": true` against two real users.

## Run the two-account check (USD 0, no model key)

What it does: signs in two existing users with the publishable key, runs the real
FastAPI routes with a real Redis and a throwaway local app database, and replaces
Hermes with the test-suite fake. It never signs anyone up, refuses a secret or
service-role key, refuses the same email twice, refuses an env file git would
track, and drops any OpenRouter, Anthropic or gateway key from its environment.
It writes only check names, booleans and status codes.

What it checks, both directions (A against B and B against A): distinct verified
subjects; guest sees nothing; forged, expired and revoked tokens fail; each can't
list, read or refresh the other's plans or restore the other's conversation; a
write with the same conversation ID stays owner-scoped; logout mid-run blocks
delivery; re-login recovery is owner-scoped; B is unaffected by A's logout.

### 1. Create account B (Supabase dashboard, once)

Authentication, Users, Add user, Create new user. Use a disposable QA email and a
fresh password, and tick **Auto Confirm User**. It is an ordinary user: no admin
role, no service-role key anywhere. Account A is the existing QA user; ask
Aurindom privately for it, or make a second disposable user for A the same way.

### 2. Get the code

PowerShell:
```powershell
git clone https://github.com/sherlocked-8601/hackathon-app.git penny-auth-qa
cd penny-auth-qa
git fetch origin aurin-test
git checkout -B auth-qa origin/aurin-test
git rev-parse HEAD
```
POSIX:
```sh
git clone https://github.com/sherlocked-8601/hackathon-app.git penny-auth-qa
cd penny-auth-qa
git fetch origin aurin-test
git checkout -B auth-qa origin/aurin-test
git rev-parse HEAD
```
Already have a clone: skip `git clone`, run the rest inside it.

### 3. Private env file (never committed, `sandbox/` is git-ignored)

Open it in an editor so passwords stay out of shell history.

PowerShell:
```powershell
New-Item -ItemType Directory -Force sandbox/two-account | Out-Null
notepad sandbox/two-account/.env
```
POSIX:
```sh
mkdir -p sandbox/two-account && touch sandbox/two-account/.env && chmod 600 sandbox/two-account/.env
${EDITOR:-nano} sandbox/two-account/.env
```
Contents:
```
SUPABASE_URL=https://<project-ref>.supabase.co
SUPABASE_PUBLISHABLE_KEY=<publishable or anon key, never the secret key>
SUPABASE_TEST_EMAIL=<account A email>
SUPABASE_TEST_PASSWORD=<account A password>
SUPABASE_TEST_EMAIL_2=<account B email>
SUPABASE_TEST_PASSWORD_2=<account B password>
REDIS_URL=redis://127.0.0.1:16390/0
```

### 4. Isolated Redis and Python (3.14, same as the production image)

PowerShell:
```powershell
docker run --rm -d --name penny-2acct-redis -p 127.0.0.1:16390:6379 redis:7.4.12-alpine
python -m venv sandbox/two-account/venv
sandbox/two-account/venv/Scripts/python -m pip install -r backend/requirements-dev.txt
```
POSIX:
```sh
docker run --rm -d --name penny-2acct-redis -p 127.0.0.1:16390:6379 redis:7.4.12-alpine
python3 -m venv sandbox/two-account/venv
sandbox/two-account/venv/bin/python -m pip install -r backend/requirements-dev.txt
```

### 5. Run it from the repository root

PowerShell:
```powershell
$env:PYTHONDONTWRITEBYTECODE='1'
sandbox/two-account/venv/Scripts/python backend/scripts/check_two_accounts.py
```
POSIX:
```sh
PYTHONDONTWRITEBYTECODE=1 sandbox/two-account/venv/bin/python backend/scripts/check_two_accounts.py
```
Exit 0 means every check passed. Exit 1 means it stopped; the last line says
where, e.g. `account B sign-in failed: 400 invalid_credentials` (wrong password or
user not confirmed) or `failed: <check name>`. Exit 2 means a setup problem.
Options: `--env-file <path>` and `--out <path>`, both must stay git-ignored.

### 6. Send back only this

- The contents of `sandbox/two-account/result.json`. Read it first: it holds the
  commit, check names, booleans and status codes, nothing else.
- The output of `git rev-parse HEAD`.

Never send the env file, passwords, tokens, screenshots of the dashboard with
keys, or a log you haven't read.

### 7. Clean up

PowerShell:
```powershell
docker stop penny-2acct-redis
Remove-Item -Recurse -Force sandbox/two-account/state-*
Remove-Item sandbox/two-account/.env
```
POSIX:
```sh
docker stop penny-2acct-redis
rm -rf sandbox/two-account/state-*
rm sandbox/two-account/.env
```
Plans and history from the run live only in the local state folder, not in
Supabase. Every session the checker opens is logged out, even when it stops early.
Keep or delete user B in the dashboard as you like.

## Remaining production steps

| Order | Work | Why | Acceptance evidence |
|---|---|---|---|
| 1 | Two-account check above | Mocked B proves the code path, not the real project config | `result.json` with `"complete": true` from two real users |
| 2 | Production SMTP, sender domain, exact Site URL and redirect URLs | The built-in sender is rate limited, confirmations must return to the real address | Fresh signup, delivered mail, back to the app, login; password reset back to the app; note the rate-limit behavior without flooding |
| 3 | Review per-request `/auth/v1/user` verification load, consider verified JWT/JWKS caching | Every protected call hits Supabase from one server IP | Signing-key type checked; signature, issuer, audience, expiry, subject, session, unknown kid and outage behavior tested; latency at the declared concurrency |
| 4 | Real deployed journeys | Local passes don't prove HTTPS, proxy or persistence | Two accounts plus guest on the deployed URL; logout recovery, saved plans, controlled Redis or provider failure; commit, config, date, results, open gaps |

Already done since the last version of this doc: one Uvicorn worker is pinned in
`deploy/compose.prod.yml`, and the VM runbook is `docs/PRODUCTION_DEPLOY.md`
(tested offline only, not on a real VM or domain).

## Code ownership

Yours: `backend/app/auth.py`, `access.py`, `chat_history.py` and their tests;
`frontend/src/auth/*`, account plan and history state and their tests.

Shared, announce before editing: `main.py`, `db.py`, `schemas.py`, `chat.py` and
the API and event contracts. Keep Penny's grounding and selection and the matching,
comparison and adoption contracts as they are.

Keep authorization server-side: user IDs from the browser or model and cached
assistant messages are never credentials. The guest route stays public with no
account data. Old browser plans still need explicit token proof to import. Never
reset a production database to make a test pass.

## Environment

Backend: `SUPABASE_URL`, `SUPABASE_PUBLISHABLE_KEY`, `REDIS_URL`, `APP_DB_PATH`.
Frontend build: `VITE_SUPABASE_URL`, `VITE_SUPABASE_PUBLISHABLE_KEY`, same project.
No service-role key, model key or test password ever goes in the frontend. Vite
variables are baked in at build time; changing runtime secrets doesn't change them.
`backend/scripts/run-local.ps1 -EnvFile <path>` starts the app with an allowlist.

Full checks, from the repository root:
```powershell
New-Item -ItemType Directory -Path sandbox/auth-qa/tmp -Force | Out-Null
$env:PYTHONDONTWRITEBYTECODE='1'
$env:TEMP=(Resolve-Path sandbox/auth-qa/tmp).Path
$env:TMP=$env:TEMP
Remove-Item Env:OPENROUTER_API_KEY, Env:ANTHROPIC_API_KEY -ErrorAction SilentlyContinue
python -m pytest backend/tests -q -p no:cacheprovider --basetemp=sandbox/auth-qa/run
cd frontend; npm ci; npm test; npm run build
```
Node must satisfy the lockfile engines (jsdom wants `^22.22.2 || ^24.15.0 || >=26.0.0`).

## Spend and gates

Auth isolation and load tests need no model spend: use the fake model. Any paid
model test needs a stated open question and an explicit call and cost bound agreed
with Aurindom first. Budget policy is `docs/PRODUCTION_BUDGET.md`; historical
release-testing spend is USD 0.637538 and this checker adds nothing.

Aurindom supplies the production URL, hosting access, SMTP provider and sender,
expected load and VM size. Nothing here authorizes disabling email confirmation
project-wide, rotating signing keys, a new paid provider, cloud provisioning or a
production deploy. Hermes and MCP stay private. Langfuse stays deferred.

## Official references

- Rate limits: https://supabase.com/docs/guides/auth/rate-limits
- SMTP: https://supabase.com/docs/guides/auth/auth-smtp
- Redirect URLs: https://supabase.com/docs/guides/auth/redirect-urls
- Verified claims and asymmetric keys: https://supabase.com/docs/reference/javascript/auth-getclaims
- Sessions and logout: https://supabase.com/docs/guides/auth/sessions

The backend verifies each token remotely before reading its claims. Don't remove
that step unless a real signature check replaces it, and don't assume a legacy
symmetric-key project supports public JWKS.
