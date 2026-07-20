from __future__ import annotations

import math
import statistics


def percentile(values: list[float], pct: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = (len(ordered) - 1) * pct
    lower = math.floor(index)
    upper = math.ceil(index)
    if lower == upper:
        return ordered[int(index)]
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (index - lower)


def summarize(values: list[float]) -> dict[str, float]:
    if not values:
        return {"mean": 0, "stdev": 0, "p50": 0, "p95": 0, "p99": 0, "ci95": 0, "min": 0, "max": 0}
    mean = statistics.mean(values)
    stdev = statistics.stdev(values) if len(values) > 1 else 0.0
    ci95 = 1.96 * stdev / math.sqrt(len(values)) if len(values) > 1 else 0.0
    return {
        "mean": round(mean, 3),
        "stdev": round(stdev, 3),
        "p50": round(percentile(values, 0.50), 3),
        "p95": round(percentile(values, 0.95), 3),
        "p99": round(percentile(values, 0.99), 3),
        "ci95": round(ci95, 3),
        "min": round(min(values), 3),
        "max": round(max(values), 3),
    }
