from __future__ import annotations

import json
import os

from scripts.final_board_check import _last_two_success, _valid_e2e_summary


def _write_run(root, name: str, status: str) -> None:
    run_dir = root / "run-data" / name
    run_dir.mkdir(parents=True)
    summary = {
        "status": status,
        "result": {
            "patch_non_empty": status == "SUCCESS",
            "pytest_returncode": 0 if status == "SUCCESS" else 1,
            "review_approved": status == "SUCCESS",
        },
    }
    summary_path = run_dir / "summary.json"
    summary_path.write_text(json.dumps(summary), encoding="utf-8")
    manifest = {
        "status": status,
        "summary": str(summary_path),
        "git_commit": "commit",
    }
    path = root / "final-evidence" / "direct-e2e" / f"{name}.log"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(manifest), encoding="utf-8")
    index = int(name.removeprefix("run"))
    os.utime(path, (index, index))


def test_valid_e2e_summary_requires_patch_test_and_review():
    assert _valid_e2e_summary(
        {
            "status": "SUCCESS",
            "result": {"patch_non_empty": True, "pytest_returncode": 0, "review_approved": True},
        }
    )
    assert not _valid_e2e_summary(
        {
            "status": "SUCCESS",
            "result": {"patch_non_empty": False, "pytest_returncode": 0, "review_approved": True},
        }
    )


def test_last_two_success_uses_time_order(tmp_path, monkeypatch):
    import scripts.final_board_check as check

    monkeypatch.setattr(check, "ROOT", tmp_path)
    _write_run(tmp_path, "run1", "SUCCESS")
    _write_run(tmp_path, "run2", "FAILED")
    _write_run(tmp_path, "run3", "SUCCESS")
    assert not _last_two_success(tmp_path / "final-evidence", "direct")

    _write_run(tmp_path, "run4", "SUCCESS")
    assert _last_two_success(tmp_path / "final-evidence", "direct")
