import pytest

from aruntime.workspace.artifact_store import safe_id
from aruntime.workspace.manager import WorkspaceManager


def test_safe_id_removes_path_separators():
    assert safe_id("../x:y") == ".._x_y"


def test_missing_git_repo_rejected(tmp_path):
    manager = WorkspaceManager(str(tmp_path / "workspaces"))
    plain = tmp_path / "plain"
    plain.mkdir()
    with pytest.raises(ValueError):
        manager.create_attempt_workspace(str(plain), "task", "attempt", "HEAD", False)
