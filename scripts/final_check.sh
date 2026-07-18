#!/usr/bin/env bash
set -euo pipefail

python3 -c "from aruntime.daemon.main import app; print(app.title)"
python3 -m pytest testing/unittest -q
python3 -m pytest testing/integration/test_daemon_restart.py -q
fuser -k 8234/tcp >/dev/null 2>&1 || true
rm -f /tmp/agent-runtime-agentd.sock /tmp/agent-runtime-os/state.db /tmp/agent-runtime-os/state.db-wal /tmp/agent-runtime-os/state.db-shm
LLM_BACKEND=mock LLM_API_KEY="" SCHEDULER_TYPE=dag python3 -m aruntime.daemon.main >/tmp/agentd_final_integration.log 2>&1 &
AGENTD_PID=$!
trap 'kill "$AGENTD_PID" >/dev/null 2>&1 || true; wait "$AGENTD_PID" >/dev/null 2>&1 || true' EXIT INT TERM
READY=0
for _ in $(seq 1 60); do
  if ! kill -0 "$AGENTD_PID" >/dev/null 2>&1; then
    cat /tmp/agentd_final_integration.log >&2
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
  cat /tmp/agentd_final_integration.log >&2
  exit 1
fi
python3 -m pytest testing/integration/test_worker_fallback.py -q
kill "$AGENTD_PID" >/dev/null 2>&1 || true
wait "$AGENTD_PID" >/dev/null 2>&1 || true
trap - EXIT INT TERM
bash examples/production_incident_demo/scripts/run_normal.sh
bash examples/production_incident_demo/scripts/run_fault.sh
python3 -m pytest testing/perf/test_benchmark.py -q
