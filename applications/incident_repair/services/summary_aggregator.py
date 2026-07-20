from __future__ import annotations

from collections import defaultdict
from typing import Any


class RunSummaryAggregator:
    def build(self, config, final_state: dict[str, Any], events: list[dict[str, Any]], execution_records: list[dict[str, Any]], provider_snapshot: dict[str, Any] | None = None) -> dict[str, Any]:
        provider_snapshot = provider_snapshot or {}
        records = execution_records or []
        tasks = len(records)
        attempts = sum(len(record.get("attempt_ids") or []) for record in records)
        queue_wait_ms = sum(float(record.get("queue_wait_ms") or 0) for record in records)
        setup_ms = sum(float(record.get("setup_ms") or 0) for record in records)
        backend_ms = sum(float(record.get("backend_ms") or 0) for record in records)
        cleanup_ms = sum(float(record.get("cleanup_ms") or 0) for record in records)
        total_tokens = sum(int(record.get("total_tokens") or 0) for record in records)
        peak_rss_mb = max([float(record.get("peak_rss_mb") or 0) for record in records] or [0])
        cpu_time_ms = sum(float(record.get("cpu_time_ms") or 0) for record in records)
        graph = {
            "nodes_started": len(records),
            "nodes_completed": sum(1 for record in records if record.get("status") == "SUCCESS"),
            "nodes_failed": sum(1 for record in records if record.get("status") not in ("SUCCESS",)),
            "repair_rounds": int(final_state.get("repair_round", 0)),
            "route_history": _route_history(events),
        }
        execution = {
            "tasks": tasks,
            "attempts": attempts,
            "queue_wait_ms": round(queue_wait_ms, 3),
            "setup_ms": round(setup_ms, 3),
            "backend_ms": round(backend_ms, 3),
            "cleanup_ms": round(cleanup_ms, 3),
            "total_tokens": total_tokens,
        }
        faults = {
            "worker_lost": int(provider_snapshot.get("worker_lost") or 0),
            "fallbacks": int(provider_snapshot.get("fallbacks") or 0),
            "retries": int(provider_snapshot.get("retries") or 0),
            "lease_reclaimed": int(provider_snapshot.get("lease_reclaimed") or 0),
            "recovery_ms": float(provider_snapshot.get("recovery_ms") or 0),
        }
        resources = {
            "peak_rss_mb": round(peak_rss_mb, 3),
            "cpu_time_ms": round(cpu_time_ms, 3),
            "oom_count": int(provider_snapshot.get("oom_count") or 0),
        }
        context = {
            "recovery_hits": int(provider_snapshot.get("recovery_hits") or 0),
            "shared_context_hits": int(provider_snapshot.get("shared_context_hits") or 0),
            "repeat_file_reads": int(provider_snapshot.get("repeat_file_reads") or 0),
            "token_saving_ratio": float(provider_snapshot.get("token_saving_ratio") or 0),
        }
        result = {
            "patch_non_empty": bool(final_state.get("patch_refs")),
            "changed_files": len((final_state.get("integration_result") or {}).get("changed_files") or []),
            "pytest_returncode": (final_state.get("test_summary") or {}).get("returncode"),
            "tests_passed": int((final_state.get("test_summary") or {}).get("passed") or 0),
            "tests_failed": int((final_state.get("test_summary") or {}).get("failed") or 0),
            "review_approved": bool((final_state.get("review_summary") or {}).get("approved")),
        }
        return {
            "run_id": config.run_id,
            "execution_mode": config.execution_mode.value,
            "status": final_state.get("workflow_status") or "UNKNOWN",
            "graph": graph,
            "execution": execution,
            "faults": faults,
            "resources": resources,
            "context": context,
            "result": result,
        }


def _route_history(events: list[dict[str, Any]]) -> list[str]:
    history: list[str] = []
    for event in events:
        name = str(event.get("name") or "")
        if name in {"graph.run.started", "graph.run.completed", "graph.run.failed"}:
            history.append(name)
    return history
