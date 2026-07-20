async function loadRuns() {
  const runs = await apiGet("/demo/runs");
  const benchmarks = await apiGet("/demo/benchmarks");
  renderJson("runs", runs);
  if (benchmarks.benchmarks.length) {
    const benchmark = await apiGet(`/demo/benchmarks/${benchmarks.benchmarks[0]}`);
    renderJson("fairness", benchmark.comparison || benchmark);
    renderJson("timeline", benchmark.summary_csv || {});
  } else {
    renderJson("fairness", {status: "no benchmark pair data"});
    renderJson("timeline", {});
  }
}
loadRuns();
