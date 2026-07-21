from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import httpx


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _print(status: str, name: str, detail: str = "") -> None:
    suffix = f" {detail}" if detail else ""
    print(f"[{status}] {name}{suffix}")


def _run(argv: list[str], timeout: int = 15, cwd: str | None = None) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(argv, cwd=cwd, stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=timeout, check=False)
    except subprocess.TimeoutExpired as exc:
        return subprocess.CompletedProcess(argv, 124, stdout=exc.stdout or "", stderr=f"timeout after {timeout}s")


def _check(ok: bool, name: str, detail: str = "", required: bool = True) -> bool:
    if ok:
        _print("PASS", name, detail)
        return True
    if required:
        _print("FAIL", name, detail)
        return False
    _print("SKIP", name, detail)
    return True


def inspect_git_state(repo: Path) -> None:
    safe_git = ["git", "-c", f"safe.directory={repo}"]
    head = _run([*safe_git, "rev-parse", "HEAD"], cwd=str(repo))
    status = _run([*safe_git, "status", "--porcelain"], cwd=str(repo))

    if head.returncode == 0:
        _print("INFO", "Git HEAD", head.stdout.strip()[:12])
    else:
        _print("WARN", "Git HEAD", (head.stderr or head.stdout).strip()[-200:])

    if status.returncode != 0:
        _print("WARN", "Git working tree", (status.stderr or status.stdout).strip()[-200:])
    elif status.stdout.strip():
        _print("WARN", "Git working tree", "uncommitted changes present")
    else:
        _print("PASS", "Git working tree", "clean")


def _codex_config_path() -> Path:
    return Path(os.getenv("CODEX_HOME", str(Path.home() / ".codex"))) / "config.toml"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--require-real", action="store_true", help="require DeepSeek/Codex credentials and live auth probes")
    parser.add_argument("--agentd-url", default=os.getenv("AGENTD_BASE_URL", "http://127.0.0.1:8234"))
    args = parser.parse_args()

    ok = True
    release = Path("/etc/openEuler-release")
    ok &= _check(release.exists(), "openEuler", release.read_text(encoding="utf-8", errors="replace").strip() if release.exists() else "not openEuler")
    ok &= _check(sys.version_info >= (3, 10), "Python", sys.version.split()[0])
    git = shutil.which("git")
    git_detail = "installed"
    if git and os.getenv("AGENTD_PREFLIGHT_GIT_VERSION") == "1":
        git_detail = _run(["git", "--version"]).stdout.strip()
    ok &= _check(git is not None, "Git", git_detail if git else "missing")
    if git:
        inspect_git_state(ROOT)
    bwrap = shutil.which("bwrap")
    if bwrap:
        bwrap_version = _run(["bwrap", "--version"]).stdout.strip()
        bwrap_probe = _run(["bwrap", "--ro-bind", "/", "/", "true"])
        bwrap_ok = bwrap_probe.returncode == 0
        bwrap_detail = bwrap_version if bwrap_ok else (bwrap_probe.stderr or bwrap_probe.stdout).strip()
    else:
        bwrap_ok = False
        bwrap_detail = "missing"
    ok &= _check(bwrap_ok, "bubblewrap namespace", bwrap_detail, required=args.require_real)
    codex = shutil.which("codex")
    codex_required = args.require_real or os.getenv("ALLOW_MISSING_CODEX") != "1"
    codex_detail = _run(["codex", "--version"]).stdout.strip() if codex else "missing"
    ok &= _check(codex is not None, "Codex", codex_detail, required=codex_required)
    codex_config = _codex_config_path()
    ok &= _check(
        codex_config.exists(),
        "Codex config",
        str(codex_config) if codex_config.exists() else f"missing {codex_config}; mount host CODEX_HOME config.toml",
        required=args.require_real,
    )
    ok &= _check((ROOT / "examples/production_incident_demo/target_repo").exists(), "target repo", "examples/production_incident_demo/target_repo")
    ok &= _check((ROOT / ".git").exists(), "Git worktree", str(ROOT))
    ok &= _check(_run(["python3", "-m", "pytest", "--version"]).returncode == 0, "pytest")

    for env_name, default, label in (
        ("AGENTD_WORKSPACE_ROOT", str(ROOT / "run-data/workspaces"), "Workspace write"),
        ("AGENTD_ARTIFACT_ROOT", str(ROOT / "run-data/artifacts"), "Artifact write"),
    ):
        path = Path(os.getenv(env_name, default))
        try:
            path.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(dir=path, delete=True) as probe:
                probe.write(b"ok")
            write_ok = True
            detail = str(path)
        except Exception as exc:
            write_ok = False
            detail = str(exc)
        ok &= _check(write_ok, label, detail)

    try:
        resp = httpx.get(f"{args.agentd_url}/metrics", timeout=2, trust_env=False)
        agentd_ok = resp.status_code == 200
    except Exception:
        agentd_ok = False
    ok &= _check(agentd_ok, "AgentRuntime", args.agentd_url, required=args.require_real)

    dashboard_ok = False
    try:
        resp = httpx.get(f"{args.agentd_url}/dashboard/demo.html", timeout=2, trust_env=False)
        dashboard_ok = resp.status_code == 200
    except Exception:
        dashboard_ok = False
    ok &= _check(dashboard_ok, "Dashboard routes", "/dashboard/demo.html", required=args.require_real)

    llm_key = os.getenv("DEEPSEEK_API_KEY") or os.getenv("LLM_API_KEY")
    codex_key = os.getenv("CODEX_API_KEY") or os.getenv("OPENAI_API_KEY")
    ok &= _check(bool(llm_key), "DeepSeek key", "env only", required=args.require_real)
    ok &= _check(bool(codex_key), "Codex key", "env only", required=args.require_real)

    cgroup_v2 = Path("/sys/fs/cgroup/cgroup.controllers").exists()
    ok &= _check(cgroup_v2, "cgroup v2", required=False)

    if args.require_real and codex and codex_config.exists():
        codex_auth_timeout = int(os.getenv("AGENTD_PREFLIGHT_CODEX_AUTH_TIMEOUT_S", "300"))
        probe = _run(
            [
                "codex",
                "--ask-for-approval",
                "never",
                "exec",
                "--sandbox",
                "read-only",
                "--ephemeral",
                "--json",
                "--skip-git-repo-check",
                "Return the word OK.",
            ],
            timeout=codex_auth_timeout,
            cwd="/tmp",
        )
        detail = "exit=0" if probe.returncode == 0 else (probe.stderr or probe.stdout)[-200:].replace("\n", " ")
        ok &= _check(probe.returncode == 0, "Codex auth", detail)

    if args.require_real and llm_key:
        try:
            from aruntime.llm.gateway import LLMGateway

            response = LLMGateway(backend="deepseek").chat_with_stats("Return only OK.", "Return the word OK.")
            deepseek_ok = bool(response.output)
            detail = f"tokens={response.total_tokens}"
        except Exception as exc:
            deepseek_ok = False
            detail = str(exc)[-200:]
        ok &= _check(deepseek_ok, "DeepSeek connectivity", detail)

    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
