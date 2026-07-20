from __future__ import annotations

import hashlib
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Literal


@dataclass
class PatchIntegrationResult:
    status: Literal["SUCCESS", "CONFLICT", "FAILED"]
    workspace_path: str
    base_commit: str
    integrated_commit: str | None
    applied_artifact_ids: list[str]
    changed_files: list[str]
    conflict_files: list[str]
    error: str | None


class PatchIntegrationService:
    def integrate(self, source_repo: str, base_commit: str, patch_refs: list[dict], run_id: str, repair_round: int) -> PatchIntegrationResult:
        repo = Path(source_repo).resolve()
        if not repo.exists():
            return PatchIntegrationResult("FAILED", str(repo), base_commit, None, [], [], [], "source repo not found")
        worktree = repo.parent / f".integration-{run_id}-{repair_round}"
        if worktree.exists():
            subprocess.run(["git", "-C", str(repo), "worktree", "remove", "--force", str(worktree)], capture_output=True, text=True, check=False)
            if worktree.exists():
                shutil.rmtree(worktree)
        proc = subprocess.run(["git", "-C", str(repo), "worktree", "add", "--detach", str(worktree), base_commit], capture_output=True, text=True, check=False)
        if proc.returncode != 0:
            return PatchIntegrationResult("FAILED", str(worktree), base_commit, None, [], [], [], proc.stderr or proc.stdout or "worktree add failed")
        applied: list[str] = []
        changed: list[str] = []
        conflict_files: list[str] = []
        try:
            for ref in sorted(patch_refs, key=lambda item: str(item.get("task_local_id") or "")):
                patch_path = Path(str(ref.get("patch_path") or ""))
                sha256 = str(ref.get("sha256") or "")
                if not patch_path.exists():
                    return PatchIntegrationResult("FAILED", str(worktree), base_commit, None, applied, changed, conflict_files, f"missing patch: {patch_path}")
                data = patch_path.read_bytes()
                if hashlib.sha256(data).hexdigest() != sha256:
                    return PatchIntegrationResult("FAILED", str(worktree), base_commit, None, applied, changed, conflict_files, "sha256 mismatch")
                check = subprocess.run(["git", "-C", str(worktree), "apply", "--check", str(patch_path)], capture_output=True, text=True, check=False)
                if check.returncode != 0:
                    conflict_files.append(str(patch_path))
                    return PatchIntegrationResult("CONFLICT", str(worktree), base_commit, None, applied, changed, conflict_files, check.stderr or check.stdout or "apply check failed")
                apply = subprocess.run(["git", "-C", str(worktree), "apply", "--3way", str(patch_path)], capture_output=True, text=True, check=False)
                if apply.returncode != 0:
                    conflict_files.append(str(patch_path))
                    return PatchIntegrationResult("CONFLICT", str(worktree), base_commit, None, applied, changed, conflict_files, apply.stderr or apply.stdout or "apply failed")
                applied.append(str(ref.get("artifact_id") or ""))
            diff_check = subprocess.run(["git", "-C", str(worktree), "diff", "--check"], capture_output=True, text=True, check=False)
            if diff_check.returncode != 0:
                return PatchIntegrationResult("FAILED", str(worktree), base_commit, None, applied, changed, conflict_files, diff_check.stderr or diff_check.stdout or "diff check failed")
            diff = subprocess.run(["git", "-C", str(worktree), "diff", "--name-only"], capture_output=True, text=True, check=False)
            changed = [line.strip() for line in diff.stdout.splitlines() if line.strip()]
            if not changed:
                changed = [str(item) for ref in patch_refs for item in (ref.get("changed_files") or [])]
            subprocess.run(["git", "-C", str(worktree), "add", "-A"], capture_output=True, text=True, check=False)
            commit = subprocess.run(
                ["git", "-C", str(worktree), "-c", "user.name=AgentRuntime", "-c", "user.email=runtime@local", "commit", "-m", "runtime: integrate agent patches"],
                capture_output=True,
                text=True,
                check=False,
            )
            if commit.returncode != 0:
                return PatchIntegrationResult("FAILED", str(worktree), base_commit, None, applied, changed, conflict_files, commit.stderr or commit.stdout or "commit failed")
            head = subprocess.run(["git", "-C", str(worktree), "rev-parse", "HEAD"], capture_output=True, text=True, check=False)
            if head.returncode != 0:
                return PatchIntegrationResult("FAILED", str(worktree), base_commit, None, applied, changed, conflict_files, head.stderr or head.stdout or "rev-parse failed")
            return PatchIntegrationResult("SUCCESS", str(worktree), base_commit, head.stdout.strip(), applied, changed, conflict_files, None)
        except Exception as exc:
            return PatchIntegrationResult("FAILED", str(worktree), base_commit, None, applied, changed, conflict_files, str(exc))
