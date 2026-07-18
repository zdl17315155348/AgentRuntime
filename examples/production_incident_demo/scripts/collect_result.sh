#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
python3 - <<'PY'
import json
from pathlib import Path
out = Path("examples/production_incident_demo/output/latest")
metrics = json.loads((out / "metrics.json").read_text())
print(json.dumps(metrics, ensure_ascii=False, indent=2))
PY
