from __future__ import annotations

from pathlib import Path

from aruntime.core.models import WorkspaceSpec
from aruntime.workspace.manager import WorkspaceManager


def test_patch_artifact_excludes_codex_private_files(tmp_path):
    source = tmp_path / "repo"
    source.mkdir()
    (source / ".git").mkdir()
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / ".codex-home").mkdir()
    (workspace / ".codex-home" / "config.toml").write_text("secret = true\n", encoding="utf-8")
    (workspace / ".codex-events.jsonl").write_text("event\n", encoding="utf-8")
    (workspace / ".codex-final.json").write_text("done\n", encoding="utf-8")
    (workspace / "app.py").write_text("print('ok')\n", encoding="utf-8")

    manager = WorkspaceManager(workspace_root=str(tmp_path / "workspaces"))
    manager._git = lambda cwd, *args: "app.py\n.codex-home/config.toml\n.codex-events.jsonl\n.codex-final.json\n" if args[:2] == ("ls-files", "--others") else "diff --git a/app.py b/app.py\n"
    artifact = manager.create_patch_artifact(
        WorkspaceSpec(source_repo=str(source), base_ref="HEAD", base_commit="base", workspace_id="w1", workspace_path=str(workspace), read_only=False),
        "task",
        "attempt-1",
        "root",
    )

    assert artifact is not None
    assert ".codex-home" not in Path(artifact.path).read_text(encoding="utf-8")
