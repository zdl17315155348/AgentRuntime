from __future__ import annotations

from testing.perf.comparison.schemas import PairedRun


FAIRNESS_FIELDS = ("base_commit", "prompt_hash", "graph_version", "codex_version", "model", "resource_limit")


def check_pair_fairness(direct: dict, runtime: dict) -> PairedRun:
    for field in FAIRNESS_FIELDS:
        if direct.get(field) != runtime.get(field):
            return PairedRun(
                pair_id=str(direct.get("pair_id") or runtime.get("pair_id") or ""),
                direct_run_id=str(direct.get("run_id") or ""),
                runtime_run_id=str(runtime.get("run_id") or ""),
                comparable=False,
                reason=f"mismatch:{field}",
            )
    return PairedRun(
        pair_id=str(direct.get("pair_id") or runtime.get("pair_id") or ""),
        direct_run_id=str(direct.get("run_id") or ""),
        runtime_run_id=str(runtime.get("run_id") or ""),
        comparable=True,
    )
