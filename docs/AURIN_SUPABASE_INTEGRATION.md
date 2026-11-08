# Aurin merge and Supabase verification

Integrated `origin/aurin-test` at `3e91158` into `giri-test`, starting from `66d6190`, on 2026-11-08. Source branches were not modified.

The merge adds bounded concurrent Penny chats, a distinct busy response, production deployment and budget runbooks, and a zero-cost real two-account Supabase checker. The handoff document conflict was resolved by preserving the current 30-day chat policy, persistent favourites, and Mailjet setup history alongside the incoming checker instructions. Incoming historical test totals and five-minute retention evidence remain identified as historical.

## Verification

- Backend: 1,066 tests passed.
- Frontend: 43 tests passed; production build passed.
- Live Creed Supabase preflight: 9 checks passed. The frontend and backend project URL and publishable key agree; Auth health and public settings returned HTTP 200; email authentication and confirmation are enabled; a malformed token was rejected with HTTP 403; a missing API key was rejected with HTTP 401.
- The signed-in Creed dashboard was accessible and displayed seven existing Auth users. No account was created, deleted, or changed during inspection.
- No paid model calls were made. Existing local model spend cap remains $1.

## Pending real-user evidence

Two confirmed QA accounts and their passwords have not been provided or selected. Therefore live password login, two-account isolation, logout/re-login recovery, and cross-account private data access have not been certified by the new checker in this session. The dashboard user list does not establish that two-account isolation passes.

An ignored `sandbox/two-account/.env` template is prepared with the existing public Supabase configuration and an isolated Redis database number, with account credential fields empty. Credentials must remain outside Git and chat. Once two QA users are configured, run `backend/scripts/check_two_accounts.py` and retain its redacted JSON report. It uses real Supabase and Redis with a disposable local app database and a fake model runtime.

SMTP delivery, confirmation links, production redirects, and a deployed staging host remain separate checks. This merge does not push or deploy changes.
