#!/usr/bin/env bash
# Linux host with Docker Compose v2. No production compose or database is used.
set -euo pipefail
repo_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
command -v docker >/dev/null || { printf '%s\n' 'Docker is required on the demo host.' >&2; exit 1; }
docker compose version >/dev/null
export DEMO_PORT="${DEMO_PORT:-32132}"
export DEMO_BIND_ADDRESS="${DEMO_BIND_ADDRESS:-127.0.0.1}"
if [[ ! "$DEMO_PORT" =~ ^[0-9]{4,5}$ ]] || (( 10#$DEMO_PORT < 1024 || 10#$DEMO_PORT > 65535 )); then
  printf '%s\n' 'DEMO_PORT must be between 1024 and 65535.' >&2; exit 1
fi
case "$DEMO_PORT" in
  32130|32131|32123|5432|55432) printf '%s\n' 'Choose a port separate from existing API, frontend, pgAdmin and database ports.' >&2; exit 1 ;;
esac
case "$DEMO_BIND_ADDRESS" in
  127.0.0.1|0.0.0.0) ;;
  *) printf '%s\n' 'DEMO_BIND_ADDRESS must be 127.0.0.1 or 0.0.0.0.' >&2; exit 1 ;;
esac
export DEMO_COMMIT_SHA="${DEMO_COMMIT_SHA:-$(git -C "$repo_root" rev-parse --short HEAD)}"
demo_dir="$repo_root/.local-demo/isolated-compose"
mkdir -p "$demo_dir"
password_file="$demo_dir/db-password"
if [[ ! -e "$password_file" ]]; then
  (umask 077; set -o noclobber; od -An -N32 -tx1 /dev/urandom | tr -d ' \n' > "$password_file")
fi
export DEMO_DB_PASSWORD="$(cat "$password_file")"
if [[ ! "$DEMO_DB_PASSWORD" =~ ^[0-9a-f]{64}$ ]]; then
  printf '%s\n' 'Invalid saved demo password; existing database was not changed.' >&2; exit 1
fi
compose=(docker compose --project-name cctv-dashboard-demo --env-file /dev/null -f "$repo_root/infra/docker-compose.demo.yaml")
"${compose[@]}" config --quiet
"${compose[@]}" up -d --build --wait --wait-timeout 120
ready=false
for ((attempt=0; attempt<15; attempt++)); do
  if "${compose[@]}" exec -T backend python -c '
import json, os, urllib.request
def get(path):
    with urllib.request.urlopen("http://127.0.0.1:8000" + path, timeout=3) as response:
        return json.load(response)
h = get("/health")
assert h["commit"] == os.environ["APP_COMMIT_SHA"]
assert h["algorithms"]["baseline"]["risk_analysis"] is True
assert get("/health/db")["db"] == "connected"
paths = get("/openapi.json")["paths"]
assert all(p in paths for p in ("/dashboard/cameras", "/edge/heartbeat", "/alerts", "/alerts/{alert_id}/ack"))
' >/dev/null 2>&1; then ready=true; break; fi
  sleep 2
done
if [[ "$ready" != true ]]; then
  printf '%s\n' 'Demo health/API verification failed. Inspect the dedicated demo containers; production was not changed.' >&2
  exit 1
fi
printf 'Demo verified: commit=%s, session=classroom-1014-s10-t1-v91, basic/baseline\n' "$DEMO_COMMIT_SHA"
printf 'Listener: %s:%s (external reachability is not verified)\n' "$DEMO_BIND_ADDRESS" "$DEMO_PORT"
printf '%s\n' 'Register map and calibration in this separate DB before edge replay. Keep the saved password for restarts.'
