# V2 integration and acceptance - 2026-11-08

Codex merged the current integrated application with `giri-test` in this independent V2 checkout. Claude should review this tree next. Nothing was pushed or deployed to Azure.

## Source and isolation

- Original base: `914e793d0f493bf5647b6f0910c8d821dfe64399`.
- Current-source checkpoint: `a3a3df8` (all 51 modified/untracked source files preserved).
- Incoming: `81559fd6d129325fcae447c5f70c07cefd15bf30` from `giri-test`.
- V2 branch: `codex/v2-integration`. This is a separate Git repository inside `hackathon-app/V2`.
- Original source: all 51 snapshot hashes still match. Only its local Git exclude was extended to hide the nested V2 checkout.
- Real V2 `app.main:app` ran in Uvicorn, with real Hermes v0.23.0, public MCP, gateway, SQLite and built React UI. No fixture account-verifier override was used. These live journeys used guests, not real Supabase accounts.
- Separate `codex-v2` containers/volumes and localhost ports 8152/5178. Runtime credentials and evidence stay outside Git. All 187 source files were scanned against private `.env` values; no matches.

## Merge decisions and defects fixed

1. Preserved task-first intake, conversational routing, service links and compact cards from Giri. Updated definitions/callers together for intentional `require_background` removal.
2. Preserved server account/action gates, stored operation verification, automatic-review scope and conservative cost controls from the current application.
3. Fixed the incoming social-reply escape: an unseen vendor sentence such as `TrialNova automates your bookkeeping.` could pass the old denylist. The model now chooses intent/approved reply ID; the server owns the social wording. Arbitrary vendor prose cannot be rendered through this route.
4. Added Hermes social parity without exposing private tools. Only `get_tool_details` is available over public MCP. Recommendations remain backend-bound evidence selections.
5. Actual live tests exposed missing Hermes semantic routing: confirmations, corrections, negation, resumption and multiple needs could produce clarification, small talk or an incomplete shortlist. Added a bounded routing proposal, validated against exact owner excerpts and known tasks. The gateway constrains excerpts in its native JSON schema. A changed route rebuilds evidence and performs fresh registered reads in one additional run. Maximum two Hermes runs; no blind retry.
6. Added single-pending-task confirmation and explicit resumption handling. Preserved active/pending context as bounded data. A greeting does not revive an old task.
7. Preserved source dates, caveats and vendor questions in the summary/PDF. V2 builds into its own `frontend/dist`; development proxy targets V2 port 8152.

## Evidence

Paths below are relative to the enclosing workspace, not this Git checkout.

| Check | Result | Evidence |
|---|---|---|
| Complete backend suite | 982 passed, 56.40 seconds | `sandbox/v2-integration/backend-acceptance.log`, `.xml` |
| Offline grounding evals | 81 tests within the full suite, including the versioned 30-case scenario matrix | `backend/tests/test_grounding_quality.py`, `backend/evals/grounding_cases.json` |
| Automatic verifier | 14 offline tests, including successful promotion, misleading evidence rejection and demotion | `backend/tests/test_auto_verification.py` |
| Frontend | 32 passed; production build passed | `sandbox/v2-integration/frontend-acceptance.log`, `frontend-build-acceptance.log` |
| Final real HTTP journey eval | 10/10 passed | `sandbox/v2-integration/stack/evidence/live-summary.json` and `route/*.sse` |
| Actual Chrome, built UI | Recommendation, social follow-up, summary/PDF, no page errors | `sandbox/v2-integration/browser-report.json`, `v2-browser.png`, `v2-summary.pdf` |
| Real Hermes/MCP with mock upstream | 7 cases: valid reads/social reply succeed; no read, failed lookup, fake label, forged save and skipped reads do not validate | `sandbox/v2-integration/stack/evidence/mock-summary.json`, `mock-final.log` |
| Stopped MCP, stopped Hermes, exhausted gateway | Readiness503, visible chat error, browsing200, zero model forwards in each case | `sandbox/v2-integration/stack/evidence/route/actions_down.json`, `hermes_down.json`, `gateway_exhausted.json` |
| Live discovery + automatic review | Invoicing24->27 tools; all3 independently checked; no full promotion. Staff scheduling returned a partial result with no accepted tools | `sandbox/v2-integration/stack/evidence/live-first-failures.json` |
| Repeat discovery |27->27; same3 entries updated/rechecked; no duplicate records | `sandbox/v2-integration/stack/evidence/discovery-repeat.json` |

The ten live journeys cover greeting after a task, greeting with substantive request, misspelled resource-shortage request and stale business, confirmation, explicit business correction, two distinct needs, negation of an old need, explicit resumption, unknown QuickBooks plan and retail excluding Mailchimp. Observed final API latency was approximately 4.7-19.0 seconds. This is a small correctness sample, not a load benchmark.

Early live failures are deliberately retained in `live-first-failures.json` and `live-second-failures.json`. The final ten-case report is `live-summary.json`. Do not use early failures as final results or omit them from debugging history.

## Cost and interrupted request

V2 provider usage: 84 settled requests, USD0.444339. One interrupted request retains its full USD0.047292 reservation because actual usage was not confirmed. Conservative V2 total: **USD0.491631**.

Including prior authorized Hermes/discovery work (USD0.145907), the shared conservative total is **USD0.637538 of USD5**, leaving **USD4.362462**. These are local ledger totals, not an OpenRouter account balance. Mock-provider charges are synthetic and excluded.

A test restart interrupted a model request. The old gateway correctly recovered its reservation as `held/orphaned` and blocked further admission. That ledger was preserved, not cleared. A separate capped batch was used for corrected routing tests; all reservations across both batches count toward the shared ceiling. Accounting: `sandbox/v2-integration/stack/evidence/accounting.json`, `discovery-repeat.json`. Do not clear these ledgers to obtain more allowance.

## Limits and Claude's next review

- The new tools have real official feature/business-fit evidence, but the current checker could not establish the required plan/pricing link. They correctly remain `pending_review`. Successful promotion has offline fixture coverage; **no live full promotion was demonstrated**. W14's richer rendered-page/pricing-table verification remains deferred.
- Scheduled expansion was not added. Live discovery remains explicitly enabled, metered and bounded; scheduling/browser expansion is W14.
- Real two-account Supabase isolation, production SMTP/auth configuration, Azure deployment, public networking and multi-user capacity are separate acceptance work. This run does not prove them. The existing per-process capacity remains1.
- Hermes printed SQLite warnings for its Windows host-mounted home directory. Deployment should use native persistent storage for Hermes state; this desktop integration run does not establish production filesystem/concurrency reliability.
- Review `hermes_routing.py`, `chat.py` routing/finalization, gateway schema, per-task verification eligibility and summary sources. Re-run offline suites first. Use the final live artifacts before deciding whether another paid test adds evidence.
- Code remains in V2 until Aurindom explicitly chooses promotion/push/deployment. Do not overwrite the original checkout or work on its W13 changes concurrently.

## Local reproduction

From the enclosing workspace:

```powershell
sandbox/w10-bindings/venv/Scripts/python.exe -B -m pytest hackathon-app/V2/backend/tests -q -p no:cacheprovider --basetemp sandbox/v2-review/pytest
npm --prefix hackathon-app/V2/frontend test
npm --prefix hackathon-app/V2/frontend run build
```

The current machine reuses the existing Python environment and a local junction to existing frontend dependencies. A teammate can install `backend/requirements-dev.txt`, `backend/requirements-mcp.txt` and run `npm ci` normally; the junction is not committed.

To start the actual V2 stack without running a paid test batch:

```powershell
sandbox/w10-bindings/venv/Scripts/python.exe -B sandbox/v2-integration/control.py start
node sandbox/v2-integration/serve-built.cjs
```

Open `http://127.0.0.1:5178`. The helper reads only the existing key from ignored `sandbox/.env` into the process environment; it does not print it. Startup itself makes no completion requests. Using Penny or research incurs metered provider calls. `control.py live` explicitly reruns paid journey tests; it is not a startup command. Stop with `docker compose -p codex-v2 -f sandbox/v2-integration/stack/compose.yml down`; retain named volumes and ledgers.
