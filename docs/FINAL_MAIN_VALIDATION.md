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
| Full backend | 1,249 passed after the fix |
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

Final concurrency/outage, accounting, main promotion and Azure results are added
below when complete. The previously running Azure release is `468cdf5`; a passing
local gate alone does not update it.

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
