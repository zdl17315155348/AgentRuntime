from __future__ import annotations

from pathlib import Path

from scripts.prepare_e2e_repo import prepare_e2e_repo


def test_prepare_e2e_repo_creates_clean_clone(tmp_path):
    source = Path("examples/production_incident_demo/target_repo")
    result = prepare_e2e_repo(source_repo=source, run_id="test_prepare", work_root=tmp_path)

    prepared = Path(result["prepared_repo"])
    assert prepared.exists()
    assert (prepared / ".git").exists()
    assert result["base_commit"]
    assert result["git_status"] == ""
    assert (prepared / "app" / "main.py").exists()
