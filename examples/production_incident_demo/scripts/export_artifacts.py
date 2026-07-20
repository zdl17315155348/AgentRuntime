from __future__ import annotations

import json
import os
from pathlib import Path

import httpx


ROOT = Path(__file__).resolve().parents[1]
BASE_URL = os.getenv("AGENTD_BASE_URL", "http://127.0.0.1:8234")


def main() -> int:
    summary = json.loads((ROOT / "output" / "real" / "summary.json").read_text(encoding="utf-8"))
    out = ROOT / "output" / "real" / "artifacts"
    out.mkdir(parents=True, exist_ok=True)
    with httpx.Client(base_url=BASE_URL, timeout=30, trust_env=False) as client:
        for artifact in summary.get("artifacts") or []:
            response = client.get(f"/artifacts/{artifact['artifact_id']}")
            response.raise_for_status()
            (out / Path(artifact["path"]).name).write_bytes(response.content)
    print(str(out))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
