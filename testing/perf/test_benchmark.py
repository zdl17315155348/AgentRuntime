from testing.perf.suite import REPORT_PATH, RESULTS_DIR, FIGURES_DIR, run_suite


def test_benchmark_generates_required_artifacts():
    rows, summary, vllm, cgroup, figures, report = run_suite(seed=42)
    REPORT_PATH.write_text(report, encoding="utf-8")

    assert rows
    assert summary
    assert REPORT_PATH.exists()
    assert (RESULTS_DIR / "raw.csv").exists()
    assert (RESULTS_DIR / "summary.csv").exists()
    assert figures
    assert FIGURES_DIR.exists()
    assert any(row["experiment"] == "调度公平对照" for row in rows)
    assert any(row["experiment"] == "容错故障注入" for row in rows)
    assert any(row["experiment"] == "通信公平对照" for row in rows)
