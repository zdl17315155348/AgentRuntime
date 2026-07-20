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
  renderSummary(summary);
  renderGraph(graph);
  renderArtifacts(artifacts);
  renderEvents(events.events);
}

document.getElementById("runtime").onclick = () => startRun("runtime");
document.getElementById("direct").onclick = () => startRun("direct");
document.getElementById("replay").onclick = () => startRun("replay");
document.getElementById("cancel").onclick = async () => {
  if (currentRunId) await apiPost(`/demo/runs/${currentRunId}/cancel`, {});
  await refresh();
};
setInterval(refresh, 1000);

function renderSummary(summary) {
  renderMetrics("summary", [
    {label: "Execution Mode", value: summary.execution_mode},
    {label: "LangGraph", value: summary.status},
    {label: "Tasks", value: summary.execution?.tasks ?? 0},
    {label: "Attempts", value: summary.execution?.attempts ?? 0},
    {label: "Backend ms", value: summary.execution?.backend_ms ?? 0},
    {label: "Peak RSS MB", value: summary.resources?.peak_rss_mb ?? 0},
    {label: "pytest", value: summary.result?.pytest_returncode ?? "n/a"},
    {label: "Review", value: summary.result?.review_approved ? "approved" : "pending"},
  ]);
}

function renderGraph(state) {
  const status = state.workflow_status || "PENDING";
  const tasks = state.planned_tasks || [];
  const coderCount = tasks.filter(t => t.role === "coder").length || 1;
  document.getElementById("graph").innerHTML = `<div class="flow">
    ${node("Planner", statusFor(state.plan))}
    ${node(`Coder x${coderCount}`, state.patch_refs?.length ? "SUCCESS" : "PENDING")}
    ${node("Integrate", state.integrated_commit ? "SUCCESS" : "PENDING")}
    ${node("Tester", state.test_summary ? (state.test_summary.returncode === 0 ? "SUCCESS" : "FAILED") : "PENDING")}
    ${node("Repair", state.repair_round > 0 ? "SUCCESS" : "PENDING")}
    ${node("Reviewer", state.review_summary ? (state.review_summary.approved ? "SUCCESS" : "FAILED") : "PENDING")}
    ${node("Workflow", status)}
  </div>`;
}

function node(name, status) {
  return `<div class="node"><strong>${escapeHtml(name)}</strong><span class="status ${escapeHtml(status)}">${escapeHtml(status)}</span></div>`;
}

function statusFor(value) {
  return value ? "SUCCESS" : "PENDING";
}

function renderEvents(items) {
  document.getElementById("events").innerHTML = `<div class="timeline">${items.map(event => `
    <div class="event"><strong>${escapeHtml(event.name)}</strong><div>${new Date(event.timestamp * 1000).toLocaleTimeString()} ${escapeHtml(event.layer)}</div></div>
  `).join("") || "No new events"}</div>`;
}

function renderArtifacts(artifacts) {
  document.getElementById("artifacts").innerHTML = `<table class="table"><thead><tr><th>Artifact</th></tr></thead><tbody>${
    (artifacts.artifacts || []).map(item => `<tr><td>${escapeHtml(item)}</td></tr>`).join("")
  }</tbody></table>`;
}
