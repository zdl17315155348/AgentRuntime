from __future__ import annotations

from collections import defaultdict

from testing.perf.comparison.schemas import RunMetric
from testing.perf.comparison.statistics import summarize


def summarize_metrics(metrics: list[RunMetric]) -> list[dict]:
    groups: dict[tuple[str, int], list[RunMetric]] = defaultdict(list)
    for metric in metrics:
        if metric.measured:
            groups[(metric.mode, metric.concurrency)].append(metric)
    rows = []
    for (mode, concurrency), items in sorted(groups.items()):
        total = summarize([item.total_ms for item in items])
        rows.append(
            {
                "mode": mode,
                "concurrency": concurrency,
                **total,
                "success_count": sum(1 for item in items if item.success),
                "failure_count": sum(1 for item in items if not item.success),
                "sample_count": len(items),
            }
        )
    return rows
