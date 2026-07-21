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
        return subprocess.run(argv, cwd=cwd, capture_output=True, text=True, timeout=timeout, check=False)
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
    ok &= _check(git is not None, "Git", _run(["git", "--version"]).stdout.strip() if git else "missing")
    bwrap = shutil.which("bwrap")
    ok &= _check(bwrap is not None, "bubblewrap", _run(["bwrap", "--version"]).stdout.strip() if bwrap else "missing", required=args.require_real)
    codex = shutil.which("codex")
    codex_required = args.require_real or os.getenv("ALLOW_MISSING_CODEX") != "1"
    codex_detail = _run(["codex", "--version"]).stdout.strip() if codex else "missing"
    ok &= _check(codex is not None, "Codex", codex_detail, required=codex_required)
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

    if args.require_real and codex:
        probe = _run(
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
            timeout=120,
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
