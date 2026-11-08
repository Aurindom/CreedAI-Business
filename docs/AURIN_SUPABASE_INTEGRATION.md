# Aurin merge and Supabase verification

Integrated `origin/aurin-test` at `3e91158` into `giri-test`, starting from `66d6190`, on 2026-11-08. Source branches were not modified.

The merge adds bounded concurrent Penny chats, a distinct busy response, production deployment and budget runbooks, and a zero-cost real two-account Supabase checker. The handoff document conflict was resolved by preserving the current 30-day chat policy, persistent favourites, and Mailjet setup history alongside the incoming checker instructions. Incoming historical test totals and five-minute retention evidence remain identified as historical.

## Verification

- Backend: 1,066 tests passed.
- Frontend: 43 tests passed; production build passed.
- Live Creed Supabase preflight: 9 checks passed. The frontend and backend project URL and publishable key agree; Auth health and public settings returned HTTP 200; email authentication and confirmation are enabled; a malformed token was rejected with HTTP 403; a missing API key was rejected with HTTP 401.
- The signed-in Creed dashboard was accessible and displayed seven existing Auth users. No account was created, deleted, or changed during inspection.
- No paid model calls were made. Existing local model spend cap remains $1.

## Completed real two-account check

On 2026-11-08, after the owner changed the second QA account, `backend/scripts/check_two_accounts.py` completed against application commit `6c3ff31`: **26 of 26 checks passed**, `complete: true`, with **zero paid model calls**. Both accounts were authenticated and verified by real Supabase. Earlier failure on an unconfirmed second account is superseded by this successful run.

The passing checks cover distinct verified subjects, guest restrictions, forged and revoked token rejection, app-side expiry validation with an advanced test clock, account-scoped plan creation/list/read/refresh, account-scoped history even with identical conversation IDs, logout isolation, stopping an in-progress response on logout, and restoration of the owner's history and plans after signing back in. Model payload checks found no account identifiers, tokens, or emails.

The checker used real Supabase and Redis, an isolated app database, and a fake Hermes/model runtime. The expiration check advanced the app clock; it did not wait for a real token to expire. Recovery was exercised promptly after logout; it does not establish the full 30-day retention duration. Browser account switching remains covered by frontend tests, and favourites were not included in this live checker matrix.

The ignored redacted report is `sandbox/two-account/result.json`. Account passwords, provider tokens and local configuration remain outside Git and chat.

SMTP delivery, confirmation links, production redirects, and a deployed staging host remain separate checks. This merge does not push or deploy changes.
