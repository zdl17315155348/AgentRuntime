from __future__ import annotations

from testing.perf.comparison.schemas import PairedRun


FAIRNESS_FIELDS = (
    "base_commit",
    "prompt_hash",
    "graph_version",
    "deepseek_model",
    "codex_model",
    "codex_version",
    "cpu_limit",
    "memory_limit_mb",
    "concurrency",
    "task_description_hash",
    "fault_mode",
    "release_commit",
)


def check_pair_fairness(direct: dict, runtime: dict) -> PairedRun:
    for field in FAIRNESS_FIELDS:
        if direct.get(field) != runtime.get(field):
            return PairedRun(
                pair_id=str(direct.get("pair_id") or runtime.get("pair_id") or ""),
                pair_index=int(direct.get("pair_index") if direct.get("pair_index") is not None else runtime.get("pair_index") or -1),
                direct_run_id=str(direct.get("run_id") or ""),
                runtime_run_id=str(runtime.get("run_id") or ""),
                comparable=False,
                reason=f"mismatch:{field}",
            )
    return PairedRun(
        pair_id=str(direct.get("pair_id") or runtime.get("pair_id") or ""),
        pair_index=int(direct.get("pair_index") if direct.get("pair_index") is not None else runtime.get("pair_index") or -1),
        direct_run_id=str(direct.get("run_id") or ""),
        runtime_run_id=str(runtime.get("run_id") or ""),
        comparable=True,
    )
