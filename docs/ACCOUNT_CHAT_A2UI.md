# Supabase accounts, temporary conversation recovery and A2UI

## Configuration

Frontend: `VITE_SUPABASE_URL` and `VITE_SUPABASE_PUBLISHABLE_KEY` at build time.
Backend: matching `SUPABASE_URL`, `SUPABASE_PUBLISHABLE_KEY`, `REDIS_URL`, persistent
`APP_DB_PATH`, and a server-only OpenRouter key/spending configuration for Penny.
Use the publishable key, never a service-role key in browser code. Test account
emails/passwords are for private harness files only and are never deployed.

Signup requests use the app origin as their confirmation return URL. The project
Site URL and allowed redirect list must include the intended addresses. Email
confirmation, SMTP and rate-limit configuration remain operator settings; this
code does not disable confirmation or bypass limits. Configure production SMTP
before public signup. The local launcher loads allowed server settings from an
explicit `-EnvFile`, never test account passwords. It provisions no services.

## Identity and ownership

Protected requests verify the exact bearer token with Supabase `/user` before
reading its subject/session claims. Subject, issuer, audience, expiry and app
revocation are checked. Identity verification is independent of Redis. Invalid
credentials never become guest requests; anonymous Supabase users are not
private accounts.

Plans belong to the verified Supabase user via `account_owner`, with one initial
owner workspace per account. Internal random ownership anchors are not bearer
credentials. Plan operations remain owner-scoped. Plans persist across logout
and cache expiry; new browser-only sessions are deprecated (410).

Old browser plans are not deleted or silently assigned to the next login. An
explicit import requires possession of the valid old private token. Migration
and token revocation commit together. Account ownership anchors are rejected as
legacy credentials, including anchors created by an older deterministic scheme.

## Logout and history

The UI flushes history, calls `/api/auth/logout`, then signs out Supabase locally.
The app immediately records the verified session as revoked; old tokens from
that session cannot access plans/history/Penny even before JWT expiry. A fresh
login has a new session and the same account ID.

History is scoped to account AND conversation. Active history has a bounded
30-day inactivity TTL, not durable storage. The last active session's logout
starts a 30-day recovery window; another active session is not expired.
Same-account login within that window can restore/reactivate the conversation.
After expiry the account/plans persist, but the temporary history is unavailable.
Account favourites live in SQLite until removed and do not expire with chats.
The owner can delete saved history without deleting favourites. See
`FAVOURITES_AND_RETENTION.md` for the current endpoints, UI and browser test.

SQLite metadata enforces the recovery deadline even if Redis expiry cannot be
confirmed; logout reports that condition. Cache failures never disable identity,
grant private data to guests or report a failed save as successful. Private
responses use `Cache-Control: no-store`.

History serialization and in-memory request limits assume one app worker.
Multiple workers/replicas require coordinated cache lifecycle/rate limits before
scaling. Persist the app database, including revocation records, across restarts.

## Penny and guest behavior

Signed-in tokens travel in headers, never model context. Backend verification
derives identity; client `user_id` fields have no authority. Guests have separate
anonymous conversations and no account plans/history. Accounts restore their
cached messages/memory before sending. Identity changes remount workspace/chat/
plan state, cancel old requests and clear the prior account's intake/results.
Failed history recovery does not silently overwrite stored history.

Penny receives only needed business context/public evidence. `submit_answer`
selects allowed IDs; backend validation/rendering owns citations, prices and
uncertainty. The A2UI allowlist remains PennyText, PennySources, PennyQuestion and
PennyRecommendation; presentation does not grant private-action authority or
execute model-supplied markup.

## Evidence

See AUTH_PENNY_INTEGRATION_REVIEW.md for mocked, real-service, browser and model
checks, costs and remaining production gaps. Test credentials are never deployed.
