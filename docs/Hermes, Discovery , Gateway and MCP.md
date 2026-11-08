# Hermes, Discovery , Gateway and MCP

Final integrated/Azure release update (2026-11-08): see
[FINAL_MAIN_VALIDATION.md](FINAL_MAIN_VALIDATION.md) for the final fixes, 1,261-test
backend gate, live Hermes/MCP/Penny/discovery/browser/concurrency evidence,
retained-charge accounting, and remaining real-account-B/production-email checks.
Application release `c969974` is running on Azure. Discovery explicitly uses
native search and an approved 24-request/USD1 lifetime limit. Earlier checkpoint
notes below are historical and do not supersede that report.

## Later checkpoint: more discovery and automatic evidence verification

2026-11-08, after the initial checkpoint below: automatic verification is now
implemented, not deferred. `app/auto_verification.py` reads bounded official
product/pricing pages, extracts structured evidence through metered OpenRouter,
checks literal quotations, task support, business wording, plan inclusion and
flat USD monthly/free pricing, and writes a before/after audit log. It rejects
unsupported quotations, wrong domains, negated features, annual/per-seat/usage
pricing, free trials and mandatory-fee ambiguity as promotion evidence.

Enable `DISCOVERY_AUTO_VERIFY=true` alongside live discovery. Up to three newly
added/updated candidates are checked per research request. Search and verification
share the SAME durable discovery ledger. `DISCOVERY_MAX_REQUESTS` (default4,
maximum24) and `DISCOVERY_SPEND_CAP_USD` (default$1, maximum$2) configure the finite
batch; the expanded tests used20 requests/$2. They are not per-user allowances.
The original per-client/global request and page/time bounds remain.

`Tool.auto_review` records per-check results, date, exact excerpts/URLs, outstanding
notes and the task scope. Passing all rules promotes only that checked task;
matching/comparison must not approve other capabilities merely because the
product has a verified status. Failed rechecks remove eligibility. Only discovered
rows can be changed by the audited promotion writer; curated rows are protected.

Live expansion added InvoiceOwl, Invoicer.ai, InvoiceVisor and Zonstaff. The test
catalog is now35 (24 original +11 discoveries across both checkpoints). A further
review-request search returned no supported additions; rejected pages were not
counted as products. Both accessible vendor evidence and unresolved cases are
reported honestly. At this checkpoint no live candidate passed every promotion
rule: feature/business evidence was confirmed for several, but qualifying-plan
and comparable-price evidence remained insufficient. The positive promotion-to-
recommendation path is covered by synthetic exact-evidence tests, not claimed
as a successful live product promotion. Pricing-table layouts, blocked pages
and ambiguous currency/billing still require further evidence rather than
automatic approval. This engine does not guarantee every official page can be
read or every factual interpretation is error-free.

UI cards distinguish automatically checked products from evidence-checked
candidates and show outstanding checks. Bare Unknown placeholders in directory,
comparison, saved-plan and chat fact presentation were replaced with actionable
vendor-confirmation wording; missing facts are not fabricated.

Final later checks:922 backend tests,27 frontend tests and production build
passed; actual App replay showed live-derived review notes and vendor links.
Evidence is under `sandbox/auto-verification/` in the parent workspace. Combined
reported testing charges since takeover are now **$0.145907 / $5**: Hermes7 calls
($0.029300), discovery/search/verification15 calls ($0.116607). The initial
$0.051583 figure below is historical, not additional. Source remains uncommitted
and undeployed. The live test DB and credential-bearing environment stay outside
the repository; another checkout must explicitly enable/configure the feature.

Reference checkpoint: 2026-11-08. This records the implementation, observed
failures, fixes and evidence from the Codex takeover. It is not a deployment or
production-readiness claim. Source changes were uncommitted at this checkpoint.

## What Pending review means

Discovery has found a candidate on the live web, fetched vendor pages and found
some evidence for the requested capability. It has not established every fact
needed for a confident purchase recommendation: plan inclusion, applicable price,
usage limits, integration prerequisites and business/channel fit can remain
unknown. The product is usable as a research candidate in the directory, with
vendor links, while those facts are checked.

This is a catalog trust status, not a failed Hermes operation or a pending API
request. A lookup can execute successfully and return a Pending review product.
The existing app discovery storage deliberately creates these records with
`origin=discovered` and `status=pending_review`; discovery does not automatically
promote them to verified winners. Matching enforces that distinction.

The hardware false positive found during testing explains why merely fetching a
page cannot establish suitability. Even the seeded catalog is not a guarantee of
universal suitability; its individual facts, dates and task requirements matter.

To qualify a new candidate for verified recommendations, establish its identity,
source-supported task/channel, applicability and required-plan facts; preserve
unresolved prices/limits as unknown; then update its reviewed evidence/status
through an intentional catalog change and validate matching behavior. A generic
review dashboard and automatic promotion workflow were not added in this work.

## Application paths

```text
Penny UI -> POST /api/chat -> verified app account or guest context
  -> Hermes/MCP/gateway readiness
  -> server-register public lookup operations
  -> Hermes v0.23.0 -> metered gateway -> OpenRouter Claude Haiku 4.5
  -> public MCP executor -> catalog result + stored execution evidence
  -> app verifies results, account/session state and grounded selection
  -> validated SSE -> Penny UI

Research more tools -> POST /api/research -> bounded live finder
  -> OpenRouter/Exa search leads -> independent public vendor-page fetching
  -> existing discovery worker extraction -> existing app validator/storage
  -> pending candidates -> refreshed directory
```

These are separate operations: retrieving Jobber from the catalog is a lookup;
finding and ingesting an absent product is discovery. The source now supports
both. Hermes remains public-read-only. Private plan writes stay in FastAPI.

## Problems found and changes made

| Observed problem | Implemented change | Evidence/limit |
|---|---|---|
| Hermes completed with no usable tools | Authenticated MCP inventory/readiness plus expected-operation verification | Missing tools fail explicitly; a completed turn never proves business success |
| Tool body said failure without a Hermes error flag | MCP stores actual public execution results; app checks operation/arguments/catalog hash | Failed, missing, tampered and wrong-operation results are rejected |
| Tool fields had right names but wrong types/requiredness | Validate object shape, exact mapped tool, required fields and string types; reject malformed schemas | Wrong schema/server on actual local route: zero model forwards |
| MCP HTTP421 | Exact private Host allowlist and matching service configuration | Host protection retained; no wildcard security bypass |
| Gateway exhausted but readiness stayed healthy | Gateway cap/trip status checked without the dependency-health cache | New chat refused before model spending; browsing200 |
| MCP died after readiness | Idle-run dependency polling, explicit stop/error and bounded timeout | Injected loss failed in4.1s versus previous10s; not a claim that outages cannot happen |
| Prior conversation missing from Hermes | Bounded structured memory and recent turns supplied as untrusted data | Exclusions/unknown-plan/history and account-switch fixtures covered |
| Real model added prose around JSON | Small PennySelection output protocol and gateway JSON-schema response format | Backend supplies package binding, citations and mandatory claims; raw prose is not rendered |
| Mock10s timeout reused with real provider | Tested60s live-provider configuration | Actual successful journeys8.869s and4.390s; fake-model timing is different |
| Fixed per-chat accounting missed hidden calls | Durable gateway admission and usage settlement for every forwarded HTTP model request | Auxiliary calls count too; title generation disabled and tested |
| No real discovery finder wired | Promoted/reused existing discovery worker and supplied live search adapter at startup | Newly discovered products persisted through actual app route |
| Poor free-search relevance admitted a hardware page | Added service/software-context relevance guard; tested OpenRouter/Exa search configuration | Bad candidate retained only in original isolated failed-test DB, not the repaired catalog |
| Discovery absent from product UI | Opt-in research status/API, task research button, progress/error text and directory refresh | Actual App replay displayed captured discoveries, pending badges and vendor links |

## Files and responsibilities

- `backend/app/chat.py`: runtime selection, prior context, final selection
  validation, selected-runtime readiness, cancellation, safe SSE delivery.
- `backend/app/agent/hermes_runtime.py`: pinned Hermes API transport/event client.
- `backend/app/agent/readiness.py`: Hermes/MCP checks and fresh gateway status.
- `backend/app/agent/tool_execution.py`: public-operation registration, validated
  execution result hashes and execution-deadline checks.
- `backend/app/agent/completion.py`: trusted finalization and exact tool/schema
  contracts; existing private-effect reconciliation.
- `backend/app/agent/context.py`: bounded context builder.
- `backend/app/agent/bindings.py` and `chat_actions.py`: server-owned identity,
  receipt/replay control and private action handling.
- `backend/app/public_mcp.py`: authenticated public-only MCP wrapper, using the
  existing catalog and public operation executor.
- `backend/app/model_gateway.py`: pinned provider request policy, durable atomic
  admission, request counters, reservations, usage settlement and trip state.
- `backend/app/live_discovery.py`: live search adapters and worker integration;
  separate metered discovery search, conservative relevance filtering.
- `backend/app/discovery_worker/`: promoted existing safe fetch/extract/store
  worker, using the current catalog vocabulary rather than its old fixture data.
- `backend/app/discovery.py`: existing candidate validation, pending conversion
  and persistent catalog insertion. Reused rather than replaced.
- `backend/app/main.py`: opt-in finder initialization and bounded research APIs.
- `frontend/src/App.jsx` / `api.js`: selected-task research and directory refresh.
- `frontend/src/chat/ChatPanel.jsx`: backend action/error status display.
- `backend/scripts/run-local.ps1`, `.env.example`, `requirements-mcp.txt`:
  runnable configuration and tested MCP dependency.

## Configuration and restart behavior

See [HERMES_DISCOVERY_RELEASE.md](HERMES_DISCOVERY_RELEASE.md) for settings and
startup instructions. The backend does not automatically read `.env`; the local
runner supports an explicit private environment file. Never commit real keys.

- `CHAT_RUNTIME=hermes` explicitly selects Hermes; there is no silent fallback.
  The direct runtime remains an explicit operator option, not a replacement for
  the repaired Hermes integration.
- Configure private Hermes, MCP and gateway URLs/credentials. Use60s for the
  tested live-provider timeout. Only the provider gateway receives the real
  credential for Hermes model calls.
- Disable `auxiliary.title_generation.enabled` in the pinned Hermes config.
- Enable discovery explicitly with `DISCOVERY_ENABLED=true`,
  `DISCOVERY_PUBLIC_ENABLED=true`, `DISCOVERY_SEARCH_PROVIDER=openrouter` and a
  backend-only `DISCOVERY_OPENROUTER_KEY`.
- Discovery search uses its own metered adapter; it does not receive private
  account data. Independent vendor fetching supplies evidence, not search prose.
- Persistent gateway and discovery ledgers survive restart; deleting a ledger
  to reset spending is not recovery. Unknown/orphaned model charges stay held.
- Initial deployment assumes a single backend worker on the selected Azure VM,
  private runtime services and persistent app/gateway/discovery state. Multiworker
  limits and resource sizing are W13 work, not established by this checkpoint.

## Tests, actual costs and failure history

Final source checks: **908 backend tests passed**, **27 frontend tests passed**,
production Vite build passed and `git diff --check` was clean.

Real Hermes validation used the actual `/api/chat` route, real local Hermes/MCP,
the application gateway and OpenRouter. Two final guest cases passed grounding:
bookkeeping and missed calls. Earlier failures were retained, not counted as
passes: first prose/JSON output rejection, then the too-short mock timeout.

Hermes: seven provider HTTP requests, **$0.029300** including those failures.
Discovery: two provider/search requests, **$0.022283**.
Combined: **nine OpenRouter HTTP requests, $0.051583 of the user's $5 testing
ceiling**. These are reported local test charges, not a team account balance.
Reservations are operational bounds under documented assumptions, not a
provider-enforced account billing guarantee.

Live discovery added three email-marketing candidates (Keap, SendPulse,
tinyEmail) and four phone-answering candidates from ansabell.com, heyjodie.com,
liveansweringai.com and smbsidekick.ai. The isolated repaired catalog grew
**24 ->31**. Both searches were partial; unsupported/blocked sources stayed
unresolved. Source pages were fetched live; no manual product list was inserted.

The first three new records survived app restart. UI replay used the real App
component and captured discovery responses; it verified cards, pending labels
and exact vendor links without another paid call. This is component replay,
not a claim that a fresh paid browser journey was run.

Private-value scan:39 changed/untracked files, zero credential/private-account
matches. The harmless documented loopback Redis URL was identified separately.
Owned temporary test containers/networks were removed; evidence/state retained.

## Evidence locations, relative to the parent workspace

- `sandbox/release-finish/release.log`, `release.xml`: final908-test result.
- `sandbox/release-finish/frontend-tests.log`, `frontend-build.log`: UI/build.
- `sandbox/release-finish/stack/evidence/live-summary.json`, `route/live-*.sse`:
  successful actual-route real-provider cases and final seven-call ledger.
- `sandbox/release-finish/failed-live-summary.json`, `failed-live-0.sse`,
  `stack/evidence/failed-live-run.json`, `timeout-live-summary.json`: failures.
- `sandbox/release-finish/stack/evidence/route/`: schema/server/gateway exhaustion,
  interrupted-MCP and mock-matrix evidence.
- `sandbox/release-finish/discovery-email_marketing.json`,
  `discovery-phone_answering.json`: real newly added records and search usage.
- `sandbox/release-finish/discovery-persistence.json`,
  `ui-discovery-result.json`: restart and directory-render evidence.
- `sandbox/release-finish/secret-scan.json`: source credential check.

Sandbox artifacts and credentials are intentionally not Git deliverables. This
document is the shareable summary; do not assume another checkout has local DBs.

## Remaining work and boundaries

No Azure deployment, commit or push was performed in this checkpoint. Existing
remote production did not change. Real two-account Supabase isolation, W13
mixed-load/VM sizing and hosted application verification remain release work.
Discovery must be explicitly enabled on the running instance; an old checkout
with its old configuration will still show the old catalog.

Public operation labels permit public correlation, not private authority; they
do not cryptographically identify an individual Hermes session. Private MCP
writes stay disabled. New discovery facts still need review before verified
recommendation status; names may be vendor page headings rather than clean
product branding. Do not silently promote a candidate or invent missing prices
to make it look equivalent to the reviewed catalog.
