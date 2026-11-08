# Supabase ownership, logout recovery and grounded Penny — 2026-11-07

## Outcome

Implemented account-owned plans, verified identity on Penny requests, anonymous
guest behavior, immediate application-session revocation and five-minute
conversation recovery. Then integrated the previously sandboxed grounded Penny.
Changes are local and uncommitted; no push or deployment occurred.

Supabase remains the identity provider. Redis remains temporary conversation
storage; SQLite holds account/workspace ownership, private plans, session
revocation and recovery deadlines. Test credentials live only in a private
sandbox environment file and are not application defaults or production users.

## Evidence by stage

| Stage | Check | Result |
| --- | --- | --- |
| Account changes before Penny integration | Full offline backend suite | 634 passed |
| Account changes before Penny integration | UI tests and production build | 20 passed; build passed |
| First real-service test | Real Supabase, Redis and application routes | 19 checks passed; second-account check pending |
| First real-service test | Actual grace-period expiry | 305.8-second real wait; conversation expired, saved plan remained accessible after fresh login |
| First Chrome test | Real sign-in, plan save/reload, sign-out, old-token replay | 8 passed |
| After Penny integration | Real Supabase + Redis + OpenRouter through integrated API | Signed-in and guest cases both passed; 3 model requests |
| Second Chrome test | Integrated app sign-in/plan/logout behavior | 8 passed; no model call from browser |
| Final offline release checks | Full backend suite | **697 passed in 35.14 seconds** |
| Final offline release checks | UI suite and production build | **23 passed; build passed** |

Live Supabase/model checks use actual application ASGI routes and real external
services; they are not mocks. Chrome checks exercised the local HTTP application
with the real Supabase SDK. The paid model was exercised through API tests, not
a freshly paid end-to-end browser conversation. Earlier failed test/setup
artifacts are retained; they are not counted as passes.

Private evidence stays outside the repo:

- `sandbox/auth-stage1/live-auth-result.json` and `live-auth-execution.log`.
- `sandbox/auth-stage1/browser-result.json`, plus no-email logout screenshot.
- `sandbox/auth-stage2/integrated-live.jsonl` and `live-execution.log`.
- `sandbox/auth-stage2/browser-result.json`.
- `sandbox/auth-stage2/backend-release.log/xml`, `frontend-release.log`, and
  `frontend-release-build.log` / build output.

## Behavior and authorization

1. The backend verifies the bearer token with Supabase, then validates/binds its
   subject and session claims. Client `user_id`, cached messages and model
   arguments are never private-operation authority. Missing credentials mean
   guest mode; invalid supplied credentials are rejected instead of downgraded.
2. Verified Supabase user IDs map to stable account-owned plans and one initial
   owner workspace. New browser-token plan sessions are deprecated. Old plans
   remain available for explicit possession-proved import; no silent attachment
   to the next signed-in account. Another account's plan IDs cannot grant access.
3. Logout revokes the app session immediately and closes Supabase's local
   session. Old tokens cannot access plans/history/Penny even if the JWT itself
   has not expired. Records persist across app restarts. A fresh login uses a
   new session with the same account ID; saved plans survive.
4. Active conversation history uses a bounded 24-hour inactivity TTL. The last
   active session's logout starts a 300-second recovery window. Same-account
   login within it restores history. After it expires, history is unavailable;
   the account and plans are retained. Other active sessions are not expired.
5. Private APIs emit no-store responses. Account switches remount the entire
   workspace/chat/plan UI, cancel old chat requests and clear prior intake and
   results. History hydration precedes signed-in chat. Failed recovery does not
   silently overwrite the old stored conversation. Rapid updates to one
   conversation are coalesced before saving.
6. Penny accepts the verified account token in headers and derives identity
   server-side. Live tests assert that user IDs and tokens are absent from
   provider payloads. Public guest advice has no account identity or plan access.
   Session revocation is checked before model rounds and outgoing frames.
7. The model selects approved claim IDs. Backend policy supplies package binding,
   mandatory uncertainty, citations and winner support; strict validation precedes
   A2UI rendering. Invalid selections remain rejected with safe diagnostic codes.

## Review correction

Review found a migration vulnerability in an intermediate implementation:
deterministic account ownership anchors could be guessed from public user IDs
and mistaken for old browser credentials. New anchors are random; legacy-token
verification explicitly rejects every account-owned anchor, including older
deterministic ones. A dedicated regression covers that older-anchor case. The
fix and private-cache headers were included in the final 697-test offline run.
The live test accounts contain only synthetic application plans.

## Real Penny results and cost

- Signed-in account: unknown QuickBooks plan, synthetic bookkeeping question.
  Backend-derived identity matched the real login. Response validated, included
  plan/pricing uncertainty and official links, and did not repeat the plan
  question or invent entitlement.
- Guest: synthetic retail email-marketing request excluding Mailchimp. No account
  authority; actual catalog action and final answer validated. No excluded-tool
  suggestion or invented replacement. Guest private-plan request returned 401.
- After logout, the old token could not validate another Penny request.

Three OpenRouter requests cost **USD0.011321** within the USD0.05 live-test bound.
Known cumulative local sample spend is **USD0.075996** inside the USD1.50 allowance,
not a verified shared-key/team-wide balance. No extra paid calls were made to
repeat reassurance. The application ledger uses conservative reservations; it
is not a provider/account hard cap. No direct Anthropic calls were made.

## Remaining gaps before public production

**Second account:** its corrected signup was rate-limited (HTTP429). The user chose
to wait. No retry loop or confirmation bypass was used. Real two-account browser/
service isolation remains pending; offline cross-owner/forged-token checks pass.
One further user-requested sign-in/signup check again returned signupHTTP429.
Continuation is assigned in PRODUCTION_AUTH_TEAMMATE_HANDOFF.md rather than a
retry loop; coordinate Claude's parallel work with CLAUDE_WXX_RESUME.md.
An earlier unused unconfirmed signup under the prior second address may remain
in the user's project; it was not deleted or silently reassigned.

**Email and redirects:** first account confirmation succeeded but its return URL
was unavailable. Signup now requests the current app origin; the operator must
still configure Supabase Site URL and allowed redirects for the real deployment.
Production email delivery/SMTP has not been configured or tested here. Supabase
documents restrictive built-in email limits and recipient restrictions:
https://supabase.com/docs/guides/auth/rate-limits and
https://supabase.com/docs/guides/auth/auth-smtp . HTTP429 alone does not identify
the exact configured quota that was reached.

**Scale:** the implementation currently verifies protected requests with Supabase
remotely. History coalescing reduces calls, but production load/endpoint quotas
must be tested; verified JWT/JWKS caching can be evaluated before scaling.
History lifecycle serialization and in-memory request limits assume one worker.
Multiple workers/replicas require coordinated lifecycle/rate limits. Persist the
SQLite database; no hosting/HA/load-test claim is made.

**Scope:** no deployment, HTTPS/remote routing verification, real provider secret
leak interception, live vendor discovery, Hermes/MCP identity receipts or full
business-team membership model was added. Stored catalog fidelity is not proof
that every vendor fact is current. Cached memory is temporary, not a durable
business profile. No test passwords or private sandbox artifacts belong in Git.

## Assessment

The requested account and Penny behaviors are implemented and have substantial
offline, real-service and browser evidence. This is ready for review and a
controlled prototype rehearsal. It is **not yet verified for unrestricted
public signup/production scale**: complete the second-account live test, email/
redirect configuration, deployment checks and expected-load validation first.
