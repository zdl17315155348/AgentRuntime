from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path
from uuid import uuid4


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SOURCE = ROOT / "examples/production_incident_demo/target_repo"


def _run(argv: list[str], cwd: Path | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(argv, cwd=str(cwd) if cwd else None, capture_output=True, text=True, check=False)


def _require_ok(proc: subprocess.CompletedProcess, action: str) -> None:
    if proc.returncode != 0:
        raise RuntimeError(f"{action} failed: {proc.stderr or proc.stdout}")


def _is_git_repo(path: Path) -> bool:
    return _run(["git", "-C", str(path), "rev-parse", "--show-toplevel"]).returncode == 0 and (path / ".git").exists()


def _git(repo: Path, *args: str) -> str:
    proc = _run(["git", "-C", str(repo), *args])
    _require_ok(proc, f"git {' '.join(args)}")
    return proc.stdout.strip()


def _copy_seed_source(source_repo: Path, seed_repo: Path) -> None:
    template = source_repo.parent / "target_repo_template"
    source = template if template.exists() else source_repo
    shutil.copytree(
        source,
        seed_repo,
        ignore=shutil.ignore_patterns("__pycache__", ".pytest_cache", ".git", ".codex-home"),
    )
    _require_ok(_run(["git", "init"], cwd=seed_repo), "git init seed repo")
    _require_ok(_run(["git", "config", "user.name", "AgentRuntime"], cwd=seed_repo), "git config user.name")
    _require_ok(_run(["git", "config", "user.email", "runtime@local"], cwd=seed_repo), "git config user.email")
    _require_ok(_run(["git", "add", "-A"], cwd=seed_repo), "git add seed repo")
    _require_ok(_run(["git", "commit", "-m", "demo: base incident repo"], cwd=seed_repo), "git commit seed repo")


def prepare_e2e_repo(
    source_repo: Path = DEFAULT_SOURCE,
    base_commit: str | None = None,
    run_id: str | None = None,
    work_root: Path | None = None,
) -> dict[str, str]:
    source_repo = source_repo.resolve()
    run_id = run_id or f"e2e_repo_{uuid4().hex[:12]}"
    work_root = (work_root or ROOT / "run-data/e2e-repos").resolve()
    run_root = work_root / run_id
    seed_repo = run_root / "seed"
    clone_repo = run_root / "repo"
    if run_root.exists():
        shutil.rmtree(run_root)
    run_root.mkdir(parents=True, exist_ok=True)

    if _is_git_repo(source_repo):
        seed_repo = source_repo
        demo_base_commit = base_commit or _git(source_repo, "rev-parse", "HEAD")
    else:
        _copy_seed_source(source_repo, seed_repo)
        demo_base_commit = base_commit or _git(seed_repo, "rev-parse", "HEAD")

    _require_ok(_run(["git", "clone", "--no-local", str(seed_repo), str(clone_repo)]), "git clone e2e repo")
    _require_ok(_run(["git", "checkout", demo_base_commit], cwd=clone_repo), "git checkout e2e base")
    git_status = _git(clone_repo, "status", "--porcelain")
    if git_status:
        raise RuntimeError(f"prepared e2e repo is dirty: {git_status}")

    return {
        "source_repo": str(source_repo),
        "prepared_repo": str(clone_repo),
        "base_commit": demo_base_commit,
        "git_status": git_status,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-repo", default=str(DEFAULT_SOURCE))
    parser.add_argument("--base-commit")
    parser.add_argument("--run-id")
    parser.add_argument("--work-root", default=str(ROOT / "run-data/e2e-repos"))
    args = parser.parse_args()

    manifest = prepare_e2e_repo(
        source_repo=Path(args.source_repo),
        base_commit=args.base_commit,
        run_id=args.run_id,
        work_root=Path(args.work_root),
    )
    print(json.dumps(manifest, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
