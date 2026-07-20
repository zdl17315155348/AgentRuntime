from __future__ import annotations

import os
import subprocess
from pathlib import Path

from aruntime.core.models import ArtifactReference, WorkspaceSpec
from aruntime.workspace.artifact_store import ArtifactStore, safe_id


class WorkspaceManager:
    def __init__(self, workspace_root: str | None = None, artifact_store: ArtifactStore | None = None):
        self.workspace_root = Path(workspace_root or os.getenv("AGENTD_WORKSPACE_ROOT", "/tmp/agent-runtime-os/workspaces")).resolve()
        self.workspace_root.mkdir(parents=True, exist_ok=True)
        self.artifact_store = artifact_store or ArtifactStore()

    def create_attempt_workspace(
        self,
        source_repo: str,
        task_id: str,
        attempt_id: str,
        base_ref: str,
        read_only: bool,
        root_task_id: str | None = None,
    ) -> WorkspaceSpec:
        repo = Path(source_repo).resolve()
        if not repo.exists():
            raise ValueError(f"source_repo not found: {source_repo}")
        if not (repo / ".git").exists():
            raise ValueError(f"source_repo is not a git repository: {source_repo}")
        base_commit = self._git(repo, "rev-parse", base_ref).strip()
        workspace_id = safe_id(attempt_id)
        workspace_path = (self.workspace_root / safe_id(root_task_id or task_id) / workspace_id).resolve()
        if self.workspace_root not in workspace_path.parents:
            raise ValueError("workspace path escapes workspace root")
        if workspace_path.exists():
            raise ValueError(f"workspace already exists: {workspace_path}")
        workspace_path.parent.mkdir(parents=True, exist_ok=True)
        self._git(repo, "worktree", "add", "--detach", str(workspace_path), base_commit)
        if read_only:
            for path in workspace_path.rglob("*"):
                if path.is_file():
                    path.chmod(0o444)
        return WorkspaceSpec(
            source_repo=str(repo),
            base_ref=base_ref,
            base_commit=base_commit,
            workspace_id=workspace_id,
            workspace_path=str(workspace_path),
            read_only=read_only,
        )

    def create_patch_artifact(
        self,
        workspace: WorkspaceSpec,
        task_id: str,
        attempt_id: str,
        root_task_id: str | None = None,
        exclude_globs: list[str] | None = None,
    ) -> ArtifactReference | None:
        if not workspace.workspace_path or not workspace.base_commit:
            return None
        worktree = Path(workspace.workspace_path).resolve()
        untracked = self._git(worktree, "ls-files", "--others", "--exclude-standard")
        ignored = tuple(exclude_globs or ["__pycache__/", ".pytest_cache/"])
        new_files = [line.strip() for line in untracked.splitlines() if line.strip() and not _ignored(line.strip(), ignored)]
        if new_files:
            self._git(worktree, "add", "-N", *new_files)
        diff_args = ["diff", "--binary", workspace.base_commit, "--", ".", ":(exclude)**/__pycache__/**", ":(exclude).pytest_cache/**"]
        patch = self._git(worktree, *diff_args)
        changed = self._git(worktree, "diff", "--name-only", workspace.base_commit, "--", ".", ":(exclude)**/__pycache__/**", ":(exclude).pytest_cache/**")
        changed_files = [line.strip() for line in changed.splitlines() if line.strip()]
        if not patch:
            return None
        return self.artifact_store.write_bytes(
            root_task_id or task_id,
            task_id,
            attempt_id,
            "patch",
            "changes.patch",
            patch.encode("utf-8"),
            metadata={"changed_files": changed_files, "base_commit": workspace.base_commit},
        )

    def cleanup_workspace(self, workspace: WorkspaceSpec, force: bool = False) -> None:
        if not workspace.workspace_path:
            return
        worktree = Path(workspace.workspace_path).resolve()
        if self.workspace_root not in worktree.parents:
            raise ValueError("workspace path escapes workspace root")
        if not worktree.exists():
            return
        args = ["worktree", "remove"]
        if force:
            args.append("--force")
        args.append(str(worktree))
        subprocess.run(["git", "-C", workspace.source_repo, *args], capture_output=True, text=True, check=False)

    def _git(self, cwd: Path, *args: str) -> str:
        proc = subprocess.run(["git", "-C", str(cwd), *args], capture_output=True, text=True, check=False)
        if proc.returncode != 0:
            raise RuntimeError(f"git {' '.join(args)} failed: {proc.stderr or proc.stdout}")
        return proc.stdout


def _ignored(path: str, ignored: tuple[str, ...]) -> bool:
    return any(part in path for part in ignored)
