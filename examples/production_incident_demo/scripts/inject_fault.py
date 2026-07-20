from __future__ import annotations

import os
import sys

import httpx


BASE_URL = os.getenv("AGENTD_BASE_URL", "http://127.0.0.1:8234")


def main() -> int:
    agent = sys.argv[1] if len(sys.argv) > 1 else "coder_a"
    with httpx.Client(base_url=BASE_URL, timeout=10, trust_env=False) as client:
        response = client.post(f"/debug/faults/workers/{agent}/sigkill")
        print(response.text)
        response.raise_for_status()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
