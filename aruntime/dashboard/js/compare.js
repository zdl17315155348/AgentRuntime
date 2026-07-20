async function loadRuns() {
  const runs = await apiGet("/demo/runs");
  const benchmarks = await apiGet("/demo/benchmarks");
  document.getElementById("runs").innerHTML = `<table class="table"><thead><tr><th>Run</th><th>Mode</th><th>Status</th><th>Duration ms</th></tr></thead><tbody>${
    (runs.runs || []).map(run => `<tr><td>${escapeHtml(run.run_id)}</td><td>${escapeHtml(run.execution_mode || "")}</td><td><span class="status ${escapeHtml(run.status || "PENDING")}">${escapeHtml(run.status || "")}</span></td><td>${escapeHtml(run.duration_ms || 0)}</td></tr>`).join("")
  }</tbody></table>`;
  if (benchmarks.benchmarks.length) {
    const benchmark = await apiGet(`/demo/benchmarks/${benchmarks.benchmarks[0]}`);
    const report = benchmark.report || benchmark.comparison || {};
    renderMetrics("fairness", [
      {label: "Data Kind", value: report.data_kind || "unknown"},
      {label: "Claims Allowed", value: report.performance_claim_allowed === false ? "no" : "yes"},
      {label: "Prompt Hash", value: (report.prompt_hash || "").slice(0, 12)},
      {label: "Pairs", value: (report.pairs || []).length},
    ]);
    document.getElementById("timeline").innerHTML = `<pre>${escapeHtml(benchmark.summary_csv || "No summary")}</pre>`;
  } else {
    renderJson("fairness", {status: "no benchmark pair data"});
    renderJson("timeline", {});
  }
}
loadRuns();
