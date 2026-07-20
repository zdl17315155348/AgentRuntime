async function loadBenchmarks() {
  const list = await apiGet("/demo/benchmarks");
  document.getElementById("benchmarks").innerHTML = `<table class="table"><thead><tr><th>Benchmark</th></tr></thead><tbody>${
    (list.benchmarks || []).map(name => `<tr><td>${escapeHtml(name)}</td></tr>`).join("")
  }</tbody></table>`;
  if (list.benchmarks.length) {
    const data = await apiGet(`/demo/benchmarks/${list.benchmarks[0]}`);
    const report = data.report || {};
    renderMetrics("summary", [
      {label: "Rows", value: report.rows || 0},
      {label: "Measured", value: report.measured_rows || 0},
      {label: "Data Kind", value: report.data_kind || "unknown"},
      {label: "Claims Allowed", value: report.performance_claim_allowed === false ? "no" : "yes"},
    ]);
  } else {
    renderJson("summary", {note: "no benchmark output yet"});
  }
}
loadBenchmarks();
