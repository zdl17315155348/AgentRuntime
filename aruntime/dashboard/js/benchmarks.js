async function loadBenchmarks() {
  const list = await apiGet("/demo/benchmarks");
  renderJson("benchmarks", list);
  if (list.benchmarks.length) {
    renderJson("summary", await apiGet(`/demo/benchmarks/${list.benchmarks[0]}`));
  } else {
    renderJson("summary", {note: "no benchmark output yet"});
  }
}
loadBenchmarks();
