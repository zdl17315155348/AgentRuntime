from __future__ import annotations

import subprocess
from pathlib import Path

from pydantic import BaseModel, Field


class IntegrationState(BaseModel):
    root_task_id: str
    source_repo: str
    base_commit: str
    current_commit: str
    applied_artifacts: list[str] = Field(default_factory=list)
    integration_workspace: str | None = None
    status: str = "PENDING"
    error: str = ""


def apply_patch_to_worktree(workspace_path: str, patch_path: str) -> tuple[bool, str]:
    worktree = Path(workspace_path).resolve()
    patch = Path(patch_path).resolve()
    check = subprocess.run(["git", "-C", str(worktree), "apply", "--check", str(patch)], capture_output=True, text=True, check=False)
    if check.returncode != 0:
        return False, check.stderr or check.stdout
    apply = subprocess.run(["git", "-C", str(worktree), "apply", "--3way", str(patch)], capture_output=True, text=True, check=False)
    return apply.returncode == 0, apply.stderr or apply.stdout
