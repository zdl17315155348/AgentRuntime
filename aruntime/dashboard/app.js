let timer = null;

async function loadRun() {
  const runId = document.getElementById("runId").value.trim();
  if (!runId) return;
  const summary = await fetch(`/runs/${encodeURIComponent(runId)}/summary`).then(r => r.json());
  const events = await fetch(`/runs/${encodeURIComponent(runId)}/events?after_id=0`).then(r => r.json());
  document.getElementById("summary").textContent = `${summary.root_task_id} | ${summary.status} | tasks ${summary.tasks.total}`;
  document.getElementById("tasks").textContent = JSON.stringify(summary.tasks, null, 2);
  document.getElementById("agents").textContent = JSON.stringify(summary.agents, null, 2);
  document.getElementById("attempts").textContent = JSON.stringify(summary.attempts, null, 2);
  document.getElementById("artifacts").textContent = JSON.stringify(summary.artifacts, null, 2);
  document.getElementById("events").textContent = JSON.stringify(events.events, null, 2);
}

document.getElementById("load").addEventListener("click", () => {
  if (timer) clearInterval(timer);
  loadRun();
  timer = setInterval(loadRun, 2000);
});
