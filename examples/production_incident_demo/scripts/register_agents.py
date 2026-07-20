from __future__ import annotations

import os
from pathlib import Path

import httpx
import yaml


ROOT = Path(__file__).resolve().parents[1]
BASE_URL = os.getenv("AGENTD_BASE_URL", "http://127.0.0.1:8234")


def main() -> int:
    agents = yaml.safe_load((ROOT / "agents.yaml").read_text(encoding="utf-8"))["agents"]
    with httpx.Client(base_url=BASE_URL, timeout=30, trust_env=False) as client:
        for item in agents:
            payload = {
                "agent_name": item["name"],
                "role": item.get("role", item["name"]),
                "system_prompt": item.get("system_prompt", ""),
                "capability": item.get("capability", {}),
                "backend": item.get("backend", {"type": "legacy_llm"}),
            }
            response = client.post("/agents", json=payload)
            if response.status_code == 400 and "已存在" in response.text:
                continue
            response.raise_for_status()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
