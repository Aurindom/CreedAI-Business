# Penny release validation, 2026-11-08

Baseline: `1c88b8e` on `aurin-test`. This release adds exact catalog-example
routing, owner-excerpt propagation, appointment/customer-list phrase coverage,
production frontend Supabase build settings, safe diagnostic logging and reusable
offline/API release gates. Explicit refusals, multiple needs and grounded output
validation retain their acceptance checks.

## Sandbox evidence

The final image was built with `deploy/Dockerfile` and the actual production
Compose file, with a sandbox override for localhost ingress, isolated credentials,
native Docker volumes and finite budgets. This tests the deployed container shape,
rather than a source-mounted development app. No Azure state was copied or reset.

- Full offline gate: **1,091 backend tests**, **36 frontend tests**, production build passed.
- Real provider matrix: **22/22** journeys passed, including all 12 catalog examples,
  greeting/context handling, business corrections, confirmations, multiple needs,
  negation, resumption, unknown QuickBooks plan and Mailchimp exclusion.
- The exact reviews starter passed separately, and the final rebuilt image passed
  the four-turn release canary (reviews, appointments, negation and greeting).
- Real Chrome against the production stack: one starter click produced exactly one
  chat POST, a Google Business Profile recommendation, sources/caveats and a PDF;
  configured Sign in was available; no page errors.
- Real Supabase account A, production API and Redis: login, verified account identity,
  live authenticated chat, private history, guest refusal, logout/revocation and
  same-owner recovery passed. **Account B still fails sign-in; real A/B isolation
  remains unproven.** The teammate's checker remains required.
- Live discovery ran twice while chat was running: catalog 24 -> 27 -> 28, all IDs
  unique, five automatic-review audit rows. No candidate passed full automatic
  promotion; missing plan/pricing evidence stays pending. A repeat search can add
  a genuinely new vendor as well as update existing entries.
- Zero-cost concurrency with real app/Hermes/MCP and a fake provider: five
  simultaneous chats produced three validated replies and two retryable busy
  refusals in ~0.31s. All 21 browse samples returned 200. Forged MCP receipt was
  rejected (`tool_missing`), and the next legitimate chat recovered.
- Actual dependency stops (MCP, Hermes, gateway): readiness 503, browsing 200, chat
  refused with no answer and zero provider forwards; recovery passed. A chat stream
  can carry an error inside HTTP 200, so the SSE outcome is checked explicitly.
- App/Redis restart retained the 28-tool catalog. Live and mock ledgers are separate.
- Built JS contains public Supabase settings and none of the internal service or
  OpenRouter credentials. Scanner paths return 404 while root/client routes work.

Accounting: **66 settled gateway calls, USD 0.370003**, plus **7 settled discovery
calls, USD 0.046737** = **73 calls, USD 0.416740** for this sandbox batch. No held
live charges or trips. Fake-provider charges are excluded. Concurrent per-case
committed-balance deltas are not individual charges; final settled ledgers are the
cost authority. Earlier historical use is separate and preserved.

Evidence is under the coordinating workspace's ignored `sandbox/release-gate/`
(live-result files, accounting.json, discovery/auth/browser/concurrency/outage
reports). Offline logs/JUnit are under this checkout's ignored
`sandbox/release-gate/20261108-184336/`. Private secrets and transcripts are not Git
artifacts. The initial mock-import failure and HTTP-vs-SSE harness expectation
failure were retained and corrected before the passing results above.

## Deployment acceptance

Deploy this release as an immutable SHA/image with existing persistent mounts.
Preserve the VM's temporary Caddy patch before pulling the committed equivalent.
Rebuild the UI so public Supabase configuration takes effect. Run the free API
checks and a bounded live canary, inspect stored MCP outcomes and gateway usage,
and confirm HTTPS, browser and restart behavior on Azure. Record hosted results
separately; sandbox acceptance alone does not prove the hosted environment.

Remaining external gates: real account B, production SMTP/confirmation/reset
redirect journeys, and provider-key rotation when the key owner is available.
W14 scheduler/browser-rendered pricing-table verification remains deferred.

The first Azure rebuild exposed restrictive Linux checkout file modes inherited
from the deployment shell's umask 077. COPY preserved mode 0600 on source/logging
files, preventing the non-root app from starting. The Dockerfile now normalizes
public source/static file permissions and runs non-root app/gateway imports and
frontend/logging readability checks at build time. Runtime secrets remain outside
these directories and retain restrictive permissions. No paid calls occurred in
this failed startup. Hosted acceptance follows the corrected image build.
