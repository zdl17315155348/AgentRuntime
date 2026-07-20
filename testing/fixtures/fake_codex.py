#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path


def main() -> int:
    mode = os.getenv("FAKE_CODEX_MODE", "success")
    if mode == "timeout":
        time.sleep(60)
        return 0
    if mode == "process_crash":
        return 2
    if mode == "invalid_json":
        print("{not-json", flush=True)
    else:
        print(json.dumps({"type": "thread.started", "thread_id": "fake-thread"}), flush=True)
        print(json.dumps({"type": "turn.started"}), flush=True)
        print(json.dumps({"type": "item.started", "item": {"type": "command_execution", "command": ["pytest", "-q"]}}), flush=True)
        print(json.dumps({"type": "turn.completed", "usage": {"input_tokens": 10, "output_tokens": 5}}), flush=True)
    if mode == "file_change":
        Path("fake_change.txt").write_text("changed\n", encoding="utf-8")
    if "--output-last-message" in sys.argv:
        idx = sys.argv.index("--output-last-message")
        Path(sys.argv[idx + 1]).write_text(json.dumps({"ok": mode != "nonzero_exit"}), encoding="utf-8")
    return 1 if mode == "nonzero_exit" else 0


if __name__ == "__main__":
    raise SystemExit(main())
