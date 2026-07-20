from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SUMMARY = ROOT / "output" / "real" / "summary.json"


def main() -> int:
    data = json.loads(SUMMARY.read_text(encoding="utf-8"))
    artifacts = data.get("artifacts") or []
    assert artifacts, "missing artifacts"
    assert any(item.get("artifact_type") == "patch" for item in artifacts), "missing patch artifact"
    print("verify_result: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
