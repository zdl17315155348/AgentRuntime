#!/bin/bash
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$PROJECT_DIR"

IMAGE_TAG="${IMAGE_TAG:-agent-runtime-os:openeuler}"
BASE_IMAGE="${BASE_IMAGE:-openeuler-24.03-lts:latest}"
CONFIG_PATH="${CONFIG_PATH:-$PROJECT_DIR/configs/runtime.json}"

if ! command -v docker >/dev/null 2>&1; then
  echo "docker 未安装或不可用"
  exit 1
fi

DOCKER="docker"
if docker info >/dev/null 2>&1; then
  DOCKER="docker"
elif sudo docker info >/dev/null 2>&1; then
  DOCKER="sudo docker"
else
  echo "docker 不可用（可能需要 sudo 权限或 docker 服务未启动）"
  exit 1
fi

if ! $DOCKER image inspect "$BASE_IMAGE" >/dev/null 2>&1; then
  echo "未找到 openEuler 基础镜像: $BASE_IMAGE"
  echo "请先下载并导入（示例）："
  echo "  wget https://repo.openeuler.org/openEuler-24.03-LTS/docker_img/x86_64/openEuler-docker.x86_64.tar.xz"
  echo "  xz -d openEuler-docker.x86_64.tar.xz"
  echo "  sudo docker load -i openEuler-docker.x86_64.tar"
  exit 1
fi

$DOCKER build --build-arg BASE_IMAGE="$BASE_IMAGE" -t "$IMAGE_TAG" .

RUN_ARGS=(--rm)
if [ -f "$CONFIG_PATH" ]; then
  RUN_ARGS+=(-v "$CONFIG_PATH:/app/configs/runtime.json:ro" -e RUNTIME_CONFIG=/app/configs/runtime.json)
fi
if [ -n "${SMOKE_LLM_BACKEND:-}" ]; then
  RUN_ARGS+=(-e "SMOKE_LLM_BACKEND=$SMOKE_LLM_BACKEND")
fi
if [ -n "${SMOKE_LLM_API_KEY:-}" ]; then
  RUN_ARGS+=(-e "SMOKE_LLM_API_KEY=$SMOKE_LLM_API_KEY")
fi

$DOCKER run "${RUN_ARGS[@]}" \
  "$IMAGE_TAG" bash -lc '
set -euo pipefail
unset http_proxy https_proxy all_proxy HTTP_PROXY HTTPS_PROXY ALL_PROXY
export NO_PROXY=127.0.0.1,localhost
export no_proxy=127.0.0.1,localhost

python3 -m pip install --no-cache-dir -q pytest

echo "== unit =="
bash scripts/test_unit.sh

echo "== integration =="
LLM_BACKEND=mock LLM_API_KEY="" SCHEDULER_TYPE=dag python3 -m aruntime.daemon.main >/tmp/agentd.log 2>&1 &
AGENTD_PID=$!
cleanup() {
  kill "$AGENTD_PID" >/dev/null 2>&1 || true
  wait "$AGENTD_PID" >/dev/null 2>&1 || true
}
trap cleanup EXIT INT TERM

for _ in $(seq 1 60); do
  if python3 -c "import httpx; r=httpx.get('http://127.0.0.1:8234/metrics', timeout=1); raise SystemExit(0 if r.status_code==200 else 1)" >/dev/null 2>&1; then
    break
  fi
  sleep 0.25
done

if ! python3 -c "import httpx; r=httpx.get('http://127.0.0.1:8234/metrics', timeout=1); raise SystemExit(0 if r.status_code==200 else 1)" >/dev/null 2>&1; then
  echo "agentd 未就绪，日志如下："
  cat /tmp/agentd.log || true
  exit 1
fi

python3 -m pytest testing/unittest/daemon/ -v
cleanup
trap - EXIT INT TERM

echo "== smoke =="
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
'
