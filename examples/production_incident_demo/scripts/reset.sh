#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
rm -rf "$ROOT/output"
rm -rf "$ROOT/target_repo"
cp -a "$ROOT/target_repo_template" "$ROOT/target_repo"
mkdir -p "$ROOT/output"
python3 - <<'PY'
from pathlib import Path
root = Path("examples/production_incident_demo")
(root / "output").mkdir(exist_ok=True)
PY
