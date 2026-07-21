from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def run(name: str, argv: list[str], required: bool = True) -> bool:
    proc = subprocess.run(argv, cwd=ROOT, text=True, capture_output=True, check=False)
    if proc.returncode == 0:
        print(f"[PASS] {name}")
        if proc.stdout.strip():
            print(proc.stdout.strip())
        return True
    status = "FAIL" if required else "SKIP"
    print(f"[{status}] {name}")
    print((proc.stdout + proc.stderr).strip())
    return not required


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--require-real", action="store_true")
    args = parser.parse_args()

    ok = True
    ok &= run("py_compile acceptance scripts", ["python3", "-m", "py_compile", "scripts/preflight_openeuler.py", "scripts/prepare_e2e_repo.py", "scripts/run_real_direct.py", "scripts/run_real_runtime.py"])
    ok &= run("application tests", ["python3", "-m", "pytest", "testing/unittest/applications", "-q"])
    ok &= run("benchmark smoke test", ["python3", "-m", "pytest", "testing/perf/test_benchmark.py", "-q"])
    ok &= run("preflight", ["python3", "scripts/preflight_openeuler.py"] + (["--require-real"] if args.require_real else []), required=args.require_real)
    ok &= run("Direct real E2E", ["python3", "scripts/run_real_direct.py"] + (["--require-real"] if args.require_real else []), required=args.require_real)
    ok &= run("Runtime real E2E", ["python3", "scripts/run_real_runtime.py"] + (["--require-real"] if args.require_real else []), required=args.require_real)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
