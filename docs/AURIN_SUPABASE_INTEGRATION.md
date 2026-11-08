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

## SMTP and redirect follow-up

On 2026-11-08, one email sign-in link was requested for existing QA account B, with `create_user: false` and `redirect_to=http://127.0.0.1:5173`. Supabase accepted the request with HTTP 200. The owner then confirmed that the email arrived and its link opened the website and signed them in. Delivery and the successful local callback are owner-observed evidence; Mailjet's dashboard was signed out, so no provider delivery event was independently inspected. No user was created and no password was changed.

Separate live negative-link probes used a deliberately invalid token, never a real confirmation token. Both `http://127.0.0.1:5173` and `http://localhost:5173` were retained as redirect destinations with an `otp_expired` error. An untrusted `https://example.invalid/qa-redirect` destination was rejected and replaced by `http://localhost:3000`. This exposes the project's current fallback Site URL. These probes establish redirect policy, not successful authentication.

**Production remains pending:** no deployed production/staging URL has been supplied, and the fallback Site URL must be set to the intended deployment before release. The fresh-signup flow is now verified separately below; the production HTTPS callback still requires a public deployment URL. Redacted results are in ignored `sandbox/two-account/email-flow-result.json` and `redirect-policy-result.json`. No paid model calls were made. This work does not push or deploy changes.


## Fresh signup confirmation

On 2026-11-08, a unique plus-address alias delivering to the existing QA B Gmail inbox was used for one new test account. A generated password was stored only in ignored `sandbox/signup-check/.env`. The actual app signup UI made the real Supabase signup request, which returned HTTP 200 with a new identity, no authenticated session, and email confirmation required. The UI displayed its inbox/spam confirmation notice and requested the correct `http://127.0.0.1:5173` redirect.

After the owner confirmed the newest signup email, independent server verification passed: Supabase password login returned HTTP 200 with `email_confirmed_at` present, and the local app's `/api/auth/me` identified an authenticated account. The verification session was signed out at both the app and Supabase. The redacted report is ignored `sandbox/signup-check/result.json`. This test created one ordinary QA identity; it did not change existing users' passwords or project-wide confirmation settings.

The owner also supplied a local URL containing `error_code=otp_expired`; that is an expired/invalid-link callback, not a production deployment address. The initial server check correctly refused to mark the fresh identity confirmed, and a resend followed by confirmation of the newest email resolved the test. No confirmation links or tokens were retained in tracked documentation.

Production testing remains blocked on the public HTTPS deployment address. Local repository deployment files are templates, and the repository metadata has no homepage and GitHub Pages is disabled. These observations do not rule out an external deployment; no production address has been supplied. No model calls were made and no deployment was created.
