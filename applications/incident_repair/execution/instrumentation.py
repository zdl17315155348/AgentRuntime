from __future__ import annotations

import time

from applications.incident_repair.execution.base import ExecutionMetrics


class ExecutionTimer:
    def __init__(self):
        self.submit_started_at = time.perf_counter()
        self.execution_started_at = self.submit_started_at
        self.execution_finished_at = self.submit_started_at

    def mark_execution_started(self) -> None:
        self.execution_started_at = time.perf_counter()

    def finish(self, queue_wait_ms: float = 0, setup_ms: float = 0, cleanup_ms: float = 0, **extra: float) -> ExecutionMetrics:
        self.execution_finished_at = time.perf_counter()
        total_ms = (self.execution_finished_at - self.submit_started_at) * 1000
        backend_ms = max((self.execution_finished_at - self.execution_started_at) * 1000 - cleanup_ms, 0)
        return ExecutionMetrics(
            submit_started_at=self.submit_started_at,
            execution_started_at=self.execution_started_at,
            execution_finished_at=self.execution_finished_at,
            queue_wait_ms=round(queue_wait_ms, 3),
            setup_ms=round(setup_ms, 3),
            backend_ms=round(backend_ms, 3),
            cleanup_ms=round(cleanup_ms, 3),
            total_ms=round(total_ms, 3),
            input_tokens=int(extra.get("input_tokens", 0)),
            output_tokens=int(extra.get("output_tokens", 0)),
            total_tokens=int(extra.get("total_tokens", 0)),
            cpu_time_ms=round(extra.get("cpu_time_ms", 0), 3),
            peak_rss_mb=round(extra.get("peak_rss_mb", 0), 3),
            tool_calls=int(extra.get("tool_calls", 0)),
            file_reads=int(extra.get("file_reads", 0)),
            search_calls=int(extra.get("search_calls", 0)),
        )
