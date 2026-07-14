from __future__ import annotations

from pathlib import Path


def workspace_root(base: str | Path, task_id: str, attempt_id: str) -> Path:
    return Path(base).expanduser().resolve() / task_id / attempt_id
