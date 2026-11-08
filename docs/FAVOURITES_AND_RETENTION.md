# Account favourites and chat retention

Favourites are durable account data in the existing app database, independent of Redis. The additive `favourite_tool` table uses `(user_id, tool_id)` as its primary key. The backend derives the owner from the verified Supabase session and rechecks revocation under the database lock. It stores tool references, a name for unavailable entries, and a saved timestamp, rather than stale pricing snapshots. Listing uses current catalog availability. Saving twice is idempotent; removing an unavailable tool remains possible.

`GET /api/favourites`, `PUT /api/favourites/{tool_id}` and `DELETE /api/favourites/{tool_id}` require account authentication and return private, non-cacheable responses. Guests and invalid/revoked sessions cannot use them. No new secrets, cloud project or paid service is required. Existing plans and account ownership are unchanged. Preserve `APP_DB_PATH` with the other durable app data when deploying or backing up.

The UI shares one favourites provider across directory cards, recommendation cards and Penny cards. Hearts report saved state, disable duplicate writes and show failures. Account switches clear the visible list; late responses cannot cross into the next account. The header links to a dedicated favourites section, where saved tools can be compared, opened or removed. Favourites are not stored in unscoped browser storage.

Chat snapshots remain a Redis cache, with up to 30 days of inactivity retention and a 30-day recovery period after the last active session logs out. Access or saving reactivates the snapshot. Logout still revokes the old session immediately. SQLite metadata enforces expiry even if a Redis key incorrectly survives; an expired conversation cannot be revived by a delayed write. This supersedes the previous 24-hour active / five-minute logout policy. Existing data that has already expired cannot be recovered. Redis eviction or loss can still clear cached chats earlier; the local development Redis container is intentionally nonpersistent. Favourites do not depend on that cache and survive its loss.

`DELETE /api/chat/history` removes only the signed-in owner's cached conversations and metadata. The UI discards queued drafts and serializes deletion behind in-flight saves to avoid restoring deleted messages. Deletion failures remain visible; deleting chats never deletes favourites. Other accounts' histories and favourites are unaffected.

## Verification

Backend tests cover idempotent saves/removals, account isolation, unknown or removed catalog entries, guest/forged/revoked credentials, logout and fresh-login recovery, database reopening, Redis independence, 30-day expiry (including retained stale keys), and account-scoped history deletion/failure handling. Frontend tests cover save/logout/re-login, account switching, late mutation responses, failed removal and save/delete serialization.

The browser journey uses the actual frontend, Supabase client SDK, FastAPI routes, SQLite and Redis. The identity provider is a synthetic, loopback-only test seam; it does not prove live Supabase credential verification, email delivery or production deployment configuration. Eleven checks passed, including Penny-card hearts, two-account isolation, next-day recovery using the test clock, history deletion, mobile layout and persisted removal. No paid model requests were made.

## Rerunning the browser journey

Run from the repository root, with backend dependencies installed, Redis running locally, and Playwright available in the test environment. The test uses ports 8001/5175, `sandbox/favourites-qa.db` and Redis database 15. `QA_REDIS_URL` can select a separate test Redis. The server resets only synthetic owners in this dedicated QA database; never run the fixture server as a production service.

In separate terminals:

```text
python backend/tests/e2e/favourites_server.py
node frontend/node_modules/vite/bin/vite.js --config frontend/e2e/vite.config.mjs
node frontend/e2e/favourites.cjs
```

Set `PLAYWRIGHT_MODULE` if Playwright is outside the repository's module resolution path, and `QA_BROWSER_PATH` to use an installed Chrome executable. The explicit QA Vite configuration supplies synthetic public provider settings; no real Supabase account or credentials are used. Results and desktop/mobile screenshots are written under ignored `sandbox/`. Stop both QA servers after the run. Normal `pytest backend/tests`, frontend `node --test tests/*.test.cjs` and the Vite build remain offline with respect to model APIs.
