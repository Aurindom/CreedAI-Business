#!/usr/bin/env bash
# Run Penny's Hermes setup on a Mac: model gateway and public MCP server (Python) plus Hermes (Docker).
#   backend/scripts/hermes-local.sh start | stop | status
# Needs: Docker Desktop running, `pip install -r backend/requirements-mcp.txt`, "127.0.0.1 penny-mcp.local" in
# /etc/hosts, and backend/.env plus backend/.env.hermes (private settings, never committed).
# Then start the backend with both files loaded (the start command prints how).
set -euo pipefail

BACKEND="$(cd "$(dirname "$0")/.." && pwd)"
STATE="$HOME/penny-hermes"
PYTHON="${PENNY_PYTHON:-$HOME/Documents/sandbox/venv/bin/python}"
IMAGE="nousresearch/hermes-agent:v0.23.0"
CONTAINER="penny-hermes"
export PATH="$PATH:/usr/local/bin:/Applications/Docker.app/Contents/Resources/bin"

load_settings() {
  [ -f "$BACKEND/.env" ] && [ -f "$BACKEND/.env.hermes" ] || { echo "Missing backend/.env or backend/.env.hermes"; exit 1; }
  set -a; source "$BACKEND/.env"; source "$BACKEND/.env.hermes"; set +a
}

wait_for_port() {  # name port seconds
  for _ in $(seq 1 "$3"); do
    if (exec 3<>"/dev/tcp/127.0.0.1/$2") 2>/dev/null; then echo "  $1 is up on port $2"; return 0; fi
    sleep 1
  done
  echo "  $1 did not start on port $2. See $STATE/logs/"; return 1
}

start_python() {  # name module port
  if lsof -nP -iTCP:"$3" -sTCP:LISTEN >/dev/null 2>&1; then echo "  $1: port $3 already in use, leaving it"; return; fi
  # exec: the service replaces this subshell, and nothing keeps the terminal's output open after start returns.
  (cd "$BACKEND" && exec nohup "$PYTHON" -m "$2" >"$STATE/logs/$1.log" 2>&1 </dev/null) &
  echo $! >"$STATE/$1.pid"
  wait_for_port "$1" "$3" 20
}

case "${1:-}" in
  start)
    load_settings
    mkdir -p "$STATE/logs"
    docker info >/dev/null 2>&1 || { echo "Docker Desktop is not running. Start it, then try again."; exit 1; }
    echo "Starting the model gateway and MCP server..."
    start_python gateway app.model_gateway "${GATEWAY_PORT:-9999}"
    start_python mcp app.public_mcp "${PUBLIC_MCP_PORT:-8000}"
    echo "Starting Hermes ($IMAGE)..."
    docker rm -f "$CONTAINER" >/dev/null 2>&1 || true
    docker run -d --name "$CONTAINER" \
      -p 127.0.0.1:8642:8642 \
      --add-host penny-mcp.local:host-gateway \
      --env-file "$STATE/hermes.env" \
      -e API_SERVER_ENABLED=true -e API_SERVER_HOST=0.0.0.0 -e HERMES_HOME=/opt/data -e PYTHONDONTWRITEBYTECODE=1 \
      -v "$STATE/hermes:/opt/data" \
      --memory 1g --security-opt no-new-privileges:true \
      "$IMAGE" gateway run >/dev/null
    wait_for_port hermes 8642 90 || { docker logs --tail 30 "$CONTAINER"; exit 1; }
    echo
    echo "Ready. Now restart the backend with both settings files, in its own terminal:"
    echo "  cd $BACKEND && set -a && source .env && source .env.hermes && set +a && uvicorn app.main:app --reload --port 8152"
    ;;
  stop)
    for name in gateway mcp; do
      if [ -f "$STATE/$name.pid" ]; then kill "$(cat "$STATE/$name.pid")" 2>/dev/null || true; rm -f "$STATE/$name.pid"; fi
    done
    docker rm -f "$CONTAINER" >/dev/null 2>&1 || true
    echo "Stopped the gateway, MCP server and Hermes. Restart the backend with only .env to go back to the direct path."
    ;;
  status)
    for pair in "gateway:9999" "mcp:8000" "hermes:8642" "backend:8152"; do
      name="${pair%%:*}"; port="${pair##*:}"
      if (exec 3<>"/dev/tcp/127.0.0.1/$port") 2>/dev/null; then echo "  $name: up ($port)"; else echo "  $name: down ($port)"; fi
    done
    ;;
  *) echo "Usage: $0 start | stop | status"; exit 1 ;;
esac
