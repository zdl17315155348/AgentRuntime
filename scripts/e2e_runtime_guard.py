from __future__ import annotations

import os


def reject_python_pid1_without_init() -> bool:
    if os.getpid() != 1:
        return False
    if os.getenv("ALLOW_PYTHON_PID1_E2E") == "1":
        return False
    print("[FAIL] Python is PID 1; run the openEuler container with docker --init so Codex/bubblewrap child processes are reaped")
    return True
