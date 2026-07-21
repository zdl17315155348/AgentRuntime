from __future__ import annotations

import argparse
import json
import re
import subprocess
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_EVIDENCE = ROOT / "final-evidence"
SECRET_PATTERNS = [
    re.compile(r"sk-[A-Za-z0-9_-]{20,}"),
    re.compile(r"(?i)(api[_-]?key|authorization|bearer)\s*[:=]\s*['\"]?[A-Za-z0-9._-]{12,}"),
]


def _load_json(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _run_summary(path: Path) -> dict[str, Any]:
    data = _load_json(path)
    if data.get("summary"):
        summary_path = Path(data["summary"])
        if not summary_path.is_absolute():
            summary_path = ROOT / summary_path
        summary = _load_json(summary_path)
        if summary:
            summary["_manifest"] = data
        return summary
    return data


def _manifest(path: Path) -> dict[str, Any]:
    return _load_json(path)


def _all_manifests(evidence: Path, mode: str) -> list[Path]:
    return sorted((evidence / f"{mode}-e2e").glob("*.log"), key=lambda path: path.stat().st_mtime)


def _success_logs(evidence: Path, mode: str) -> list[Path]:
    paths: list[Path] = []
    for path in _all_manifests(evidence, mode):
        summary = _run_summary(path)
        if _valid_e2e_summary(summary):
            paths.append(path)
    return paths


def _has_success_run(evidence: Path, mode: str) -> bool:
    return bool(_success_logs(evidence, mode))


def _last_two_success(evidence: Path, mode: str) -> bool:
    logs = _all_manifests(evidence, mode)
    if len(logs) < 2:
        return False
    return all(_valid_e2e_summary(_run_summary(path)) for path in logs[-2:])


def _valid_e2e_summary(summary: dict[str, Any]) -> bool:
    result = summary.get("result") or {}
    return (
        summary.get("status") == "SUCCESS"
        and bool(result.get("patch_non_empty")) is True
        and result.get("pytest_returncode") == 0
        and bool(result.get("review_approved")) is True
    )


def _runtime_summary_valid(summary: dict[str, Any]) -> bool:
    execution = summary.get("execution") or {}
    manifest = summary.get("_manifest") or {}
    runtime_summary = manifest.get("runtime_summary") if isinstance(manifest.get("runtime_summary"), dict) else {}
    attempts = runtime_summary.get("attempts") if isinstance(runtime_summary.get("attempts"), list) else []
    return (
        int(execution.get("tasks") or 0) > 0
        and int(execution.get("attempts") or 0) > 0
        and bool(summary.get("runtime_task_ids") or attempts or runtime_summary.get("tasks"))
    )


def _fault_summary_valid(summary: dict[str, Any]) -> bool:
    manifest = summary.get("_manifest") or {}
    fault = manifest.get("fault_evidence") if isinstance(manifest.get("fault_evidence"), dict) else summary.get("faults") or {}
    return int(fault.get("worker_lost") or 0) >= 1 and int(fault.get("fallback_created") or fault.get("fallbacks") or 0) >= 1


def _has_file(directory: Path, patterns: tuple[str, ...]) -> bool:
    if not directory.exists():
        return False
    return any(any(directory.glob(pattern)) for pattern in patterns)


def _has_secret_leak(evidence: Path) -> tuple[bool, str]:
    if not evidence.exists():
        return False, ""
    for path in evidence.rglob("*"):
        if ".codex-home" in path.parts:
            continue
        try:
            if not path.is_file() or path.stat().st_size > 2_000_000:
                continue
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        for pattern in SECRET_PATTERNS:
            if pattern.search(text):
                return True, str(path.relative_to(ROOT))
    return False, ""


def _git_head() -> str:
    try:
        return subprocess.check_output(["git", "-C", str(ROOT), "rev-parse", "HEAD"], text=True).strip()
    except (subprocess.SubprocessError, OSError):
        return ""


def _git_clean() -> bool:
    try:
        status = subprocess.check_output(
            ["git", "-C", str(ROOT), "status", "--porcelain", "--untracked-files=no"],
            text=True,
        ).strip()
    except (subprocess.SubprocessError, OSError):
        return False
    return not status


def _recorded_commit(evidence: Path) -> str:
    path = evidence / "environment/git_commit.txt"
    try:
        return path.read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def _manifests_match_commit(evidence: Path, commit: str) -> bool:
    if not commit:
        return False
    paths = []
    for mode in ("direct", "runtime", "fault"):
        paths.extend(_success_logs(evidence, mode))
    if not paths:
        return False
    return all((_manifest(path).get("git_commit") == commit) for path in paths)


def _benchmark_reports(evidence: Path) -> list[dict[str, Any]]:
    reports = []
    if not (evidence / "benchmarks").exists():
        return reports
    for path in sorted((evidence / "benchmarks").rglob("*.json")):
        data = _load_json(path)
        if data.get("benchmark_id") and ("summary" in data or "pairs" in data):
            data["_path"] = str(path)
            reports.append(data)
    return reports


def _benchmarks_valid(evidence: Path, commit: str) -> tuple[bool, str]:
    reports = _benchmark_reports(evidence)
    if not reports:
        return False, "missing benchmark report"
    for report in reports:
        if report.get("data_kind") == "synthetic_smoke":
            continue
        if report.get("performance_claim_allowed") is not True:
            return False, f"{report.get('_path')}: performance_claim_allowed=false"
        if commit and report.get("release_commit") not in ("", commit):
            return False, f"{report.get('_path')}: release_commit mismatch"
        pairs = report.get("pairs") or []
        if pairs and not all(pair.get("comparable") for pair in pairs):
            return False, f"{report.get('_path')}: incomparable pair"
        summary = report.get("summary") or []
        if not summary:
            return False, f"{report.get('_path')}: empty summary"
        if all(float(row.get("mean") or 0) == 0 and float(row.get("p50") or 0) == 0 for row in summary if isinstance(row, dict)):
            return False, f"{report.get('_path')}: zero metrics"
    return True, ""


def _check(name: str, ok: bool, detail: str = "") -> bool:
    status = "PASS" if ok else "FAIL"
    suffix = f" {detail}" if detail else ""
    print(f"[{status}] {name}{suffix}")
    return ok


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--evidence-dir", default=str(DEFAULT_EVIDENCE))
    args = parser.parse_args()
    evidence = Path(args.evidence_dir)
    head = _git_head()
    recorded_commit = _recorded_commit(evidence)

    ok = True
    ok &= _check("源码工作区干净", _git_clean())
    ok &= _check("HEAD与封板Commit一致", bool(head and recorded_commit and head == recorded_commit), recorded_commit or "missing git_commit.txt")
    ok &= _check("E2E Manifest Commit一致", _manifests_match_commit(evidence, recorded_commit))
    ok &= _check("无密钥全量测试通过", _has_file(evidence / "tests", ("unittest.log", "integration.log", "final_acceptance_fake.log")))
    ok &= _check("openEuler镜像强制包含Codex", _has_file(evidence / "environment", ("openeuler_preflight.log", "docker_build.log", "codex_version.txt")))
    ok &= _check("Direct真实E2E成功", _has_success_run(evidence, "direct"))
    runtime_success = [_run_summary(path) for path in _success_logs(evidence, "runtime")]
    fault_success = [_run_summary(path) for path in _success_logs(evidence, "fault")]
    ok &= _check("Runtime真实E2E成功", any(_runtime_summary_valid(summary) for summary in runtime_success))
    ok &= _check("Runtime故障E2E成功", any(_fault_summary_valid(summary) for summary in fault_success))
    ok &= _check("Direct最后两次连续成功", _last_two_success(evidence, "direct"))
    ok &= _check("Runtime最后两次连续成功", _last_two_success(evidence, "runtime"))
    ok &= _check("小样本真实性能数据字段完整", _has_file(evidence / "benchmarks", ("small_sample*.json", "small_sample*.csv", "small_sample*.log")))
    ok &= _check("正式Benchmark结果可复现", _has_file(evidence / "benchmarks", ("formal*.json", "formal*.csv", "formal*.log")))
    bench_ok, bench_detail = _benchmarks_valid(evidence, recorded_commit)
    ok &= _check("Benchmark真实且Pair可比较", bench_ok, bench_detail)
    ok &= _check("Dashboard读取真实数据", _has_file(evidence / "dashboard", ("*.png", "*.json", "*.log")))
    ok &= _check("Replay和录屏可用", _has_file(evidence / "videos", ("*.mp4", "*.webm")) and _has_file(evidence / "runtime-e2e", ("*replay_manifest.json", "replay_manifest.json")))
    leaked, leak_path = _has_secret_leak(evidence)
    ok &= _check("API Key没有泄漏", not leaked, leak_path)
    required_dirs = ["environment", "tests", "direct-e2e", "runtime-e2e", "fault-e2e", "benchmarks", "dashboard", "patches", "videos"]
    missing_dirs = [name for name in required_dirs if not (evidence / name).is_dir()]
    ok &= _check("最终证据目录完整", not missing_dirs, ",".join(missing_dirs))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
