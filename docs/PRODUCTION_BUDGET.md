# Production budget policy and runbook

This doc does not pick a budget. The numbers below are placeholders and demo
ranges. The owner sets the real values in `deploy/settings.env` at deploy time.

## Two ledgers, both lifetime, neither resets itself

| Ledger | File (host) | Variable | What it counts |
|---|---|---|---|
| App ledger | /srv/penny/state/chat_spend.db | CHAT_SPEND_CAP_USD | A fixed reservation per Hermes run (HERMES_RESERVE_USD, default 0.02). The app never sees the real cost of a Hermes run, so the reservation is kept as spent. |
| Gateway ledger | /srv/penny/gateway/gateway.db | GATEWAY_CAP_USD, GATEWAY_MAX_REQUESTS | Every model HTTP call, with a worst-case reservation settled to the provider's reported cost. The real dollar guard. |

Both are cumulative totals on disk. A restart, a redeploy or a new image does not
give budget back. Only the reconciliation steps below change them.

## Why the default 0.10 is not enough
- `CHAT_SPEND_CAP_USD` defaults to 0.10 and never resets.
- One Hermes run reserves 0.02. A chat that gets rerouted runs Hermes twice and
  reserves 0.04.
- So the default allows 5 ordinary chats (2 or 3 if rerouted) for the life of the
  deployment. W13 measured this: 5 chats, then chat is down with 503.
- After that `/api/chat/ready` returns 503 with `budget: false` and the UI shows
  Penny as unavailable. Browsing keeps working.

## Production variables (deploy/settings.env)

| Variable | Placeholder | Demo range (suggestion, not a decision) | Notes |
|---|---|---|---|
| GATEWAY_CAP_USD | REPLACE_WITH_GATEWAY_BUDGET_USD | 1 to 5 | Hard ceiling on provider spend for this ledger's lifetime. |
| GATEWAY_MAX_REQUESTS | REPLACE_WITH_GATEWAY_REQUEST_LIMIT | 200 to 1000 | Counts every model call, about 2 per normal chat, up to 6 with tool turns. |
| CHAT_SPEND_CAP_USD | REPLACE_WITH_APP_BUDGET_USD | equal to or a bit below GATEWAY_CAP_USD | At 0.02 per run, 1.00 allows 50 runs. |
| HERMES_RESERVE_USD | 0.02 | 0.02 | About 2.4x the measured real rate (about 0.0084 per two-call chat). Lower only after real measurements. |
| CHAT_DAILY_MESSAGES | 60 | 20 to 60 | Per client per day, in memory, resets on restart. |
| CHAT_REQUESTS_PER_MINUTE | 30 | 10 to 30 | Per client burst. |
| CHAT_MAX_INFLIGHT | 3 (compose) | 3 | Raise to 5 only after a paid latency check. |

Rule of thumb: chats you can serve is about the smaller of
`CHAT_SPEND_CAP_USD / 0.02`, `GATEWAY_MAX_REQUESTS / 2` and
`GATEWAY_CAP_USD / real cost per chat`. Keep the OpenRouter key's own limit (set in
the OpenRouter dashboard) at or above GATEWAY_CAP_USD and well below what you'd
be upset to lose. The gateway cap is the app's guard. The key limit is the account's.

Never deploy an uncapped production key. The uncapped allowance for release
testing does not apply to the deployed service.

## Readiness behavior
`/api/chat/ready` is 503 (`Retry-After: 60`) when any of these is true:
- the app ledger can't fit one more HERMES_RESERVE_USD;
- the gateway is tripped (a call with missing or unverifiable usage, or a call
  that died mid-flight and was marked orphaned at startup);
- the gateway has hit GATEWAY_MAX_REQUESTS or GATEWAY_CAP_USD;
- Hermes, the gateway or the database is unreachable.

The chat route refuses with the same reasons, so no money is reserved once
readiness is false.

## Reconciliation and rotation (by hand, stack stopped)

Do this when a ledger is exhausted or tripped, or on a planned budget period.

1. Stop the stack: `docker compose -f deploy/compose.prod.yml down` (no `-v`).
2. Back up both ledgers with `sqlite3 ... ".backup ..."` (see PRODUCTION_DEPLOY.md).
3. Check the real spend for the period in the OpenRouter dashboard (Activity) for
   the gateway key. Write it down with the date.
4. Read the gateway ledger:
   ```
   sqlite3 /srv/penny/gateway/gateway.db \
     "SELECT state, count(*), round(sum(coalesce(charged_usd, reserved_usd)),6) FROM attempt GROUP BY state;
      SELECT tripped, refused FROM gateway;
      SELECT n, reserved_usd, charged_usd, reason FROM attempt WHERE state = 'held';"
   ```
5. Held or unknown charges (`state = 'held'`, or `tripped` set) are never cleared
   automatically. Compare each one with the provider's activity. If you can match
   it, note the real cost. If you can't, treat the reserved amount as spent.
6. Rotate instead of editing: move the old file into the backup folder and keep it
   as the record of that period:
   ```
   mv /srv/penny/gateway/gateway.db /srv/penny/backups/<date>/gateway-period-<n>.db
   mv /srv/penny/state/chat_spend.db /srv/penny/backups/<date>/chat_spend-period-<n>.db
   ```
   New empty ledgers are created on the next start. Lower GATEWAY_CAP_USD and
   CHAT_SPEND_CAP_USD for the new period by any provider spend you could not
   reconcile.
7. Record the period in a spend log: dates, provider total, gateway committed,
   held rows and how each was resolved.
8. Start the stack and check `/api/chat/ready` is 200.

Never copy an older ledger file back to get budget back, and never edit `total_usd`
or `attempt` rows in place.

## Acceptance tests for a budget setting
- With the chosen values, `/api/chat/ready` is 200 on a fresh ledger.
- Set a tiny CHAT_SPEND_CAP_USD in a throwaway copy and confirm chat goes 503 after
  `cap / 0.02` runs while `/api/tools` stays 200 (this is the W13 budget phase).
- Set a tiny GATEWAY_MAX_REQUESTS in a throwaway copy and confirm readiness goes 503
  with the gateway exhausted.
- A held row keeps readiness at 503 until reconciled by hand.

## Testing spend history
Historical tracked release-testing spend before the uncapped testing allowance:
USD 0.637538. New paid validation is added to that total in the shared memory log.
