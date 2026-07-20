from pathlib import Path

from testing.unittest.workspace.test_worktree_manager import init_repo
from aruntime.workspace.artifact_store import ArtifactStore
from aruntime.workspace.manager import WorkspaceManager


def test_patch_artifact_uses_git_changed_files(tmp_path):
    repo = tmp_path / "repo"
    init_repo(repo)
    store = ArtifactStore(str(tmp_path / "artifacts"))
    manager = WorkspaceManager(str(tmp_path / "workspaces"), store)
    workspace = manager.create_attempt_workspace(str(repo), "task", "attempt-1", "HEAD", False)
    Path(workspace.workspace_path, "a.txt").write_text("b\n", encoding="utf-8")

    artifact = manager.create_patch_artifact(workspace, "task", "attempt-1", "root")

    assert artifact is not None
    assert artifact.sha256
    assert artifact.metadata["changed_files"] == ["a.txt"]


def test_patch_artifact_ignores_pytest_cache_files(tmp_path):
    repo = tmp_path / "repo"
    init_repo(repo)
    store = ArtifactStore(str(tmp_path / "artifacts"))
    manager = WorkspaceManager(str(tmp_path / "workspaces"), store)
    workspace = manager.create_attempt_workspace(str(repo), "task", "attempt-1", "HEAD", False)
    cache_file = Path(workspace.workspace_path, "app", "__pycache__", "module.pyc")
    cache_file.parent.mkdir(parents=True)
    cache_file.write_bytes(b"cache")

    artifact = manager.create_patch_artifact(workspace, "task", "attempt-1", "root")

    assert artifact is None
