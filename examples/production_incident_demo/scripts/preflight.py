from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import httpx


ROOT = Path(__file__).resolve().parents[1]
TARGET = Path(os.getenv("DEMO_TARGET_REPO", ROOT / "target_repo")).resolve()
BASE_URL = os.getenv("AGENTD_BASE_URL", "http://127.0.0.1:8234")


def check(name: str, ok: bool, detail: str = "") -> None:
    print(f"{name}: {'OK' if ok else 'FAIL'} {detail}".strip())
    if not ok:
        raise SystemExit(1)


def run(*argv: str) -> subprocess.CompletedProcess:
    return subprocess.run(list(argv), capture_output=True, text=True, check=False)


def main() -> int:
    release = Path("/etc/openEuler-release")
    check("openEuler", release.exists(), release.read_text(encoding="utf-8", errors="replace").strip() if release.exists() else "")
    check("git", shutil.which("git") is not None, run("git", "--version").stdout.strip())
    codex = shutil.which("codex")
    if codex:
        check("codex", run("codex", "--version").returncode == 0, run("codex", "--version").stdout.strip())
    else:
        check("codex", bool(os.getenv("ALLOW_MISSING_CODEX")), "missing")
    check("OPENAI_API_KEY", bool(os.getenv("OPENAI_API_KEY") or os.getenv("CODEX_API_KEY")), "env only")
    check("DEEPSEEK_API_KEY", bool(os.getenv("DEEPSEEK_API_KEY") or os.getenv("LLM_API_KEY")), "env only")
    check("target git repo", (TARGET / ".git").exists(), str(TARGET))
    with httpx.Client(base_url=BASE_URL, timeout=3, trust_env=False) as client:
        check("agentd", client.get("/metrics").status_code == 200, BASE_URL)
    pytest_ok = run("python3", "-m", "pytest", "--version").returncode == 0
    check("pytest", pytest_ok)
    if codex and os.getenv("SKIP_CODEX_PREFLIGHT") != "1":
        probe = subprocess.run(
            [
                "codex",
                "--sandbox",
                "read-only",
                "--ask-for-approval",
                "never",
                "exec",
                "--ephemeral",
                "--json",
                "--skip-git-repo-check",
                "Return the word OK.",
            ],
            cwd="/tmp",
            capture_output=True,
            text=True,
            timeout=90,
            check=False,
        )
        detail = "exit=0" if probe.returncode == 0 else (probe.stderr or probe.stdout)[-240:].replace("\n", " ")
        check("codex api", probe.returncode == 0, detail)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
