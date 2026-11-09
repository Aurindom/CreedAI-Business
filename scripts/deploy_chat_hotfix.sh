#!/usr/bin/env bash
# App-only rolling cutover. Existing chat/storage/provider services stay running.
set -euo pipefail
cd "$(dirname "$0")/../deploy"
release="${1:?Usage: bash scripts/deploy_chat_hotfix.sh APPROVED_SHA}"
[[ "$release" =~ ^[0-9a-f]{7,40}$ && "$(git rev-parse HEAD)" == "$release"* ]]
[[ -z "$(git status --porcelain --untracked-files=no)" ]]
exec 9>.chat-hotfix.lock
flock -n 9
export PENNY_IMAGE="penny-app:$release"
compose=(docker compose -f compose.prod.yml)
old_app="$("${compose[@]}" ps -q app)"
[[ -n "$old_app" ]]
stage_dir="$(mktemp -d)"
override="$stage_dir/candidate.yml"
printf 'services:\n  app-candidate:\n    extends:\n      service: app\n' > "$override"
next=(docker compose -f compose.prod.yml -f "$override")
candidate_live=false
cleanup() {
    if [[ "$candidate_live" == true ]]; then
        echo 'Candidate remains live; preserve it until canonical app health is reconciled.' >&2
    else
        "${next[@]}" rm -s -f app-candidate >/dev/null 2>&1 || true
        rm -rf -- "$stage_dir"
    fi
}
trap cleanup EXIT
"${compose[@]}" config --quiet
"${compose[@]}" build app

# Retain previous content-hashed chunks for already-open judge browser tabs.
# This disposable container has no runtime secrets, mounts or running process.
mkdir "$stage_dir/assets"
docker cp "$old_app:/srv/frontend/assets/." "$stage_dir/assets/"
asset_stage="$(docker create "$PENNY_IMAGE")"
docker cp "$stage_dir/assets/." "$asset_stage:/srv/frontend/assets/"
docker commit "$asset_stage" "$PENNY_IMAGE" >/dev/null
docker rm "$asset_stage" >/dev/null

"${next[@]}" up -d --no-deps app-candidate
wait_ready() {
    local service="$1"
    for attempt in $(seq 1 40); do
        if "${next[@]}" exec -T "$service" python -c \
          'import urllib.request,json; assert json.load(urllib.request.urlopen("http://127.0.0.1:8000/api/chat/ready",timeout=4))["ready"]' >/dev/null 2>&1; then
            return 0
        fi
        sleep 1
    done
    return 1
}
wait_ready app-candidate
"${next[@]}" exec -T app-candidate python - <<'PY'
import urllib.request,json
body=json.dumps({'conversation_id':'release-help-check','message':'what businesses can you help me with?'}).encode()
r=urllib.request.Request('http://127.0.0.1:8000/api/chat',data=body,headers={'Content-Type':'application/json'})
text=urllib.request.urlopen(r,timeout=5).read().decode()
assert 'app_help' in text and 'agent_unavailable' not in text
PY
python3 - "$stage_dir/Caddyfile" <<'PY'
from pathlib import Path
import sys
text=Path('Caddyfile').read_text()
assert text.count('reverse_proxy app:8000')==1
Path(sys.argv[1]).write_text(text.replace('reverse_proxy app:8000','reverse_proxy app-candidate:8000'))
PY
"${compose[@]}" exec -T proxy caddy validate --config - --adapter caddyfile < "$stage_dir/Caddyfile"
"${compose[@]}" exec -T proxy caddy reload --config - --adapter caddyfile < "$stage_dir/Caddyfile"
candidate_live=true

# Traffic is on the checked candidate while the canonical app is replaced.
"${compose[@]}" up -d --no-deps app
wait_ready app
"${compose[@]}" exec -T proxy caddy reload --config /etc/caddy/Caddyfile --adapter caddyfile
candidate_live=false
if grep -q '^PENNY_IMAGE=' .env; then
    sed -i "s/^PENNY_IMAGE=.*/PENNY_IMAGE=$PENNY_IMAGE/" .env
else
    printf '\nPENNY_IMAGE=%s\n' "$PENNY_IMAGE" >> .env
fi
chmod 600 .env
# Upgrade the bounded selection schema only after the independent catalog path
# is live. Do not interrupt a reserved provider request to restart its gateway.
gateway_idle=false
for attempt in $(seq 1 30); do
    reserved="$("${compose[@]}" exec -T gateway python -c 'from pathlib import Path; from app.model_gateway import Ledger; print(Ledger(Path("/gw/gateway.db")).status()["by_state"].get("reserved",{}).get("count",0))')"
    if [[ "$reserved" == 0 ]]; then gateway_idle=true; break; fi
    sleep 1
done
if [[ "$gateway_idle" == true ]]; then
    "${compose[@]}" up -d --no-deps gateway
    wait_ready app
else
    echo 'Gateway upgrade deferred: a provider request is active; app remains live.' >&2
fi
# Let in-flight requests drain on the temporary upstream before removing it.
sleep 40
"${compose[@]}" ps
