import subprocess

from aruntime.workspace.manager import WorkspaceManager


def init_repo(path):
    path.mkdir()
    subprocess.run(["git", "init"], cwd=path, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "t"], cwd=path, check=True)
    subprocess.run(["git", "config", "user.email", "t@example.com"], cwd=path, check=True)
    (path / "a.txt").write_text("a\n", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=path, check=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=path, check=True, capture_output=True)


def test_create_attempt_workspace(tmp_path):
    repo = tmp_path / "repo"
    init_repo(repo)
    manager = WorkspaceManager(str(tmp_path / "workspaces"))

    workspace = manager.create_attempt_workspace(str(repo), "task", "task:attempt:1", "HEAD", False)

    assert workspace.workspace_path
    assert "task_attempt_1" in workspace.workspace_path
    assert (tmp_path / "workspaces").resolve() in __import__("pathlib").Path(workspace.workspace_path).resolve().parents
