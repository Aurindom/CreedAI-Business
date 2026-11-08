# Teammate handoff: Supabase and Penny production hardening

2026-11-07. Start from the pushed **aurin-test** commit containing this document.
Record `git rev-parse HEAD` in your report; do not start from the older giri-test
or unmodified 443f338 snapshot. Create your own branch, e.g. `auth-production`.

## Assignment and current state

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

Implemented here:

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

Read ACCOUNT_CHAT_A2UI.md, AUTH_PENNY_INTEGRATION_REVIEW.md and PENNY_GUARDRAILS.md.
No private parent-folder memory or sandbox artifact is needed to understand this
assignment. Those artifacts were deliberately excluded from Git.

## Proven baseline and remaining live gap

Final source: **697 backend tests, 23 frontend tests and production build passed**.
Real first-account Supabase/Redis/API checks:19 passed, including a real305.8s
expiry wait. Chrome:8 login/plan/reload/logout checks before integration and8
after. Real integrated account+guest Penny cases both passed (3 model requests,
USD0.011321). Those model tests used real application APIs; Chrome auth tests did
not make paid model requests. These are bounded samples, not general guarantees.

The corrected second account is still not available. A new user-requested check
again returned signup HTTP429. There is no live two-account isolation pass yet.
Do not repeatedly retry signup or disable confirmation to label the test green.
No test emails/passwords, JWTs, project keys or private runtime files are in Git;
get authorized project access and disposable test accounts privately from Aurindom.

## Steps, reasons and acceptance

| Order | Work | Why | Acceptance evidence |
| --- | --- | --- | --- |
| 1 | Complete the second confirmed account and live isolation matrix | Mocked isolation is insufficient for real project configuration | A cannot list/read/refresh B's plans or restore B's conversation; switching accounts clears prior UI state; forged/expired/revoked credentials fail; guest sees no private data |
| 2 | Configure production SMTP, sender/domain and exact Site URL/allowed redirects with the project owner | Public signup/reset emails and confirmation returns must work at the actual deployed address | Fresh signup -> delivered confirmation -> correct app -> login; password recovery -> correct app; record expected rate-limit behavior without flooding |
| 3 | Review auth verification request volume and choose verified JWT/JWKS caching where supported | Current /user verification for every protected call can become a rate/latency bottleneck behind one server IP | Verify signing-key type; test signature/issuer/audience/expiry/subject/session, key rotation/unknown kid, outage behavior and app revocation; measure requests/latency at declared concurrency |
| 4 | Define supported worker count and storage/restart behavior | Process-local cache serialization/rate limits are not multi-worker guarantees | One-worker deployment explicitly enforced until coordinated lifecycle/limits are implemented; plan/revocation DB survives restart; no resurrection of revoked sessions or expired history |
| 5 | Prepare staging/deployment runbook for Aurindom's selected host | Local correctness does not establish HTTPS, persistence or proxy behavior | Same-origin UI/API, HTTPS, secrets injected safely, persistent DB, private Redis, trusted proxy settings, backup/restore and rollback rehearsal on staging |
| 6 | Run the real deployed two-account + guest journeys and failure cases | Release needs user-visible evidence on the actual deployment | Both account journeys and guest browse/chat; logout/cache grace, saved-plan persistence, controlled provider/Redis failures; exact commit/config/date/results and unresolved gaps |

Steps1/2 can be prepared alongside code review for3/4. Deployment happens after
the relevant source/configuration checks pass. Do not wait for Azure to write
tests/runbooks, but do not change live hosting without its separate direction.

## Code ownership and contract coordination

Primary files: `backend/app/auth.py`, `access.py`, `chat_history.py`, corresponding
tests; `frontend/src/auth/*`, account-plan/history state and their tests. Preserve
Penny's grounding/selection and existing matching/comparison/adoption contracts.

`main.py`, `db.py`, `schemas.py`, `chat.py` and API/event contracts are shared with
Claude's W10 integration. Announce any required shared-file/schema change before
editing; one integrator resolves it. Do not have both workers independently
rewrite login, private ownership, discovery or the chat loop. Return a small
branch/PR with migration reasoning, tests and measured results for review.

Maintain server-side authorization: browser/model user IDs and cached assistant
messages are not credentials. Preserve the public guest route without granting
account data. Treat the existing legacy-import exclusion regression as a release
requirement. Preserve saved plans and require explicit possession proof for any
further migration; do not reset production databases to make tests pass.

## Environment and verification

Use your own isolated environment and private test settings. Backend variables:
`SUPABASE_URL`, `SUPABASE_PUBLISHABLE_KEY`, `REDIS_URL`, persistent `APP_DB_PATH`.
Frontend build variables: `VITE_SUPABASE_URL`, `VITE_SUPABASE_PUBLISHABLE_KEY`.
They must identify the same project. Never put service-role/model keys or test
passwords in the frontend. Runtime secret injection does not retroactively change
Vite build variables. The local launcher accepts an explicit `-EnvFile` allowlist.

Create a fresh virtual environment and install `backend/requirements-dev.txt`.
Global Python packages previously had inconsistent source despite version labels.
Use a Node version compatible with the lockfile/dev-dependency engines (jsdom
declares `^22.22.2 || ^24.15.0 || >=26.0.0`). Earlier Node24.12 tests passed with
engine warnings; that is not proof that every version in the broad app engine
range is supported. Keep all temp/cache/build/test output under ignored sandbox.

Example backend checks from the repository root in PowerShell:

```powershell
New-Item -ItemType Directory -Path sandbox/auth-qa/tmp -Force | Out-Null
$env:PYTHONDONTWRITEBYTECODE='1'
$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD='1'
$env:TEMP=(Resolve-Path sandbox/auth-qa/tmp).Path
$env:TMP=$env:TEMP
python -m pytest backend/tests -q -p no:cacheprovider --basetemp=sandbox/auth-qa/run
```

Use `npm ci`, `npm test`, `npm run build` in `frontend` with cache/output under
sandbox; inspect warnings rather than concealing them. Offline tests must unset
real provider keys. For live tests record sanitized case-level evidence, not
credentials or raw token-bearing requests. Do not claim a mock proves Supabase,
SMTP, browser or hosted behavior.

## Configuration decisions and gates

Aurindom supplies the production URL, project/hosting access, SMTP provider and
sender/domain/budget, expected demo load, and selected Azure account/VM size.
Prepare code and a concrete plan without those, then request only the missing
decision/access. Routine reversible source work on your branch need not wait for
individual approvals. No project-wide confirmation disable, signing-key rotation,
new paid provider, cloud provisioning or production deployment is implied here.

No model spending is needed for auth isolation or most load tests: inject the
model and use synthetic requests. Paid model tests require a stated unresolved
question and explicit per-batch call/cost bounds. Known local sample spend is
USD0.075996 of the USD1.50 allowance, not the team-wide USD25 key balance. Do not
repeat the completed model samples just for reassurance. Test accounts are not
production defaults; don't ship credentials or depend on Aurindom's local files.

Before production rollout, agree the tested commit, backup/rollback action,
capacity limit, secrets/configuration and smoke-test results with Aurindom. Keep
Hermes/MCP services private and Langfuse deferred per the current work order.

## Official references

- Email and endpoint quotas: https://supabase.com/docs/guides/auth/rate-limits
- SMTP/recipient restrictions: https://supabase.com/docs/guides/auth/auth-smtp
- Redirect configuration: https://supabase.com/docs/guides/auth/redirect-urls
- Verified/cached claims and asymmetric-key dependency:
  https://supabase.com/docs/reference/javascript/auth-getclaims
- Sessions/logout behavior: https://supabase.com/docs/guides/auth/sessions

The current Python backend verifies remotely before decoding claims. Do not
remove that step unless a proper signature-verification path replaces it. The
getClaims reference describes Supabase's approach; do not paste browser SDK code
into FastAPI or assume a legacy symmetric project supports public JWKS checks.
