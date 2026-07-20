from __future__ import annotations

import hashlib
import subprocess

from applications.incident_repair.services.patch_integration import PatchIntegrationService


def _git(cwd, *args):
    proc = subprocess.run(["git", "-C", str(cwd), *args], capture_output=True, text=True, check=False)
    assert proc.returncode == 0, proc.stderr or proc.stdout
    return proc.stdout


def test_patch_integration_applies_patch_and_creates_commit(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init")
    _git(repo, "config", "user.name", "test")
    _git(repo, "config", "user.email", "test@example.local")
    (repo / "app.py").write_text("value = 1\n", encoding="utf-8")
    _git(repo, "add", "app.py")
    _git(repo, "commit", "-m", "base")
    base = _git(repo, "rev-parse", "HEAD").strip()

    work = tmp_path / "work"
    _git(repo, "worktree", "add", "--detach", str(work), base)
    (work / "app.py").write_text("value = 2\n", encoding="utf-8")
    patch_data = _git(work, "diff", "--binary", base).encode("utf-8")
    patch = tmp_path / "change.patch"
    patch.write_bytes(patch_data)

    result = PatchIntegrationService().integrate(
        source_repo=str(repo),
        base_commit=base,
        patch_refs=[
            {
                "task_local_id": "fix",
                "artifact_id": "artifact1",
                "patch_path": str(patch),
                "sha256": hashlib.sha256(patch_data).hexdigest(),
                "changed_files": ["app.py"],
            }
        ],
        run_id="run",
        repair_round=0,
    )

    assert result.status == "SUCCESS"
    assert result.integrated_commit
    assert result.changed_files == ["app.py"]
    assert _git(result.workspace_path, "show", f"{result.integrated_commit}:app.py") == "value = 2\n"
