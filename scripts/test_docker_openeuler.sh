#!/bin/bash
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$PROJECT_DIR"

source "$PROJECT_DIR/scripts/docker_common.sh"

IMAGE_TAG="${IMAGE_TAG:-agent-runtime-os:openeuler}"
CONFIG_PATH="${CONFIG_PATH:-$PROJECT_DIR/configs/runtime.json}"
CODEX_HOME_MOUNT=()
if [ -f "${CODEX_HOME:-$HOME/.codex}/config.toml" ]; then
  CODEX_HOME_MOUNT=(-v "${CODEX_HOME:-$HOME/.codex}/config.toml:/root/.codex/config.toml:ro")
fi

ensure_docker_available

if [ ! -x "$PROJECT_DIR/third_party/codex/codex" ]; then
  echo "未找到 Codex 二进制: $PROJECT_DIR/third_party/codex/codex"
  exit 1
fi

$DOCKER build \
  -f deploy/Dockerfile.openeuler \
  -t "$IMAGE_TAG" \
  .

RUN_ARGS=(--rm)
if [ -n "${OPENAI_API_KEY:-}" ]; then
  RUN_ARGS+=(-e "OPENAI_API_KEY=$OPENAI_API_KEY")
fi
if [ -n "${CODEX_API_KEY:-}" ] || [ -n "${OPENAI_API_KEY:-}" ]; then
  RUN_ARGS+=(-e "CODEX_API_KEY=${CODEX_API_KEY:-$OPENAI_API_KEY}")
fi
if [ -f "$CONFIG_PATH" ]; then
  RUN_ARGS+=(-v "$CONFIG_PATH:/app/configs/runtime.json:ro" -e RUNTIME_CONFIG=/app/configs/runtime.json)
fi
if [ -n "${SMOKE_LLM_BACKEND:-}" ]; then
  RUN_ARGS+=(-e "SMOKE_LLM_BACKEND=$SMOKE_LLM_BACKEND")
fi
if [ -n "${SMOKE_LLM_API_KEY:-}" ]; then
  RUN_ARGS+=(-e "SMOKE_LLM_API_KEY=$SMOKE_LLM_API_KEY")
fi

$DOCKER run \
  "${CODEX_HOME_MOUNT[@]}" \
  "${RUN_ARGS[@]}" \
  "$IMAGE_TAG" bash -lc '
set -euo pipefail
unset http_proxy https_proxy all_proxy HTTP_PROXY HTTPS_PROXY ALL_PROXY
export NO_PROXY=127.0.0.1,localhost
export no_proxy=127.0.0.1,localhost

python3 -m pip install --no-cache-dir -q pytest

wait_agentd_ready() {
python3 - <<PY >/dev/null 2>&1
import httpx
try:
    r = httpx.get("http://127.0.0.1:8234/metrics", timeout=1, trust_env=False)
    raise SystemExit(0 if r.status_code == 200 else 1)
except Exception:
    raise SystemExit(1)
PY
}

echo "== unit =="
bash scripts/test_unit.sh

echo "== integration (no resource_aware) =="
fuser -k 8234/tcp >/dev/null 2>&1 || true
LLM_BACKEND=mock LLM_API_KEY="" SCHEDULER_TYPE=dag python3 -m aruntime.daemon.main >/tmp/agentd.log 2>&1 &
AGENTD_PID=$!
cleanup() {
  kill "$AGENTD_PID" >/dev/null 2>&1 || true
  wait "$AGENTD_PID" >/dev/null 2>&1 || true
}
trap cleanup EXIT INT TERM

for _ in $(seq 1 60); do
  if ! kill -0 "$AGENTD_PID" >/dev/null 2>&1; then
    break
  fi
  if wait_agentd_ready; then
    break
  fi
  sleep 0.25
done

if ! wait_agentd_ready; then
  echo "agentd 未就绪，日志如下："
  if kill -0 "$AGENTD_PID" >/dev/null 2>&1; then
    echo "agentd 进程仍在运行："
    ps -p "$AGENTD_PID" -o pid,cmd || true
    python3 - <<PY || true
import os, httpx
print("http_proxy:", os.getenv("http_proxy"))
print("https_proxy:", os.getenv("https_proxy"))
try:
    r = httpx.get("http://127.0.0.1:8234/metrics", timeout=2, trust_env=False)
    print("status:", r.status_code)
    print("body:", r.text[:200])
except Exception as e:
    print("exc:", repr(e))
PY
  else
    echo "agentd 进程已退出："
    wait "$AGENTD_PID" || true
  fi
  cat /tmp/agentd.log || true
  exit 1
fi

python3 -m pytest testing/unittest/daemon/test_lifecycle.py -v
cleanup
trap - EXIT INT TERM

echo "== integration (resource_aware=true) =="
python3 -m pytest testing/unittest/daemon/test_resource_aware.py -v

echo "== smoke =="
fuser -k 8234/tcp >/dev/null 2>&1 || true
STATE_DB="${AGENTD_STATE_DB:-/tmp/agent-runtime-os/state.db}"
rm -f /tmp/agent-runtime-agentd.sock "$STATE_DB" "$STATE_DB-wal" "$STATE_DB-shm" /tmp/agent-runtime-os/state.db /tmp/agent-runtime-os/state.db-wal /tmp/agent-runtime-os/state.db-shm || true
SMOKE_LLM_BACKEND="${SMOKE_LLM_BACKEND:-}"
SMOKE_LLM_API_KEY="${SMOKE_LLM_API_KEY:-}"
if [ -z "$SMOKE_LLM_API_KEY" ] && [ -f configs/runtime.json ]; then
  SMOKE_LLM_API_KEY="$(python3 -c "import json;print(json.load(open(\"configs/runtime.json\")).get(\"llm\",{}).get(\"api_key\",\"\") )")"
fi
if [ -z "$SMOKE_LLM_BACKEND" ]; then
  SMOKE_LLM_BACKEND=deepseek
fi
if [ -n "$SMOKE_LLM_API_KEY" ]; then
  SMOKE_LLM_BACKEND="$SMOKE_LLM_BACKEND" SMOKE_LLM_API_KEY="$SMOKE_LLM_API_KEY" \
    python3 -m pytest testing/smoke/test_smoke.py -v
else
  echo "跳过 smoke（未提供真实 LLM key）"
fi

echo "== benchmark =="
python3 -m pytest testing/perf/test_benchmark.py -q
'
