# Hermes and live discovery checkpoint - 2026-11-08

The application `/api/chat` path now runs Hermes with verified public MCP
operations, bounded conversation context, dependency readiness and a metered
provider gateway. Private writes remain in FastAPI. A completed Hermes turn or
`success:true` is not proof: the application checks its registered operation,
arguments, execution deadline and the executor's catalog-result hash before
validating/rendering an answer.

## Runtime configuration

The backend does not automatically load `.env`. The local script now supports
the settings in `backend/.env.example`:

```powershell
backend/scripts/run-local.ps1 -Python PATH_TO_VENV_PYTHON -EnvFile PATH_TO_PRIVATE_ENV
```

For Hermes select `CHAT_RUNTIME=hermes`; configure `HERMES_API_URL/KEY`,
`PUBLIC_MCP_URL/TOKEN`, `MODEL_GATEWAY_URL/KEY`, and an appropriate real-provider
`HERMES_TIMEOUT_SECONDS` (60 was tested). Use private service URLs, never browser
URLs. Run Hermes v0.23.0 with only the marketplace public tool enabled; its model
base URL points at the gateway with the gateway client credential. Disable
`auxiliary.title_generation.enabled`; the tested value is `false`.

Run the public MCP server with `python -m app.public_mcp` and the provider gateway
with `python -m app.model_gateway`. Install `backend/requirements-mcp.txt` for the
MCP process. MCP and the application share the same persistent `APP_DB_PATH` on
the initial single-VM/single-app-worker deployment. Set `PUBLIC_MCP_ALLOWED_HOST`
to the exact private host:port. Do not expose Hermes/MCP/gateway to the public.

Gateway process settings: `GATEWAY_UPSTREAM` (OpenRouter chat completions),
`GATEWAY_PROVIDER_KEY`, `GATEWAY_CLIENT_KEY`, `GATEWAY_STATE_PATH` (persistent),
`GATEWAY_MAX_REQUESTS` and `GATEWAY_CAP_USD`. Counters include every model HTTP
request; unknown usage retains its reservation and stops further admission.
Only the gateway receives the real key for Hermes model calls. Readiness checks
gateway exhaustion/trip state without caching those changing values. Dependency
health is cached briefly; a mid-run failure still fails closed. Reservations are
conservative operational estimates, not a provider account billing guarantee.

## Live discovery

Set all three explicitly:

```text
DISCOVERY_ENABLED=true
DISCOVERY_PUBLIC_ENABLED=true
DISCOVERY_SEARCH_PROVIDER=openrouter
DISCOVERY_OPENROUTER_KEY=<private OpenRouter key>
```

The separate discovery search adapter uses that backend-only key for metered
OpenRouter/Exa search leads. It sends task text and public catalog names only;
vendor facts come from independently fetched pages, not model claims. The
existing discovery worker was promoted into `app/discovery_worker` and reused;
the existing application validator/storage still handles pending tools.

Choose a task, then **Research more tools**. `/api/research` performs the bounded
search and the directory refreshes. No operator token enters the browser. The
original operator `/api/discover` endpoint stays protected.

Default release-test safeguards: four public research attempts per client/hour,
20 globally/hour, one active finder, bounded pages/time, and a separate persistent
search ledger permitting four provider attempts and $1 in admitted reservations.
These are explicit finite defaults, not a production capacity forecast. Its
budget/key availability is included in discovery status. Review/adjust them
deliberately for a longer demo; do not delete ledger files to hide prior spend.
All application, gateway and discovery state belongs on persistent VM storage.

New tools are **Pending review**, with source links/dates and unknown pricing
where unresolved. They do not automatically become verified winners. Failed or
partial searches preserve browsing and existing recommendations. A free Bing
RSS adapter exists but the live test found poor relevance; OpenRouter/Exa is
the tested discovery configuration.

## Observed evidence and limits

- Real application route with Hermes/MCP/OpenRouter passed bookkeeping and
  missed-call journeys, with validated answers (8.87s / 4.39s).
- This checkpoint's Hermes testing: seven provider requests, $0.029300, including
  a rejected prose response and a timeout before the formatting/timeout fixes.
- Live email-marketing discovery added Keap, SendPulse and tinyEmail. A second
  phone-answering search added four further pending candidates. Catalog24 ->31
  in the isolated test database; this was not a manual catalog edit.
- Discovery search: two provider requests, $0.022283. Combined actual reported
  testing cost: **$0.051583 of the authorized $5**. This is local test accounting,
  not a team account balance.
- Both searches were partial; unsupported/blocked pages remain incomplete.
  The first free-source phone search admitted a hardware false positive; its
  evidence was retained and task/service relevance filtering was added. That
  candidate was not added to the repository's catalog or the repaired test DB.
- Initial three discoveries survived an application restart. The actual App
  component replayed their captured results and showed all three cards with
  Pending review and vendor links; that UI replay made no paid calls.
- Wrong-schema, wrong-server and exhausted-gateway checks through the real
  local route returned unavailable with zero model forwards and browsing200.
  Interrupted MCP was detected in4.1s versus the prior10s timeout. The default
  healthy mock response and real-provider timing are different workloads.

No Azure deployment or Git commit/push occurred. Two real Supabase account
isolation and selected-VM deployment/whole-application hosted checks remain
release work. Concurrency sizing remains W13. Public operation labels do not
grant private authority, but they are not cryptographic proof of which Hermes
session invoked a public read; private MCP operations remain disabled.
