from __future__ import annotations

import json
import platform
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any


class RunStore:
    def __init__(self, root: str | Path = "run-data/live"):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def run_dir(self, run_id: str) -> Path:
        path = self.root / run_id
        path.mkdir(parents=True, exist_ok=True)
        (path / "artifacts").mkdir(exist_ok=True)
        return path

    def write_json(self, run_id: str, name: str, data: dict[str, Any]) -> Path:
        path = self.run_dir(run_id) / name
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        return path

    def write_environment(self, run_id: str, source_repo: str = ".") -> Path:
        git_commit = ""
        try:
            commit = subprocess.run(["git", "-C", source_repo, "rev-parse", "HEAD"], capture_output=True, text=True, check=False, timeout=5)
            git_commit = commit.stdout.strip() if commit.returncode == 0 else ""
        except (subprocess.SubprocessError, OSError):
            git_commit = ""
        codex_version = ""
        if shutil.which("codex"):
            try:
                codex = subprocess.run(["codex", "--version"], capture_output=True, text=True, check=False, timeout=5)
                codex_version = codex.stdout.strip() if codex.returncode == 0 else ""
            except (subprocess.SubprocessError, OSError):
                codex_version = ""
        return self.write_json(
            run_id,
            "environment.json",
            {
                "python": platform.python_version(),
                "platform": platform.platform(),
                "git_commit": git_commit,
                "codex_version": codex_version,
                "captured_at": time.time(),
            },
        )

    def write_replay_manifest(self, run_id: str) -> Path:
        return self.write_json(
            run_id,
            "replay_manifest.json",
            {
                "run_id": run_id,
                "source": "recorded",
                "recorded_at": time.time(),
                "events_file": "unified_events.jsonl",
                "speed": 1.0,
            },
        )

    def load_events(self, run_id: str) -> list[dict[str, Any]]:
        path = self.run_dir(run_id) / "unified_events.jsonl"
        if not path.exists():
            return []
        events: list[dict[str, Any]] = []
        for line in path.read_text(encoding="utf-8").splitlines():
            try:
                events.append(json.loads(line))
            except json.JSONDecodeError:
                continue
        return events

    def list_runs(self) -> list[dict[str, Any]]:
        runs = []
        for path in sorted(self.root.iterdir()) if self.root.exists() else []:
            if not path.is_dir():
                continue
            summary = path / "summary.json"
            runs.append(json.loads(summary.read_text(encoding="utf-8")) if summary.exists() else {"run_id": path.name})
        return runs
