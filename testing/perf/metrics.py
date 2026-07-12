from __future__ import annotations

import csv
import math
import statistics
from pathlib import Path
from typing import Iterable


def percentile(values: list[float], p: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = max(min(math.ceil(len(ordered) * p) - 1, len(ordered) - 1), 0)
    return float(ordered[index])


def ci95(values: list[float]) -> float:
    if len(values) < 2:
        return 0.0
    return 1.96 * statistics.stdev(values) / math.sqrt(len(values))


def describe(values: list[float]) -> dict[str, float]:
    if not values:
        return {"mean": 0.0, "stdev": 0.0, "p50": 0.0, "p95": 0.0, "p99": 0.0, "ci95": 0.0}
    return {
        "mean": float(statistics.mean(values)),
        "stdev": float(statistics.stdev(values)) if len(values) > 1 else 0.0,
        "p50": percentile(values, 0.50),
        "p95": percentile(values, 0.95),
        "p99": percentile(values, 0.99),
        "ci95": ci95(values),
    }


def write_csv(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames: list[str] = []
    for row in rows:
        for key in row:
            if key not in fieldnames:
                fieldnames.append(key)
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def _svg_header(width: int, height: int, title: str) -> list[str]:
    return [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
        '<rect width="100%" height="100%" fill="#ffffff"/>',
        f'<text x="{width/2}" y="28" text-anchor="middle" font-size="18" font-family="Arial" fill="#111">{title}</text>',
    ]


def write_bar_chart_svg(path: Path, title: str, labels: list[str], values: list[float], unit: str = "") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    width, height = 900, 420
    margin_left, margin_right, margin_top, margin_bottom = 80, 30, 50, 80
    plot_width = width - margin_left - margin_right
    plot_height = height - margin_top - margin_bottom
    max_value = max(values) if values else 1.0
    max_value = max(max_value, 1e-9)
    bar_width = plot_width / max(len(values) * 1.4, 1.0)
    gap = bar_width * 0.4
    lines = _svg_header(width, height, title)
    lines.append(f'<line x1="{margin_left}" y1="{height - margin_bottom}" x2="{width - margin_right}" y2="{height - margin_bottom}" stroke="#333"/>')
    lines.append(f'<line x1="{margin_left}" y1="{margin_top}" x2="{margin_left}" y2="{height - margin_bottom}" stroke="#333"/>')
    for idx, (label, value) in enumerate(zip(labels, values)):
        bar_height = (value / max_value) * plot_height
        x = margin_left + idx * (bar_width + gap) + gap / 2
        y = height - margin_bottom - bar_height
        lines.append(f'<rect x="{x:.2f}" y="{y:.2f}" width="{bar_width:.2f}" height="{bar_height:.2f}" fill="#4f46e5"/>')
        lines.append(f'<text x="{x + bar_width / 2:.2f}" y="{height - 54}" text-anchor="middle" font-size="11" font-family="Arial" fill="#111">{label}</text>')
        lines.append(f'<text x="{x + bar_width / 2:.2f}" y="{y - 6:.2f}" text-anchor="middle" font-size="11" font-family="Arial" fill="#111">{value:.2f}{unit}</text>')
    if unit:
        lines.append(f'<text x="16" y="{margin_top + 12}" font-size="12" font-family="Arial" fill="#444">unit: {unit}</text>')
    lines.append("</svg>")
    path.write_text("\n".join(lines), encoding="utf-8")


def write_line_chart_svg(
    path: Path,
    title: str,
    x_labels: list[str],
    series: dict[str, list[float]],
    unit: str = "",
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    width, height = 920, 420
    margin_left, margin_right, margin_top, margin_bottom = 80, 120, 50, 80
    plot_width = width - margin_left - margin_right
    plot_height = height - margin_top - margin_bottom
    all_values = [value for values in series.values() for value in values]
    max_value = max(all_values) if all_values else 1.0
    max_value = max(max_value, 1e-9)
    lines = _svg_header(width, height, title)
    lines.append(f'<line x1="{margin_left}" y1="{height - margin_bottom}" x2="{width - margin_right}" y2="{height - margin_bottom}" stroke="#333"/>')
    lines.append(f'<line x1="{margin_left}" y1="{margin_top}" x2="{margin_left}" y2="{height - margin_bottom}" stroke="#333"/>')
    colors = ["#4f46e5", "#0891b2", "#16a34a", "#d97706", "#dc2626", "#7c3aed"]
    x_step = plot_width / max(len(x_labels) - 1, 1)
    for idx, (name, values) in enumerate(series.items()):
        color = colors[idx % len(colors)]
        points = []
        for x_idx, value in enumerate(values):
            x = margin_left + x_idx * x_step
            y = height - margin_bottom - (value / max_value) * plot_height
            points.append(f"{x:.2f},{y:.2f}")
        lines.append(f'<polyline fill="none" stroke="{color}" stroke-width="2" points="{" ".join(points)}"/>')
        if values:
            legend_y = margin_top + 18 + idx * 18
            lines.append(f'<rect x="{width - margin_right + 10}" y="{legend_y - 10}" width="12" height="12" fill="{color}"/>')
            lines.append(f'<text x="{width - margin_right + 28}" y="{legend_y}" font-size="12" font-family="Arial" fill="#111">{name}</text>')
    for idx, label in enumerate(x_labels):
        x = margin_left + idx * x_step
        lines.append(f'<text x="{x:.2f}" y="{height - 54}" text-anchor="middle" font-size="11" font-family="Arial" fill="#111">{label}</text>')
    if unit:
        lines.append(f'<text x="16" y="{margin_top + 12}" font-size="12" font-family="Arial" fill="#444">unit: {unit}</text>')
    lines.append("</svg>")
    path.write_text("\n".join(lines), encoding="utf-8")
