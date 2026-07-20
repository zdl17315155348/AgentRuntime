#!/usr/bin/env bash
set -euo pipefail

mkdir -p "${AGENTD_WORKSPACE_ROOT:-/runtime/workspaces}" \
  "${AGENTD_ARTIFACT_ROOT:-/runtime/artifacts}" \
  "$(dirname "${AGENTD_STATE_DB:-/runtime/state/state.db}")" \
  "${AGENTD_LOG_DIR:-/runtime/logs}"

if [ "$#" -gt 0 ]; then
  exec "$@"
fi

exec python3 -m uvicorn aruntime.daemon.main:app --host 0.0.0.0 --port 8234 --log-level info
