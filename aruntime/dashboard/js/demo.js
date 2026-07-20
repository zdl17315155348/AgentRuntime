let currentRunId = "";
let lastEventId = 0;

async function startRun(mode) {
  const run = await apiPost("/demo/runs", {execution_mode: mode, task_case: "incident_repair_v1"});
  currentRunId = run.run_id;
  lastEventId = 0;
  document.getElementById("mode").textContent = mode.toUpperCase();
  await refresh();
}

async function refresh() {
  if (!currentRunId) return;
  const summary = await apiGet(`/demo/runs/${currentRunId}`);
  const graph = await apiGet(`/demo/runs/${currentRunId}/graph`);
  const artifacts = await apiGet(`/demo/runs/${currentRunId}/artifacts`);
  const events = await apiGet(`/demo/runs/${currentRunId}/events?after_id=${lastEventId}`);
  if (events.events.length) lastEventId = events.events[events.events.length - 1].event_id;
  renderJson("summary", summary);
  renderJson("graph", graph);
  renderJson("artifacts", artifacts);
  renderJson("events", events);
}

document.getElementById("runtime").onclick = () => startRun("runtime");
document.getElementById("direct").onclick = () => startRun("direct");
document.getElementById("replay").onclick = () => startRun("replay");
document.getElementById("cancel").onclick = async () => {
  if (currentRunId) await apiPost(`/demo/runs/${currentRunId}/cancel`, {});
  await refresh();
};
setInterval(refresh, 1000);
