# Release and teammate integration gate

Use `aurin-test` as the integration line and deploy an explicit commit/image tag.
Merge one teammate branch at a time after inspecting its base and diff. Preserve
private settings and persistent state outside Git. Never merge directly on the VM.

## Offline gate (no provider calls)

Install `backend/requirements-dev.txt` plus `backend/requirements-mcp.txt` in an
isolated Python environment; run `npm ci` in frontend. From the repository root:

```
python scripts/release_gate.py
```

The gate runs all backend tests, frontend tests and production frontend build.
It removes provider credentials from child environments and stores logs/JUnit
under ignored `sandbox/release-gate/<date>`. A failure stops the gate. On Windows,
pytest temporary-directory ACL restrictions may require running in the normal
user terminal outside an IDE filesystem sandbox.

`test_catalog_contract.py` checks every catalog plain-words sentence and every
factual UI starter, explicit refusals, multiple needs, and actual `/api/chat`
routes with persisted MCP execution receipts. Those route tests use fake Hermes.
Grounding, forged/missing receipts, schema validation, auth isolation, cancellation,
budget, automatic verification and scanner-path regressions remain in the full suite.
Every new task/starter must pass the same catalog contract.

Canonical catalog sentences are compared by exact normalized sentence identity.
This covers problem descriptions such as "never send it anything" while preserving
explicit refusal checks on free text. A refusal wrapper or changed sentence does
not inherit a canonical example's task authority. New paraphrases still use the
phrase resolver and bounded semantic routing with exact owner excerpts.

## Production image gate

Build using `deploy/compose.prod.yml` with isolated settings, secrets and native
Linux volumes. The UI build requires the BuildKit `frontend_auth` secret from
`app.env`; it exports exactly the public Supabase URL and publishable/anon key.
Internal keys never enter the frontend build environment. Do not put model,
service-role or session credentials into Vite settings.

Run the real app, Caddy, Redis, Hermes, public MCP and gateway. Check browsing,
probe-path 404s, real operation receipts, routing, auth history and restart
persistence. Use a fake provider for five concurrent turns: three admitted, two
retryable `agent_busy`, browsing stays up. Check forged tool outcomes, dependency
stops and recovery with zero model forwards while unavailable. Mock usage belongs
in a separate ledger, never the live accounting ledger.

## Metered canary and deployment

```
python scripts/api_canary.py --base-url https://YOUR_HOST
python scripts/api_canary.py --base-url https://YOUR_HOST --live
```

The first command is free. `--live` sends at most four synthetic guest turns,
stopping on the first failure. Establish finite gateway/app/key budgets before
running it. Record gateway counts, settled/held usage and stored MCP receipts
before and after, plus the exact commit and image. A completed run alone is not
acceptance. Compare the validated SSE tasks and actual stored operation outcomes.

Discovery needs a separate bounded live check with official-page evidence,
automatic-review audit records, duplicate checks and restart persistence. Partial
search results and pending plan/pricing evidence are reported honestly; they never
become verified solely because a model or run reports success.

Deploy the passing SHA with its image tag and persistent volumes; verify HTTPS,
Supabase auth, browser chat, the canary, restarts and accounting on Azure. Keep the
previous image for rollback. Real two-account isolation and SMTP/email redirects
remain release gates owned by the Supabase teammate; mocked account B is insufficient.
