#!/usr/bin/env bash
# Explicit, separate demo process. Run with a dedicated PostgreSQL DATABASE_URL.
set -euo pipefail

case "${DATABASE_URL:-}" in
  postgresql://*|postgresql+psycopg2://*) ;;
  *) printf '%s\n' 'Set DATABASE_URL to a dedicated PostgreSQL demo database.' >&2; exit 1 ;;
esac

repo_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
python_bin="${DEMO_PYTHON:-python3}"
demo_port="${DEMO_PORT:-8001}"
demo_bind="${DEMO_BIND_ADDRESS:-127.0.0.1}"
export DASHBOARD_SESSION_ID="${DASHBOARD_SESSION_ID:-classroom-1014-s10-t1-v91}"
export DASHBOARD_CALIBRATION_PROFILE=basic
export DASHBOARD_ALGORITHM=baseline
export ENABLE_RISK_ANALYSIS=true
export APP_COMMIT_SHA="$(git -C "$repo_root" rev-parse --short HEAD)"

cd "$repo_root/backend"
"$python_bin" -c 'import os; from schemas import DetectionBundleIn; s=os.environ["DASHBOARD_SESSION_ID"]; assert 1 <= len(s) <= 128; p=int(os.environ.get("DEMO_PORT", "8001")); assert 1024 <= p <= 65535'
"$python_bin" -m alembic upgrade head
printf 'Demo condition: %s / basic / baseline\n' "$DASHBOARD_SESSION_ID"
printf 'Demo listener: %s:%s\n' "$demo_bind" "$demo_port"
exec "$python_bin" -m uvicorn main:app --host "$demo_bind" --port "$demo_port"
