#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
STATE_DB="${AGENTD_STATE_DB:-/tmp/agent-runtime-os/state.db}"
fuser -k 8234/tcp >/dev/null 2>&1 || true
rm -f /tmp/agent-runtime-agentd.sock "$STATE_DB" "$STATE_DB-wal" "$STATE_DB-shm" /tmp/agent-runtime-os/state.db /tmp/agent-runtime-os/state.db-wal /tmp/agent-runtime-os/state.db-shm

export LLM_BACKEND="${LLM_BACKEND:-deepseek}"
if [ -z "${LLM_API_KEY:-}" ] && [ -n "${DEEPSEEK_API_KEY:-}" ]; then
  export LLM_API_KEY="$DEEPSEEK_API_KEY"
fi
python3 -m aruntime.daemon.main >/tmp/agentd_real_demo.log 2>&1 &
AGENTD_PID=$!
export AGENTD_BASE_URL=http://127.0.0.1:8234
cleanup() {
  kill "$AGENTD_PID" >/dev/null 2>&1 || true
  wait "$AGENTD_PID" >/dev/null 2>&1 || true
}
trap cleanup EXIT INT TERM

READY=0
for _ in $(seq 1 80); do
  if ! kill -0 "$AGENTD_PID" >/dev/null 2>&1; then
    cat /tmp/agentd_real_demo.log >&2
    exit 1
  fi
  if python3 - <<'PY' >/dev/null 2>&1
import httpx
raise SystemExit(0 if httpx.get("http://127.0.0.1:8234/metrics", timeout=1, trust_env=False).status_code == 200 else 1)
PY
  then
    READY=1
    break
  fi
  sleep 0.25
done
if [ "$READY" -ne 1 ]; then
  cat /tmp/agentd_real_demo.log >&2
  exit 1
fi

python3 "$ROOT/scripts/preflight.py"
python3 "$ROOT/scripts/run_real_demo.py" "$@"
python3 "$ROOT/scripts/verify_result.py"
