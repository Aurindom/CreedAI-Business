#!/usr/bin/env bash
# Invoke only after fetching and reviewing an explicitly approved release SHA.
set -euo pipefail
cd "$(dirname "$0")/../deploy"
release="${1:?Usage: bash scripts/deploy_vm.sh APPROVED_SHA}"
if [[ ! "$release" =~ ^[0-9a-f]{7,40}$ ]] || [[ "$(git rev-parse HEAD)" != "$release"* ]]; then
  echo 'The checkout must match the approved release SHA.' >&2
  exit 1
fi
if [[ -n "$(git status --porcelain --untracked-files=no)" ]]; then
  echo 'Tracked deployment/source changes must be preserved and reviewed first.' >&2
  exit 1
fi
export PENNY_IMAGE="penny-app:$release"
docker compose -f compose.prod.yml config --quiet
# Includes a non-root import/readability gate. A bad image never replaces services.
docker compose -f compose.prod.yml build app render
docker compose -f compose.prod.yml up -d
# An existing Hermes process can retain stale MCP registration when dependencies
# are replaced. Refresh it only after actions and gateway are healthy.
docker compose -f compose.prod.yml restart hermes
docker compose -f compose.prod.yml up -d --force-recreate proxy
docker compose -f compose.prod.yml exec -T app python - <<'PY'
import json, time, urllib.request
for attempt in range(60):
    try:
        with urllib.request.urlopen('http://127.0.0.1:8000/api/chat/ready', timeout=4) as response:
            if json.load(response).get('ready'):
                print('Chat readiness passed; run the bounded hosted canary next.')
                break
    except Exception:
        pass
    time.sleep(1)
else:
    raise SystemExit('Chat readiness failed; inspect safe service diagnostics before retrying.')
PY
# Persist the selected image for later compose commands without changing secrets.
if grep -q '^PENNY_IMAGE=' .env; then
  sed -i "s/^PENNY_IMAGE=.*/PENNY_IMAGE=$PENNY_IMAGE/" .env
else
  printf '\nPENNY_IMAGE=%s\n' "$PENNY_IMAGE" >> .env
fi
chmod 600 .env
docker compose -f compose.prod.yml ps
