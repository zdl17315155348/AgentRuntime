#!/usr/bin/env bash
set -euo pipefail

DIR="$(cd "$(dirname "$0")" && pwd)"
AGENTD_ENABLE_FAULT_INJECTION=true bash "$DIR/run_real.sh" --inject-fault "$@"
