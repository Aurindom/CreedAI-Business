# Discovery, JavaScript checking and automatic verification

Checkpoint: 2026-11-08. This document distinguishes implemented behavior,
observed live results and work still required. See also
[Hermes, Discovery , Gateway and MCP.md](Hermes,%20Discovery%20,%20Gateway%20and%20MCP.md).

## How new tools actually enter the application

The tools were not manually inserted. We selected tasks to start finite tests;
the application searched for products and extracted their evidence automatically.

```text
Selected task -> Research more tools -> POST /api/research
  -> live OpenRouter/Exa search (existing catalog names excluded in the query)
  -> candidate URLs, not trusted facts
  -> independent official-page fetching/extraction
  -> schema, source, capability and duplicate checks
  -> persistent discovered-tool records
  -> automatic evidence checks when enabled
  -> refreshed directory with status, notes and vendor links
```

The first live searches added seven candidates. Later invoicing and staff-
scheduling searches added InvoiceOwl, Invoicer.ai, InvoiceVisor and Zonstaff.
The isolated test catalog grew24 ->31 ->35. These are11 discovered additions.
A review-request search added none because its extracted evidence did not meet
the current task-support rules. Raw search leads are not counted as tools.

The test script subsequently named some of those already-discovered IDs to
recheck their vendor evidence. That selected verification targets; it did not
create their records manually. No new products were inserted into catalog.json.

Current discovery is **on demand**. Search/extraction/storage happen automatically
after the trigger. There is no scheduled crawler or periodic discovery job yet,
and browsing a page does not launch another paid search automatically. The app
must be explicitly configured with discovery enabled; an old teammate checkout
or old running service still uses its previous catalog/configuration.

## Technologies and responsibilities

| Stage | Technology | What happens | Current status |
|---|---|---|---|
| Discovery trigger/UI | React, JavaScript, fetch | Selected task starts research; results refresh directory | Implemented |
| API and contracts | FastAPI, Python, Pydantic | Validate inputs and bounded requests; return structured reports | Implemented |
| Live search | OpenRouter Haiku4.5 with Exa web search | Find public product leads beyond existing catalog | Live-tested |
| Page access | Python httpx, public-IP validation/pinning | Independently fetch vendor pages with bounded bytes/time/redirects | Live-tested |
| Static extraction | Python HTMLParser and conservative phrase/context checks | Extract visible HTML text, identity, feature and pricing leads | Live-tested; not a browser |
| Automatic checking | Tool-less structured model extraction + Pydantic + deterministic Python rules | Validate quotations and task/plan/price evidence | Implemented and live-tested, partial outcomes |
| Persistence/audit | SQLite | Store candidates, shared spend ledger and before/after review records | Implemented |
| Recommendation eligibility | Existing matching/comparison engine | Only checked scope qualifies; unconfirmed plan/price blocks confident recommendation | Regression-tested |
| UI JavaScript checker | Node.js, esbuild, React, jsdom | Compile/render real components and inspect badges/notes/links/SSE rendering | Implemented; component replay |
| Vendor JavaScript rendering | Proposed Playwright + Chromium | Execute vendor-page JavaScript before extracting evidence | NOT implemented in this checkpoint |
| Scheduled discovery | Future bounded server job using the same finder | Periodically find/recheck tools without a button click | NOT implemented |

## What the JavaScript checker does and does not do

The existing UI checker uses the actual React application component, compiled
with esbuild and rendered in jsdom. Fetch responses are replayed from captured
live discovery output. It checks the research request's task, refreshed cards,
review labels, outstanding evidence notes and vendor links. Earlier chat replay
also checked validated answers and visible failure states.

jsdom is not a full browser rendering engine. It does not prove arbitrary
vendor JavaScript pages can be crawled. The application currently fetches HTML;
some script-built, blocked or authentication-only vendor pages remain unreadable.
Automated local Chrome checks from earlier auth work are separate evidence and
do not establish a discovery browser fallback.

## Planned vendor-page browser checker

Add an optional Playwright/Chromium worker only for sources whose static fetch
fails to expose useful content. Keep it separate from private account sessions.
Use an ephemeral browser context without saved logins, bounded navigation/render
time, resource counts and output bytes. Validate every redirect/resource request
against the public-source/network policy; block private/internal destinations,
downloads and unsupported protocols. Browser network access needs equivalent
SSRF protection, not just an initial public URL check.

Read the rendered DOM and structured pricing/feature sections, retaining source
URL, date and exact excerpt. A page loading successfully still does not establish
plan entitlement. Return blocked/login-required/insufficient-evidence explicitly;
do not bypass access controls or retry indefinitely. The browser is a page-reading
fallback, not an automatic reason to approve a product.

Acceptance: one actual JavaScript-rendered official page yields usable sourced
evidence; one blocked page fails cleanly; both use the same evidence validator.
The fetched/static/rendered provenance must be distinguishable in the report.

## What automatic verification currently does

`backend/app/auto_verification.py` receives a discovered tool and a task. It:

1. Reads bounded official product/pricing pages using the safe fetcher.
2. Requests structured extraction of feature, business-fit and plan evidence.
3. Matches quotations to actual fetched text on the product's vendor domain.
4. Checks task phrases/negation, business applicability, explicit plan inclusion,
   currency and monthly price basis. It does not assume a bare dollar sign is
   USD or an annual equivalent is a monthly subscription price.
5. Records pass/fail checks, source excerpts/URLs, date and outstanding notes in
   `Tool.auto_review`. Search and verification share a durable metered ledger.
6. Promotes only when all configured requirements pass, retaining before/after
   documents in automatic_review_log. Curated records cannot be overwritten by
   the discovered-tool promotion writer.
7. Limits eligibility to the checked task. A failed recheck removes eligibility.

Discovery invokes this for up to three new/updated candidates per request with
`DISCOVERY_AUTO_VERIFY=true`. A model's success claim, completed request or
confidence score is not approval. Exact quotes are necessary evidence but are
not an infallible semantic proof; pricing-table associations still need stronger
structural parsing. The rules intentionally hold ambiguous cases.

There is no generic review dashboard. Positive automatic promotion and actual
matching eligibility are exercised with exact-evidence fixtures; this code path
is implemented. **No live candidate tested in this checkpoint passed every plan/
price promotion requirement.** Several had verified feature/business evidence
but insufficient qualifying-plan/currency/billing evidence. Do not describe that
as a successful live automatic promotion.

## What is shown to users

- A new tool is a research candidate until enough evidence is established.
- Attempted verification shows its evidence notes and specific remaining checks.
- Fully qualified automatic results have an Automatically checked label and
  task scope; that is not universal certification of the vendor or every feature.
- Missing facts use wording such as Confirm with vendor or Check vendor pricing,
  rather than a bare Unknown placeholder. The underlying uncertainty is retained.

## Live testing: precise boundary

| Check | Real external service used? | Observed result |
|---|---|---|
| Actual /api/chat through Hermes/MCP/gateway/OpenRouter | Yes | Two final guest journeys validated |
| Discovering absent tools via /api/research | Yes: search and vendor HTTP | Eleven additions across four successful task families; partial searches recorded |
| Automatic official-page checks | Yes: vendor HTTP and metered extraction | Feature/business checks confirmed for several; unresolved plan/price retained |
| Fully eligible automatic promotion | Fixture evidence | Positive and rejection paths passed; no successful live promotion claimed |
| UI JavaScript component checker | Captured live data replay | Cards, notes and links displayed correctly; no extra paid call |
| Vendor JavaScript-rendering fallback | No | Not yet implemented/tested |
| Scheduled discovery | No | Not yet implemented/tested |
| Azure-hosted whole application | No | Not deployed |

Final backend922 tests, frontend27 tests and production build passed. Relevant
evidence is under the parent workspace's sandbox/auto-verification and
sandbox/release-finish folders. Total reported testing since takeover is
$0.145907 across22 OpenRouter HTTP requests, within the authorized$5 combined
Hermes/discovery testing ceiling. This is local accounting, not the account
balance. Credentials and sandbox databases stay out of Git.

## Next engineering steps

1. Improve vendor verification: optional rendered-page reading and structural
   plan-table/currency extraction. Prove one real candidate can pass the same
   promotion rules and reach a task-appropriate recommendation; also prove a
   contradictory/blocked candidate remains unapproved. Do not lower rules just
   to manufacture that positive example.
2. Add bounded automatic triggers: an opt-in background job for a task lacking
   suitable results and a periodic refresh. Reuse the same finder; deduplicate
   concurrent searches, reuse recent results, preserve the one-discovery-worker
   limit, and enforce aggregate request/spend budgets. Never launch paid searches
   on every page view or expose operator credentials to the frontend.
3. W13 mixed-load/concurrency and resource measurements, two-account Supabase
   checks, source review/commit direction and user-led Azure VM setup/hosted tests.

This document adds no scheduler or browser implementation by itself. No new
paid calls, deployment, commit or push were performed while writing it.
