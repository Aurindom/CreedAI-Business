# Owner accounts, short Penny history, and A2UI

## Configure accounts

Create a Supabase project with email/password sign-in enabled and email confirmation configured. Use its **project URL** and **publishable key** in `frontend/.env.local` as shown in `frontend/.env.example`. Put the same values in the backend environment as `SUPABASE_URL` and `SUPABASE_PUBLISHABLE_KEY`. The publishable key is intended for browser use; do not put a Supabase secret or service-role key in the frontend. Restart Vite after changing its environment.

Set `REDIS_URL` on the backend to a managed Redis endpoint. Prefer TLS (`rediss://`) in deployment. For local development, `docker compose -f backend/compose.redis.yml up -d` starts an ephemeral Redis bound only to `127.0.0.1:6379`; use `redis://127.0.0.1:6379/0` for the local backend. The backend will return 503 for account history if the Supabase or Redis configuration is absent. The public catalog and guest Penny chat remain available. No shared or hardcoded account is created: each owner signs up with their own email and password through Supabase Auth.

For the local backend, put `REDIS_URL` and any Supabase public settings alongside the existing Claude key in the ignored `backend/app/.env`, then run `backend/scripts/run-local.ps1 -Python <path-to-your-venv-python>`. The script reads only an allowlist of backend variables, prints no secrets, and keeps the local Claude test cap at $2 unless explicitly configured otherwise. Deployment should inject secrets through its hosting environment, not run this local script.

## What the five-minute cache does

The browser sends a signed-in owner's Supabase access token to the backend. The backend verifies it with that project's Auth `/user` endpoint before any history read or write. It hashes the verified user ID for the Redis key and stores at most 40 display messages plus Penny memory. Each save sets a 300-second Redis expiry. Signing out flushes the latest state and refreshes the expiry, then ends the browser's Supabase session. A login to the same account within five minutes can restore the chat; another account cannot read it. Once Redis expires the key, the history is gone. The HTTP routes send `Cache-Control: no-store` and never log tokens or chat text.

When Supabase is configured, chat history does not use browser `sessionStorage`. Existing anonymous saved plans use a separate private-session token; they are **not** linked to new accounts by this change. Account migration for plans needs a separate ownership flow.

The local Redis container is available through `backend/compose.redis.yml`. The frontend preview still needs a Supabase project URL and publishable key before owner login and five-minute history can be exercised end to end. Unit tests use a fake expiring cache and mocked Auth responses; they do not create an owner or store real chat in a live provider.

## A2UI scope

Penny's `ask_owner` action now sends versioned A2UI v0.9 `createSurface` and `updateComponents` messages in the live stream. A small, allowlisted React renderer accepts only our `PennyQuestion` catalog component, uses the existing chat styling, and sends selected choices back through Penny's normal message path. Both the server cache and renderer validate the surface before displaying it. The backend also sends the old `clarify` event for older clients; the current UI displays only the A2UI version. The rest of the site and detailed recommendation cards still use their existing React components. The official A2UI React package was evaluated, but its dependency tree had a critical security advisory at this version; this bounded renderer avoids shipping that dependency while using the A2UI message protocol.

Official setup: https://a2ui.org/guides/client-setup/ and https://a2ui.org/guides/defining-your-own-catalog/ .
