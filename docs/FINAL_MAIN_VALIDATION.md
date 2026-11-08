# Final integrated release — 2026-11-08

The final application lives in the separate `hackathon-app/main` worktree.
It combines Aurin `468cdf5` and Arvind `2299863`, including the Giri integration
already in Arvind's history. `PULLS/arvind-test` preserves the compared teammate
snapshot. The old dirty checkout and `hackathon-app/V2` were preserved.

## Fixes found during final integration

1. **Private diagnostics:** incoming logging could expose dictionary keys and
   raw path values. Backend logs now allow known schema fields and route
   templates; browser logs a rejection count. Privacy regressions pass.
2. **Hermes alternatives:** live Hermes repeated the suggested tool, despite
   passing direct-provider tests. The server now binds alternatives to one active
   task and catalog names in the request or latest assistant response. Exclusions
   apply to this answer's evidence and cards only. Conflicting tasks, negation and
   multiple active tasks cannot use this shortcut. Subscriptions/rejections stay
   intact. No supported replacement produces an honest catalog-limit explanation.
   Native Hermes still requires registered reads and valid receipts for remaining
   required tools. Model-written product facts never become evidence.
3. **Browser test drift:** favourites E2E selectors targeted the removed sign-in
   popover. They now exercise the dedicated sign-in page.
4. **Integration gate:** `scripts/api_canary.py --live --edges` adds alternatives,
   scheduling ambiguity and vague requests to the four existing live cases.
   Without `--live`, it only makes free HTTP checks. Eight chat turns are a finite
   batch, not eight billed provider requests; actual costs come from ledgers.

Docker non-root readability, public-only Supabase build settings, durable budgets,
MCP outcome verification, safe Caddy routes and Hermes lifecycle refresh remain.

## Completed local validation

| Gate | Result |
| --- | --- |
| Full backend | 1,261 passed after the final discovery fixes |
| Frontend | 62 passed; also 62 passed under production Node 22 |
| Build | Vite and actual production Docker image passed |
| Live Penny/Hermes/MCP/OpenRouter | 25 catalog/context/ownership journeys passed |
| Additional live edges | Named/contextual alternatives, ambiguity and paraphrase passed |
| Expanded live deployment canary | Eight turns passed |
| Prompt injection | HTTP 422 with safe explanation before generation |
| Directory/toolkit/handoff browser | Desktop/tablet/mobile passed; no page errors |
| Account-data browser | 14 checks passed with synthetic provider, real API/SQLite/Redis |
| Real Supabase account A | Login, identity, authenticated live Penny, revocation and recovery passed |
| Live discovery | Two scans added six distinct records; repeat candidates updated; six review audits |

Discovery used real OpenRouter search and official-page retrieval. Records remain
pending where pricing/subscription/fit proof is incomplete; none were falsely
promoted. Search results alone do not verify pricing. Rendered-page/pricing-table
enhancements remain separate queued work.

Raw SSE, JUnit, browser and ledger evidence stays in ignored workspace
`sandbox/final-main/` and checkout `sandbox/release-gate/`. No credentials or raw
account identifiers belong in this report.

## Evidence boundaries

The local second-account credentials returned HTTP 400. No signup retries,
password changes or security-setting changes were made. Arvind reports 26/26 real
two-account checks on an earlier integrated app. That is teammate evidence,
separate from our independent synthetic two-account browser and real account-A
checks. A fresh real A/B hosted check still needs two working confirmed accounts.

The owner approved **30-day chat recovery**. Logout revokes the old session
immediately. A fresh verified login restores the same account's unexpired cache.
Expiry tests advance the clock; nobody waited 30 days. Redis loss/eviction can
remove cached history. Favourites remain durable SQL account data.

## Hosted testing found and fixed discovery failures

The first Azure release of this integration passed the eight-turn live Penny
canary and real browser login/favourites/Penny/logout, but discovery failed.
An isolated one-request diagnostic confirmed **OpenRouter HTTP 500 on the Exa
search path**, with no usage receipt. The key-status check was HTTP 200. The
production request and diagnostic each retain a USD 0.25 unknown-charge hold.
These holds count toward the testing total; they were not labelled free or erased.

Discovery now explicitly selects `DISCOVERY_WEB_ENGINE=native` by default;
`exa` remains an explicit alternative. There is no automatic paid retry or
engine-switch loop. Native support and citation schema are described in the
[OpenRouter web-search documentation](https://openrouter.ai/docs/guides/features/plugins/web-search).
Search returns up to three requested leads with a bounded 1,200-token output.
Native search sometimes returned commentary followed by a valid fenced JSON
array. A discovery-only parser now accepts one such block or structured citation
URLs. Only HTTPS URLs and titles survive; prices, prose and purported facts do
not. Guarded fetches, deduplication and official-page proof remain mandatory.
Penny's strict factual-answer parser was not relaxed.

Discovery now hashes the client address from the existing trusted-proxy helper.
Previously all visitors behind Caddy shared its IP's four-per-hour quota. Tests
prove separate visitors get separate quotas and untrusted forwarded headers
cannot evade a quota. The persistent global twenty-per-hour and provider request/
dollar limits still apply. A test that accepted HTTP 200 despite a failed report
was also corrected to require `status=completed`.

Safe discovery diagnostics include the selected engine, HTTP status and exception
type, never provider bodies, credentials or prompts. An operator-only recovery
script can acknowledge one reviewed hold while **retaining its held state and
entire charge**: `backend/scripts/acknowledge_discovery_hold.py`. It requires the
exact attempt/reason and `--retain-full-reservation`, refuses multiple unknown or
in-flight requests, records an audit row, and clears only that matching breaker.
It is never invoked automatically by a web request. Existing finite caps still
count the retained charge; acknowledgement is not verification of the actual bill.

The older reused auth-test conversation was correctly refused as expired rather
than revived after the retention change. With a fresh unique conversation ID,
all hosted real-account-A history, identity, authenticated live Penny, logout
revocation and fresh-login recovery checks passed. The browser harness also now
waits for directory and favourite loading before checking a button's state.

The corrected native-engine application scan added **two more distinct tools**
(Wave and Zoho Invoice) from independently fetched official pages, bringing the
local catalog to 32. Its status was honestly `partial`: a page could not be fully
processed and the second automatic review hit the preserved twelve-request
provider limit. One automatic review completed; both records remain pending,
with no unsupported promotion. Successful partial results require actual added/
updated records and no run error; a failed report inside HTTP 200 is a failure.
The final 17 targeted search/quota/recovery regressions passed as well.

Final local app ledgers: **103 settled requests / USD 0.638817**. Two isolated
native diagnostics add **2 settled requests / USD 0.043807**. The hosted failed
production search and isolated Exa diagnostic retain **USD 0.50** in unknown
charges, counted conservatively; final hosted settlement is recorded below.

## Deployment checkpoint

The production app/Hermes/MCP with a fake provider admitted three of five
simultaneous turns, returned two immediate `agent_busy` responses, and served
21 concurrent catalog reads successfully. A forged operation produced
`tool_missing`, never validated output; the next valid turn recovered. Stopping
actions, Hermes and gateway individually gave unavailable readiness and blocked
chat with zero provider forwards while browsing returned 200. Every dependency
recovered; all 30 catalog records survived app/Redis restart. These deliberate
outages were confined to the isolated candidate, not the public VM.

Two genuinely concurrent OpenRouter-backed turns also validated successfully
(8.33s and 14.42s). Chrome independently completed real Supabase sign-in,
favourite persistence across reload, the original review-reply prompt through
the full production stack, and logout. Built frontend assets contain the public
Supabase configuration and none of the private runtime/provider credentials.

Local live ledgers settled **99 provider requests / USD 0.562227** (gateway
91 / USD 0.509584; discovery 8 / USD 0.052643). No held requests or tripped budget.
Including the previously tracked conservative USD 1.294227 gives USD 1.856454
before hosted final-release tests, below the USD 10 ceiling.

**Completed:** application release `c969974` is pushed on main and running on
Azure as `penny-app:c969974`. The prior `468cdf5` and intermediate `a664b80`
images remain available for rollback. All six services are healthy. The final
Git evidence commit may be newer than this application SHA because it changes
documentation only.

Public URL: <https://mainstreet-penny-aurin.belgiumcentral.cloudapp.azure.com>.

- The final eight-turn public HTTPS canary passed, including the original review
  prompt, booking, negation, greetings, both alternatives paths and clarification.
- Real Supabase account-A API checks passed login, identity, authenticated live
  Penny, saved Redis history, immediate logout revocation and fresh-login recovery.
  Chrome also passed login, favourite persistence, live Penny cards and logout.
- Directory/toolkit/selection browser journeys passed on the hosted frontend at
  desktop, tablet and mobile widths, without page errors or horizontal overflow.
- Five simultaneous **real-provider Azure** turns produced three validated
  answers in 10.28–10.84s and two graceful busy responses in 0.44–0.45s. Twenty
  concurrent catalog reads returned 200. This demonstrates the single worker's
  admission limit, not a claim of unlimited VM capacity.
- Native discovery added Wave and Zoho on Azure: catalog 28 -> 30, unique IDs,
  two automatic reviews, no false promotions. The scan was partial because some
  page evidence could not be fully read; verification notes remain visible.
- Private routes reject guests/forged credentials. Sign-in and comparison routes
  load successfully. Secret/Git probe paths return 404. HTTPS validation is enabled.
- Final database check: `ok`; zero active unfinished public-read operations.
  One expired pending operation from the old release remains historical; it
  cannot satisfy a new run. Twenty-three stored public reads succeeded.
- Public frontend assets contain only the public Supabase configuration, with
  private provider/service credentials absent. VM service memory at final idle
  audit was about 480 MiB combined, excluding OS/cache. This is not a load ceiling.

Consistent configuration/database/ledger snapshots are retained in
`/srv/penny/backups/pre-final-main-a664b80` and
`/srv/penny/backups/pre-final-main-c969974`. The VM's original single-branch clone
now tracks main, so future reviewed updates can use `git fetch origin`, an
explicit fast-forward and `scripts/deploy_vm.sh TESTED_SHA`. A failed first
tracking setup was recovered only after confirming the entire index and worktree
equalled the approved target; no reset or user edits were discarded.

The operator hold acknowledgement ran from the VM checkout using system Python,
not inside the runtime image (operator scripts are deliberately outside that
image). Its existing audit row records attempt 8 with the full USD 0.25 charge
still held. Do not rerun acknowledgement blindly.

After testing, the owner explicitly approved **24 lifetime discovery requests,
with the existing USD 1 cap and all charges retained**. That setting is applied;
11 attempts have been used. The app was reloaded and a further live review-reply
canary validated. Gateway controls remain 500 requests / USD 4. Discovery still
allows four public runs per client/hour and twenty globally/hour. These are
lifetime provider counters; restarting does not replenish them.

Owned local test containers and QA servers have been stopped. Their volumes,
ledgers and ignored evidence remain. Azure stays running.

## Final spend and remaining handoff

| Component | Conservative USD |
| --- | ---: |
| Previously tracked project testing | 1.294227 |
| New local stack and isolated native diagnostics | 0.682624 |
| New hosted work, including both unknown-charge holds | 0.757392 |
| **Tracked total** | **2.734243 / 10.00** |

This new batch accounts for 154 provider attempts: 152 settled and two held.
The USD 0.50 in unknown charges is included in full; this is conservative ledger
accounting, not a claim that every reservation was billed. USD 7.265757 remains
under the user's testing ceiling. Existing Azure lifetime spend/holds total
USD 0.997341, including earlier work already counted in the first row.

Remaining acceptance items are a fresh hosted real A/B run with two working
confirmed accounts, and owner/project-admin confirmation of production email
confirmation/reset redirect settings. Local synthetic A/B and teammate-reported
real A/B results must not be misrepresented as that hosted test. Automatically
discovered records need their remaining evidence checks before promotion;
rendered-page and pricing-table improvements remain queued separately.

Machine-readable sanitized evidence is in
`validation/2026-11-08-final-main.json`. Detailed ignored artifacts remain local.

## Cost and Git

The owner set a **USD 10 total testing ceiling**. Prior conservative cumulative
spend was USD 1.294227. Candidate durable ledgers cap gateway at USD 2 and discovery
at USD 1. Fake-provider tests use separate ledgers and incur no provider cost.
Existing Azure lifetime controls remain USD 4 gateway plus USD 1 discovery.
Historical and held charges must never be reset to make a test fit.

Code, Docker/Compose, gates and runbooks belong in Git. Azure resources, private
runtime environments, SSH keys and live SQL/Redis state stay outside Git. Deploy
an explicit tested commit with `bash scripts/deploy_vm.sh APPROVED_SHA`; retain
the previous image for rollback.
