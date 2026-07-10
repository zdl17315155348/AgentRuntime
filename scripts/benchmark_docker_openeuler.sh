#!/bin/bash
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$PROJECT_DIR"

source "$PROJECT_DIR/scripts/docker_common.sh"

IMAGE_TAG="${IMAGE_TAG:-agent-runtime-os:openeuler}"

ensure_docker_available

$DOCKER build -t "$IMAGE_TAG" .

CID="$($DOCKER create "$IMAGE_TAG" bash -lc '
set -euo pipefail
unset http_proxy https_proxy all_proxy HTTP_PROXY HTTPS_PROXY ALL_PROXY
python3 -m pip install --no-cache-dir -q pytest
python3 -m pytest testing/perf/test_benchmark.py -q
')"

cleanup() {
  $DOCKER rm -f "$CID" >/dev/null 2>&1 || true
}
trap cleanup EXIT INT TERM

$DOCKER start -a "$CID"
$DOCKER cp "$CID:/app/BENCHMARK.md" "$PROJECT_DIR/BENCHMARK.md"

echo "BENCHMARK.md generated"
