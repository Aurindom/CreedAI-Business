# Final main integration checkpoint

## Resumed candidate checkpoint

The checkout is now `hackathon-app/main`; the comparison copy of latest Arvind is
`PULLS/arvind-test` at2299863. That update has been merged into this candidate.
The prepared privacy-log fix plus Hermes/complaint/OWASP focused tests passed
121 checks. The candidate is being pushed separately from main before its final
full gate, production-container and live API/browser tests. Those final results
will be recorded in `docs/FINAL_MAIN_VALIDATION.md`; the older blocked checkpoint
below is retained as history. The approved testing ceiling is now USD10 total,
with preserved usage accounting. Azure remains468cdf5 until promotion/acceptance.

2026-11-08. This is an integration candidate, not a completed main promotion.

## Inputs and ancestry

- `origin/main`: `2a2b47c` before this integration.
- `origin/aurin-test`: `468cdf5`, the validated Azure release.
- `origin/arvind-test`: `3386c22`, already containing all of `468cdf5`, plus the
  Giri/Arvind UI, favourites, auth, business-toolkit and chat work.
- Candidate branch: `codex/final-main-validation`, isolated in the coordinating
  workspace at `sandbox/final-main/repo`.
- Merge commit: `2f7cfbb`. It contains both source ancestries. No source branch was
  reset or overwritten; the local V2 reference document was preserved and copied
  into this candidate for inclusion.

`main` and the live Azure application have not been updated by this integration.
Azure remains on `468cdf5`.

## Explicit policy decision

Aurindom selected **30-day chat recovery** for the final app in response to the
integration review. Preserve the incoming 30-day active/recovery policy and its
metadata-expiry tests. Logout still revokes the previous session immediately;
recovery requires a new verified login to the same account. Favourites remain
durable account data, independent of Redis. The old five-minute policy is history
for this candidate, not the requested final behavior.

## Completed baseline verification

The exact merged baseline `2f7cfbb` passed:

- **1,225 backend tests**.
- **62 frontend tests**.
- Production Vite build.

Logs/JUnit are retained under ignored
`sandbox/release-gate/20261108-200550/` inside this candidate checkout.
The local Node24.12 runtime reported jsdom engine warnings; the production image
uses Node22. Validate the candidate's UI tests/build in that production builder
as part of the remaining container gate.

## Review finding and current uncommitted changes

Incoming request-validation diagnostics logged full Pydantic locations and raw
request paths. Dictionary keys and path values can themselves contain private
data. A focused correction is prepared in:

- `backend/app/main.py`: allow only known schema field names/indices in logged
  locations, limit diagnostics, and log the route template instead of raw URL values.
- `frontend/src/chat/ChatPanel.jsx`: log the number of rejected fields rather than
  owner-controlled dictionary keys in browser diagnostics.
- `backend/tests/test_private_validation_logs.py`: regressions for a private
  dictionary key and a private path value.

These edits passed `git diff --check` but **have not yet run through tests**.
The totals above precede this correction. Also untracked: the requested
`PENNY_HERMES_MCP_DISCOVERY_FIXES_AND_E2E.md` reference and this checkpoint document.

## Why verification stopped

Automatic approval review failed on the focused elevated pytest command because
of the account usage limit. The reviewer explicitly reported a review-service
failure, not a determination that the command was unsafe. The command did not
execute. The existing Windows filesystem sandbox denies pytest temporary-directory
access, so the previous release gates used the approved outside-sandbox runner.
Do not bypass the failed approval mechanism or report this correction as tested.

## Remaining gate before promoting main

1. Run the privacy regressions, then `python scripts/release_gate.py` on the final
   edited candidate using the existing isolated Python environment. Fix failures.
2. Build the actual production image with private settings outside Git. Preserve
   the Supabase BuildKit/public-only export, Linux non-root permission check,
   Caddy rules, one-worker/in-flight limits and Hermes restart workflow.
3. Run real app/Hermes/MCP/gateway tests with a fake provider, plus browser journeys
   for favourites, business selection -> Penny, compare/save-plan/draft actions,
   sign-in/reset routes, rich-history retention, deletion and account switching.
4. Run a finite live OpenRouter canary through the candidate, including the original
   review-reply starter, prior routing journeys, business correction, software
   ownership, vague requests and alternatives. The new alternatives unit tests
   primarily exercise the direct runtime; verify parity with the configured
   production Hermes runtime. Verify stored MCP receipts and actual usage.
5. Test discovery/verification/deduplication/persistence and concurrency against the
   candidate. Preserve all earlier ledgers; use separate fake/live accounting.
6. Review teammate-reported real A/B and SMTP evidence in
   `AURIN_SUPABASE_INTEGRATION.md`. Do not label those reports as independently
   rerun against this candidate without obtaining the actual sanitized result or
   running the checker with two confirmed accounts. Do not trigger signup loops.
7. Scan staged/new files for secrets/artifacts; include the requested reference
   document and focused fixes; commit the final changes. Fetch main again, inspect
   any concurrent updates, integrate deliberately, and normal-push the validated
   candidate to main. No force push. Stop for actual conflicts/blockers.
8. Report the resulting main SHA. Azure is a separate deployment checkpoint; do
   not silently replace the working hosted app merely because main changed.

No paid model requests or Azure mutations were made for this integration checkpoint.
The prior total validation cost and all earlier evidence remain unchanged.
