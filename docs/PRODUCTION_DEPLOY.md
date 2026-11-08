# Production deploy (single Linux VM)

Files: `deploy/Dockerfile`, `deploy/compose.prod.yml`, `deploy/Caddyfile`,
`deploy/settings.env.example`, `deploy/secrets.example/*.env`,
`deploy/hermes-config.yaml.example`. Nothing here creates cloud resources. The VM,
DNS and Supabase settings are done by hand.

Tested: offline `docker compose config`, a local image build and an offline smoke
run (see the release notes for the exact result). Not tested: a real VM, a real
domain with TLS, real Supabase production settings, a paid model call through this
compose file.

## Shape

| Service | Image | Networks | Public |
|---|---|---|---|
| proxy | caddy:2.10.2-alpine | edge (fixed IP 172.30.10.10) | 80, 443 only |
| app | penny-app (this repo) | edge, egress, private | no |
| actions (public MCP) | penny-app | private | no |
| gateway | penny-app | egress, private | no |
| hermes | nousresearch/hermes-agent:v0.23.0 | private | no |
| redis | redis:7.4.12-alpine | private | no |

`private` is an internal Docker network with no route out. Hermes, MCP and Redis
can't reach the internet. Only the gateway (OpenRouter) and the app (Supabase)
have egress. Nothing but the proxy publishes a port.

Same origin: the app serves the built UI from `/srv/frontend` and the API under
`/api`, so the browser only ever talks to `https://PENNY_DOMAIN`. No CORS setup
and no second hostname.

## Pinned in compose (can't be changed through settings.env)
- `CHAT_RUNTIME=hermes`.
- One Uvicorn worker: `--workers 1 --no-proxy-headers`. The in-flight cap, the
  burst limiter and the daily limiter are per process, so a second worker doubles
  every limit. Don't scale the app with workers or replicas.
- `CHAT_MAX_INFLIGHT` defaults to 3. It can be overridden from the shell that runs
  compose (1 to 50). A malformed or out-of-range value falls back to 3, it never
  fails a request. When all slots are busy the user gets a retryable "Penny is
  helping other people right now" message, not the outage card.
- `CHAT_TRUST_PROXY=1` with `CHAT_TRUSTED_PROXY_CIDRS=172.30.10.10/32`, the
  proxy's fixed address. Only that peer's `X-Forwarded-For` is believed. Caddy
  itself trusts no upstream headers, so a client can't spoof its address.
  If you ever put a load balancer or CDN in front of Caddy, add its ranges to
  Caddy's `trusted_proxies` too, or every user shares the balancer's IP bucket.
- Private service URLs: `http://hermes:8642`, `http://actions:8000/mcp`,
  `http://gateway:9999`. `PUBLIC_MCP_ALLOWED_HOST=actions:8000`.
- `GATEWAY_UPSTREAM` is OpenRouter chat completions.

## Persistent mount map (native Linux, not a synced or network folder)

Default root `/srv/penny`, change with `PENNY_DATA`. Secrets default to
`/srv/penny/secrets`, change with `PENNY_SECRETS`.

| Host path | Container | Holds | Back up |
|---|---|---|---|
| state/ | app and actions `/state` | app.db (plans, accounts' rows), chat_spend.db (app ledger) | yes |
| gateway/ | gateway `/gw` | gateway.db (provider ledger, every model call) | yes |
| hermes/ | hermes `/opt/data` | config.yaml, Hermes sessions and memory | yes (config holds secrets) |
| redis/ | redis `/data` | appendonly + dump (signed-in chat history) | yes |
| caddy/data, caddy/config | proxy | TLS certificates and ACME account | optional |
| secrets/ | env_file only | app.env, gateway.env, actions.env, hermes.env, redis.env | keep offline copy |

Setup on the VM, once:
```
sudo mkdir -p /srv/penny/{state,gateway,hermes,redis,caddy/data,caddy/config,secrets,backups}
sudo chown 10001:10001 /srv/penny/state /srv/penny/gateway
sudo chmod 700 /srv/penny/secrets
```
The app, actions and gateway run as uid 10001. Hermes' entrypoint starts as root
and manages its own home. Keep SQLite files on the local disk: no NFS, SMB or
synced folders, because SQLite locking depends on it.

## Secrets (exact names)

Copy `deploy/secrets.example/` into `/srv/penny/secrets/`, fill it, `chmod 600`.

| File | Variables |
|---|---|
| app.env | HERMES_API_KEY, PUBLIC_MCP_TOKEN, MODEL_GATEWAY_KEY, SUPABASE_URL, SUPABASE_PUBLISHABLE_KEY, REDIS_URL |
| gateway.env | GATEWAY_PROVIDER_KEY (the OpenRouter key, only here), GATEWAY_CLIENT_KEY, GATEWAY_FORBIDDEN |
| actions.env | PUBLIC_MCP_TOKEN |
| hermes.env | API_SERVER_KEY |
| redis.env | REDIS_PASSWORD |

Pairs that must match: HERMES_API_KEY = API_SERVER_KEY; PUBLIC_MCP_TOKEN in app
and actions = the Bearer value in Hermes config; MODEL_GATEWAY_KEY =
GATEWAY_CLIENT_KEY = Hermes `model.api_key`; the password inside REDIS_URL =
REDIS_PASSWORD. Use random values of 32+ characters (`openssl rand -hex 32`).
The app needs no OpenRouter key with the Hermes runtime.

Copy `deploy/hermes-config.yaml.example` to `/srv/penny/hermes/config.yaml` and
fill its two secrets. Copy `deploy/settings.env.example` to `deploy/settings.env`
and set the budget numbers (see `docs/PRODUCTION_BUDGET.md`). Both filled files
are ignored by git.

## Start, check, stop
```
cd deploy
export PENNY_DOMAIN=penny.example.com
docker compose -f compose.prod.yml build app
docker compose -f compose.prod.yml up -d
docker compose -f compose.prod.yml ps
curl -fsS https://$PENNY_DOMAIN/api/health
curl -s https://$PENNY_DOMAIN/api/chat/ready
```
- `/api/health` is liveness. Compose uses it for the app health check. Browsing
  works whenever this is up.
- `/api/chat/ready` is readiness for chat: provider (Hermes plus gateway status),
  database and app budget, as booleans only. 503 with `Retry-After: 60` means stop
  sending chat here, not restart. It goes 503 when the app ledger can't fit one
  more reservation, or when the gateway is tripped or exhausted.
- Other services have TCP health checks. Hermes starts last, after the gateway and
  MCP are healthy.

Stop with `docker compose -f compose.prod.yml down`. Never add `-v`, and never
delete the `/srv/penny` folders: they hold the ledgers.

## Backup
Stop writes first, or use SQLite's online backup:
```
TS=$(date +%Y%m%d-%H%M)
mkdir -p /srv/penny/backups/$TS
for f in state/app.db state/chat_spend.db gateway/gateway.db; do
  sqlite3 /srv/penny/$f ".backup /srv/penny/backups/$TS/$(basename $f)"
done
docker compose -f compose.prod.yml exec redis sh -c 'REDISCLI_AUTH="$REDIS_PASSWORD" redis-cli BGSAVE'
tar -C /srv/penny -czf /srv/penny/backups/$TS/files.tgz redis hermes secrets
```
Copy the backup off the VM. It contains secrets, so store it like one.

## Rollback
Tag every build: `PENNY_IMAGE=penny-app:<git-sha>`. To roll back, set
`PENNY_IMAGE` to the previous tag and `docker compose -f compose.prod.yml up -d`.
The ledgers and app.db stay in place. If a release changed the database, restore
the matching backup with the stack stopped. Never roll back a ledger file to make
budget reappear: see `docs/PRODUCTION_BUDGET.md`.

## Still needed before go-live (not decided here)
- Domain and DNS A/AAAA record pointing at the VM, ports 80 and 443 open.
- Supabase production project: URL, publishable key, Site URL and redirect URLs set
  to `https://PENNY_DOMAIN`, email confirmation on.
- SMTP for Supabase auth mail (the built-in sender is rate limited and not for
  production).
- The OpenRouter key for the gateway and the budget numbers in settings.env.
- The VM itself (W13 suggests 2 vCPU / 4 GiB).
