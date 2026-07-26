const STORAGE_KEY = "agent-runtime-os.demo.currentRun";
let currentRunId = "";
let lastEventId = 0;
let refreshTimer = null;

function isTerminalStatus(status) {
  return ["SUCCESS", "FAILED", "TIMEOUT", "CANCELLED", "INTERRUPTED"].includes(String(status || "").toUpperCase());
}

function startPolling() {
  if (refreshTimer !== null) clearInterval(refreshTimer);
  refreshTimer = setInterval(refresh, 1000);
}

function stopPollingIfTerminal(summary) {
  if (!isTerminalStatus(summary.status)) return;
  if (["INTERRUPTED", "CANCELLED"].includes(String(summary.status || "").toUpperCase())) clearCurrentRun();
  if (refreshTimer !== null) {
    clearInterval(refreshTimer);
    refreshTimer = null;
  }
}

function saveCurrentRun(mode) {
  localStorage.setItem(STORAGE_KEY, JSON.stringify({run_id: currentRunId, mode}));
  renderRunId();
  const url = new URL(window.location.href);
  url.searchParams.set("run_id", currentRunId);
  url.searchParams.set("mode", mode);
  window.history.replaceState({}, "", url);
}

function clearCurrentRun() {
  localStorage.removeItem(STORAGE_KEY);
  const url = new URL(window.location.href);
  url.searchParams.delete("run_id");
  url.searchParams.delete("mode");
  window.history.replaceState({}, "", url);
}

function loadCurrentRun() {
  try {
    const params = new URLSearchParams(window.location.search);
    const queryRunId = params.get("run_id");
    if (queryRunId) {
      currentRunId = queryRunId;
      const mode = params.get("mode") || "";
      if (mode) document.getElementById("mode").textContent = mode.toUpperCase();
      renderRunId();
      return;
    }
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return;
    const data = JSON.parse(raw);
    currentRunId = data.run_id || "";
    if (data.mode) document.getElementById("mode").textContent = data.mode.toUpperCase();
    renderRunId();
  } catch {
    currentRunId = "";
  }
}

function renderRunId() {
  const target = document.getElementById("run-id");
  if (target) target.textContent = currentRunId ? currentRunId : "";
}

async function startRun(mode) {
  const run = await apiPost("/demo/runs", {execution_mode: mode, task_case: "incident_repair_v1"});
  currentRunId = run.run_id;
  lastEventId = 0;
  document.getElementById("mode").textContent = mode.toUpperCase();
  saveCurrentRun(mode);
  startPolling();
  await refresh();
}

async function refresh() {
  if (!currentRunId) return;
  let summary;
  try {
    summary = await apiGet(`/demo/runs/${currentRunId}`);
  } catch (err) {
    clearMissingRun();
    return;
  }
  const graph = await apiGetOrDefault(`/demo/runs/${currentRunId}/graph`, {});
  const displaySummary = mergeSummaryWithGraph(summary, graph);
  const runtimeTasks = await apiGetOrDefault(`/demo/runs/${currentRunId}/runtime-tasks`, {tasks: []});
  window.__latestRuntimeTasks = runtimeTasks.tasks || [];
  renderSummary(displaySummary);
  renderAgentFocus(displaySummary, graph);
  renderRuntimeLayer(displaySummary, runtimeTasks);
  renderTopology(graph);
  renderGraph(graph);
  stopPollingIfTerminal(displaySummary);
}

function clearMissingRun() {
  clearDisplayedRun("MISSING");
}

function clearDisplayedRun(status) {
  currentRunId = "";
  lastEventId = 0;
  clearCurrentRun();
  renderRunId();
  renderSummary({status, execution_mode: "none"});
  renderAgentFocus({status}, {workflow_status: status});
  renderRuntimeLayer({execution_mode: "none"}, {tasks: []});
  renderTopology({workflow_status: status, planned_tasks: []});
  renderGraph({workflow_status: status, planned_tasks: []});
}

document.getElementById("runtime").onclick = () => startRun("runtime");
document.getElementById("direct").onclick = () => startRun("direct");
document.getElementById("replay").onclick = () => startRun("replay");
document.getElementById("cancel").onclick = async () => {
  const runId = currentRunId;
  if (runId) {
    try {
      await apiPost(`/demo/runs/${runId}/cancel`, {});
    } catch (err) {
      console.warn(`cancel failed or run already deleted: ${runId}`, err);
    }
  }
  clearDisplayedRun("DELETED");
};
loadCurrentRun();
refresh();
startPolling();

function renderSummary(summary) {
  const status = String(summary.status || "PENDING").toUpperCase();
  const tasks = summary.execution?.tasks ?? 0;
  const attempts = summary.execution?.attempts ?? 0;
  document.getElementById("summary").innerHTML = `
    <div class="footer-stat">执行模式：<strong>${escapeHtml(summary.execution_mode || "runtime")}</strong></div>
    <div class="footer-stat">总任务:<strong>${escapeHtml(tasks)}</strong></div>
    <div class="footer-stat">总尝试:<strong>${escapeHtml(attempts)}</strong></div>
    <div class="footer-stat">工作流状态:<strong><span class="status-dot">•</span> ${escapeHtml(status)}</strong></div>
    <div class="mode-pill">${escapeHtml(summary.execution_mode || "runtime")}</div>`;
}

function mergeSummaryWithGraph(summary, graph) {
  const graphStatus = String(graph.workflow_status || "").toUpperCase();
  if (!isTerminalStatus(graphStatus)) return summary;
  return {
    ...summary,
    status: graphStatus,
    error: graph.error || summary.error,
    result: {
      ...(summary.result || {}),
      pytest_returncode: graph.test_summary?.returncode ?? summary.result?.pytest_returncode,
      review_approved: graph.review_summary?.approved ?? summary.result?.review_approved,
    },
  };
}

function renderAgentFocus(summary, state) {
  const current = currentAgentState(summary, state);
  const runtimeTask = currentRuntimeTask(current.agent);
  const role = String(current.agent || "workflow").toUpperCase();
  const roleTarget = document.getElementById("agent-role");
  if (roleTarget) roleTarget.textContent = role;
  document.getElementById("agent-focus").innerHTML = `<div class="focus">
    <div class="focus-top">
      <span class="status ${escapeHtml(current.status)}">${escapeHtml(current.status)}</span>
      <span class="focus-backend">后端: ${escapeHtml(current.backend || "codex_cli")}</span>
    </div>
    <div class="focus-action">操作：${escapeHtml(current.action)}</div>
    <div class="focus-task">
      <div>任务ID: ${escapeHtml(runtimeTask?.task_id || "等待任务创建")}</div>
      <div>尝试次数: ${escapeHtml(runtimeTask?.attempts || "0/0")} · 状态: ${escapeHtml(current.status)}</div>
    </div>
  </div>`;
}

function renderRuntimeLayer(summary, runtimeTasks) {
  const mode = String(summary.execution_mode || "").toLowerCase();
  const tasks = runtimeTasks.tasks || [];
  const isRuntime = mode === "runtime";
  const queueBrief = document.getElementById("queue-brief");
  if (queueBrief) queueBrief.textContent = `${tasks.length} tasks`;
  document.getElementById("runtime-layer").innerHTML = `<div class="layer ${isRuntime ? "runtime-mode" : "direct-mode"}">
      ${renderMonitorMetrics(summary, tasks)}
      <div class="runtime-tasks">
        ${isRuntime ? renderRuntimeTasks(tasks) : renderDirectLayer(summary)}
      </div>
      <div class="repair-note">修复内容: ${escapeHtml(latestRepairNote(tasks))}</div>
    </div>`;
}

function renderMonitorMetrics(summary, tasks) {
  const activeWorkers = new Set(tasks.filter(task => ["RUNNING", "SUCCESS"].includes(String(task.status || "").toUpperCase())).map(task => task.agent_name)).size;
  const attempts = tasks.reduce((total, task) => total + (task.attempts || []).length, 0);
  return `<div class="monitor-metrics">
    <div class="monitor-metric"><span>运行耗时</span><strong>${escapeHtml(formatDuration(runAgeMs(summary)))}</strong></div>
    <div class="monitor-metric"><span>Runtime任务</span><strong>${escapeHtml(tasks.length)}</strong></div>
    <div class="monitor-metric"><span>Attempt次数</span><strong>${escapeHtml(attempts)}</strong></div>
    <div class="monitor-metric"><span>活跃Worker</span><strong>${escapeHtml(activeWorkers || 0)}</strong></div>
  </div>`;
}

function runAgeMs(summary) {
  if (summary.duration_ms) return Number(summary.duration_ms) || 0;
  const startedAt = Number(summary.started_at || 0);
  if (!startedAt) return 0;
  const finishedAt = Number(summary.finished_at || 0) || Date.now() / 1000;
  return Math.max(0, (finishedAt - startedAt) * 1000);
}

function formatDuration(ms) {
  const value = Number(ms || 0);
  if (value < 1000) return `${Math.round(value)} ms`;
  const seconds = value / 1000;
  if (seconds < 60) return `${seconds.toFixed(1)} s`;
  const minutes = Math.floor(seconds / 60);
  const remain = Math.round(seconds % 60);
  return `${minutes}m ${remain}s`;
}

function renderRuntimeTasks(tasks) {
  if (!tasks.length) return `<div class="empty">No runtime task submitted yet</div>`;
  return tasks.map(task => {
    const attempts = task.attempts || [];
    const latest = attempts[attempts.length - 1] || {};
    return `<div class="runtime-task">
      <div class="runtime-task-main">
        <strong>${escapeHtml(task.agent_name || "unassigned")}</strong>
        <span class="status ${escapeHtml(task.status || "PENDING")}">${escapeHtml(task.status || "PENDING")}</span>
      </div>
      <div class="runtime-task-id">${escapeHtml(task.task_id || "")}</div>
      <div class="runtime-attempts">attempts ${attempts.length}${latest.attempt_id ? ` · latest ${escapeHtml(latest.attempt_id)}` : ""}</div>
    </div>`;
  }).join("");
}

function renderDirectLayer(summary) {
  return `<div class="runtime-task">
    <div class="runtime-task-main">
      <strong>LangGraph process</strong>
      <span class="status RUNNING">DIRECT</span>
    </div>
    <div class="runtime-task-id">进程内执行，不提交 agentd runtime task</div>
  </div>`;
}

function currentAgentState(summary, state) {
  const status = String(summary.status || state.workflow_status || "PENDING").toUpperCase();
  if (isTerminalStatus(status)) return {agent: "Workflow", action: summary.error || terminalAction(status), status, backend: "langgraph"};
  if (!state.plan) return {agent: "Planner", action: "分析故障并生成修复计划", status: "RUNNING", backend: "native_planner"};
  if ((state.completed_coder_task_ids || []).length < (state.planned_tasks || []).filter(t => t.role === "coder").length) {
    const active = state.active_coder_task || nextTask(state, "coder");
    return {agent: "Coder", action: active?.goal || "编辑代码并生成 patch", status: "RUNNING", backend: "codex_cli"};
  }
  if (!state.integrated_commit) return {agent: "Integrate", action: "应用 patch 到集成工作区", status: "RUNNING", backend: "direct_tool"};
  if (!state.test_summary) return {agent: "Tester", action: "运行回归测试", status: "RUNNING", backend: "direct_tool"};
  if (state.test_summary.returncode !== 0) return {agent: "Repair", action: "修复失败测试并重新生成 patch", status: "RECOVERING", backend: "codex_cli"};
  if (!state.review_summary) return {agent: "Reviewer", action: "检查 diff 和测试结果", status: "RUNNING", backend: "codex_cli"};
  if (state.review_summary && !state.review_summary.approved) return {agent: "Repair", action: "处理 reviewer 反馈", status: "RECOVERING", backend: "codex_cli"};
  return {agent: "Workflow", action: "等待最终状态", status: state.workflow_status || "RUNNING", backend: "langgraph"};
}

function terminalAction(status) {
  const actions = {
    SUCCESS: "Workflow completed",
    FAILED: "Workflow failed",
    TIMEOUT: "Workflow timed out",
    CANCELLED: "Workflow cancelled",
    INTERRUPTED: "Workflow interrupted",
    DELETED: "Run deleted",
    MISSING: "Run was cleaned up"
  };
  return actions[status] || "Workflow completed";
}

function graphNodes(state) {
  const status = state.workflow_status || "PENDING";
  const tasks = state.planned_tasks || [];
  const coderTasks = tasks.filter(t => t.role === "coder");
  return [
    graphNode("planner", "Planner", "planner", statusFor(state.plan), state.plan?.summary || "Build repair DAG", []),
    graphNode("coder", `Coder x${coderTasks.length || 1}`, "coder", coderStatus(state), coderAction(state, coderTasks), ["planner"]),
    graphNode("integrator", "Integrate", "integrator", state.integrated_commit ? "SUCCESS" : afterCoderStatus(state), integrateAction(state), ["coder"]),
    graphNode("tester", "Tester", "tester", testerStatus(state), testerAction(state), ["integrator"]),
    graphNode("repair", "Repair", "repair", repairStatus(state), repairAction(state), ["tester"]),
    graphNode("reviewer", "Reviewer", "reviewer", reviewerStatus(state), reviewerAction(state), ["tester", "repair"]),
    graphNode("workflow", "Done", "workflow", status, workflowAction(state), ["reviewer"]),
  ];
}

function renderTopology(state) {
  const target = document.getElementById("topology");
  if (!target) return;
  target.innerHTML = topology(graphNodes(state), state);
}

function renderGraph(state) {
  const nodes = graphNodes(state);
  const current = nodes.find(item => ["RUNNING", "RECOVERING", "FAILED", "TIMEOUT"].includes(item.status)) || nodes[nodes.length - 1];
  const brief = document.getElementById("active-brief");
  if (brief) brief.textContent = `当前焦点：${current.name}`;
  const updatedAt = document.getElementById("updated-at");
  if (updatedAt) updatedAt.textContent = `· 更新 ${new Date().toLocaleTimeString()}`;
  document.getElementById("graph").innerHTML = `<div class="langgraph-panel">
    <div class="langgraph-head">
      <div>
        <div class="label">Workflow Status</div>
        <strong>${escapeHtml(state.workflow_status || "PENDING")}</strong>
      </div>
      <div>
        <div class="label">Active Node</div>
        <strong>${escapeHtml(current.name)}</strong>
      </div>
    </div>
    ${renderGraphTopology(nodes)}
  </div>`;
}

function graphNode(id, name, role, status, action, deps) {
  return {id, name, role, status, action, deps};
}

function renderGraphTopology(nodes) {
  const positions = {
    planner: [24, 128],
    coder: [190, 128],
    integrator: [356, 128],
    tester: [522, 128],
    repair: [688, 28],
    reviewer: [688, 228],
    workflow: [854, 228],
  };
  const edges = [
    ["planner", "coder"],
    ["coder", "integrator"],
    ["integrator", "tester"],
    ["repair", "tester"],
    ["tester", "reviewer"],
    ["reviewer", "repair"],
    ["reviewer", "workflow"],
  ];
  const byId = Object.fromEntries(nodes.map(item => [item.id, item]));
  return `<div class="langgraph-topology">
    <svg class="langgraph-edges" viewBox="0 0 992 356" aria-hidden="true">
      <defs>
        <marker id="langgraph-arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto">
          <path d="M 0 0 L 10 5 L 0 10 z" fill="context-stroke"></path>
        </marker>
      </defs>
      ${edges.map(([from, to]) => graphEdge(positions[from], positions[to], byId[from], byId[to], from, to)).join("")}
    </svg>
    ${nodes.map((item, index) => {
      const pos = positions[item.id];
      if (!pos) return "";
      return `<div class="graph-node-slot" style="left:${pos[0]}px;top:${pos[1]}px">${graphStep(item, index + 1)}</div>`;
    }).join("")}
  </div>`;
}

function graphEdge(from, to, source, target, fromId, toId) {
  if (!from || !to) return "";
  const nodeW = 110;
  const nodeH = 86;
  const startX = from[0] + nodeW;
  const startY = from[1] + nodeH / 2;
  const endX = to[0] - 16;
  const endY = to[1] + nodeH / 2;
  const status = edgeStatus(source, target);
  const live = ["RUNNING", "RECOVERING"].includes(target?.status || "") ? " live" : "";
  if (fromId === "repair" && toId === "tester") {
    const sx = from[0] + 8;
    const sy = from[1] + nodeH / 2;
    const ex = to[0] + nodeW / 2;
    const ey = to[1] - 12;
    return `<path class="graph-edge ${escapeHtml(status)}${live}" d="M ${sx} ${sy} C ${sx - 92} ${sy + 4}, ${ex - 94} ${ey - 70}, ${ex} ${ey}"></path>`;
  }
  if (fromId === "reviewer" && toId === "repair") {
    const sx = from[0] + 8;
    const sy = from[1] + nodeH / 2;
    const ex = to[0] + nodeW / 2;
    const ey = to[1] + nodeH + 10;
    return `<line class="graph-edge ${escapeHtml(status)}${live}" x1="${sx}" y1="${sy}" x2="${ex}" y2="${ey}"></line>`;
  }
  const midX = (startX + endX) / 2;
  const curve = Math.max(42, (endX - startX) * 0.42);
  return `<path class="graph-edge ${escapeHtml(status)}${live}" d="M ${startX} ${startY} C ${startX + curve} ${startY}, ${endX - curve} ${endY}, ${endX} ${endY}"></path>`;
}

function topology(nodes, state) {
  const positions = {
    planner: [76, 128],
    coder: [250, 128],
    integrator: [424, 128],
    tester: [598, 128],
    repair: [772, 128],
    reviewer: [946, 128],
    workflow: [1120, 128],
  };
  const byId = Object.fromEntries(nodes.map(item => [item.id, item]));
  const edges = nodes.flatMap(item => item.deps.map(dep => [dep, item.id]));
  const active = activeTopologyNode(nodes);
  const counts = topologyCounts(nodes);
  return `<div class="topology-shell">
    <div class="topology-meta">
      <div>
        <span class="label">Active</span>
        <strong>${escapeHtml(active?.name || "Workflow")}</strong>
      </div>
      <div>
        <span class="label">Status</span>
        <span class="status ${escapeHtml(active?.status || state.workflow_status || "PENDING")}">${escapeHtml(active?.status || state.workflow_status || "PENDING")}</span>
      </div>
      <div>
        <span class="label">Updated</span>
        <strong>${escapeHtml(new Date().toLocaleTimeString())}</strong>
      </div>
    </div>
    <svg class="topology live-topology" viewBox="0 0 1196 256" role="img" aria-label="Real-time agent dependency topology">
    <defs>
      <marker id="topology-arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto">
        <path d="M 0 0 L 10 5 L 0 10 z" fill="context-stroke"></path>
      </marker>
    </defs>
    ${edges.map(([from, to]) => topoEdge(positions[from], positions[to], byId[from], byId[to])).join("")}
    ${nodes.map(item => topoNode(item, positions[item.id], active?.id === item.id)).join("")}
  </svg>
  <div class="topology-counts">
    ${["SUCCESS", "RUNNING", "RECOVERING", "FAILED", "PENDING"].map(status => `<span class="${escapeHtml(status)}"><strong>${counts[status] || 0}</strong>${escapeHtml(status)}</span>`).join("")}
  </div>
  <div class="topology-legend">
    ${["PENDING", "RUNNING", "RECOVERING", "SUCCESS", "FAILED"].map(status => `<span><i class="${escapeHtml(status)}"></i>${escapeHtml(status)}</span>`).join("")}
  </div>
  </div>`;
}

function activeTopologyNode(nodes) {
  return nodes.find(item => ["RUNNING", "RECOVERING"].includes(item.status))
    || nodes.find(item => ["FAILED", "TIMEOUT"].includes(item.status))
    || nodes.find(item => item.status === "PENDING")
    || nodes[nodes.length - 1];
}

function topologyCounts(nodes) {
  return nodes.reduce((acc, item) => {
    const status = item.status || "PENDING";
    acc[status] = (acc[status] || 0) + 1;
    return acc;
  }, {});
}

function topoEdge(from, to, source, target) {
  if (!from || !to) return "";
  const midX = (from[0] + to[0]) / 2;
  const path = `M ${from[0] + 36} ${from[1]} C ${midX} ${from[1]}, ${midX} ${to[1]}, ${to[0] - 36} ${to[1]}`;
  const status = edgeStatus(source, target);
  const live = ["RUNNING", "RECOVERING"].includes(target?.status || "") ? " live" : "";
  return `<path class="topo-edge ${escapeHtml(status)}${live}" d="${path}"></path>`;
}

function edgeStatus(source, target) {
  if (["RUNNING", "RECOVERING"].includes(target?.status || "")) return target.status;
  if (["FAILED", "TIMEOUT"].includes(source?.status || "") || ["FAILED", "TIMEOUT"].includes(target?.status || "")) return "FAILED";
  if (source?.status === "SUCCESS" && target?.status === "SUCCESS") return "SUCCESS";
  return "PENDING";
}

function topoNode(item, pos, active) {
  if (!pos) return "";
  return `<g class="topo-node ${escapeHtml(item.status)}${active ? " active" : ""}" transform="translate(${pos[0]} ${pos[1]})">
    <ellipse class="node-ring" rx="42" ry="30"></ellipse>
    <ellipse rx="34" ry="24"></ellipse>
    <text y="4">${escapeHtml(shortName(item.name))}</text>
    <title>${escapeHtml(`${item.name}: ${item.status}`)}</title>
  </g>
  <text class="topo-label" x="${pos[0]}" y="${pos[1] + 50}">${escapeHtml(item.name)}</text>`;
}

function shortName(name) {
  const value = String(name || "");
  if (value.startsWith("Coder")) return "C";
  if (value.startsWith("Planner")) return "P";
  if (value.startsWith("Integrate")) return "I";
  if (value.startsWith("Tester")) return "T";
  if (value.startsWith("Repair")) return "R";
  if (value.startsWith("Reviewer")) return "V";
  return "D";
}

function graphStep(item, index) {
  return `<div class="graph-step ${escapeHtml(item.status)}">
    <div class="step-index">${index}</div>
    <div>
      <div class="node-top">
        <strong>${escapeHtml(item.name)}</strong>
        <span class="node-role">${escapeHtml(item.role)}</span>
      </div>
      <div class="node-action">${escapeHtml(item.action)}</div>
      <div class="node-deps">${escapeHtml(item.deps.length ? `depends on ${item.deps.join(", ")}` : "entry")}</div>
    </div>
    <div class="node-status-pill">${escapeHtml(item.status)}</div>
  </div>`;
}

function currentRuntimeTask(agentName) {
  const tasks = window.__latestRuntimeTasks || [];
  const normalized = String(agentName || "").toLowerCase();
  const task = tasks.find(item => String(item.agent_name || "").toLowerCase().includes(normalized))
    || tasks.find(item => String(item.status || "").toUpperCase() === "RUNNING")
    || tasks[0];
  if (!task) return null;
  return {
    task_id: task.task_id,
    attempts: `${(task.attempts || []).length}/3`,
  };
}

function latestRepairNote(tasks) {
  const running = (tasks || []).find(task => String(task.status || "").toUpperCase() === "RUNNING");
  if (running?.agent_name) return `${running.agent_name} 正在处理当前任务`;
  return "等待运行时产生修复任务";
}

function statusFor(value) {
  return value ? "SUCCESS" : "PENDING";
}

function nextTask(state, role) {
  const done = new Set(state.completed_coder_task_ids || []);
  return (state.planned_tasks || []).find(task => task.role === role && !done.has(task.local_id));
}

function coderStatus(state) {
  const tasks = (state.planned_tasks || []).filter(t => t.role === "coder");
  if (!state.plan) return "PENDING";
  if ((state.completed_coder_task_ids || []).length >= tasks.length && tasks.length > 0) return "SUCCESS";
  return "RUNNING";
}

function afterCoderStatus(state) {
  return coderStatus(state) === "SUCCESS" ? "RUNNING" : "PENDING";
}

function coderAction(state, tasks) {
  const done = state.completed_coder_task_ids || [];
  const active = state.active_coder_task || nextTask(state, "coder");
  if (!state.plan) return "Waiting for plan";
  if (done.length >= tasks.length && tasks.length > 0) return `${done.length}/${tasks.length} coder tasks completed`;
  return active?.goal || `${done.length}/${tasks.length || 1} coder tasks completed`;
}

function integrateAction(state) {
  if (state.integrated_commit) return `commit ${String(state.integrated_commit).slice(0, 8)}`;
  return (state.patch_refs || []).length ? "Applying patch artifacts" : "Waiting for patch";
}

function testerStatus(state) {
  if (!state.integrated_commit) return "PENDING";
  if (!state.test_summary) return "RUNNING";
  return state.test_summary.returncode === 0 ? "SUCCESS" : "FAILED";
}

function testerAction(state) {
  if (!state.test_summary) return state.integrated_commit ? "Running pytest" : "Waiting for integration";
  if (state.test_summary.returncode !== 0) return firstFailureMessage(state.test_summary);
  return `${state.test_summary.passed || 0} passed, ${state.test_summary.failed || 0} failed`;
}

function repairStatus(state) {
  if (state.review_summary && !state.review_summary.approved && state.workflow_status !== "FAILED" && state.workflow_status !== "SUCCESS") return "RECOVERING";
  if (!state.test_summary || state.test_summary.returncode === 0) return state.repair_round > 0 ? "SUCCESS" : "PENDING";
  return "RECOVERING";
}

function repairAction(state) {
  if (state.review_summary && !state.review_summary.approved && state.workflow_status !== "FAILED" && state.workflow_status !== "SUCCESS") return "Addressing reviewer findings";
  if (state.repair_round > 0) return `repair round ${state.repair_round}`;
  return "Only runs after test/review failure";
}

function reviewerStatus(state) {
  if (state.workflow_status === "SUCCESS") return "SUCCESS";
  if (!state.test_summary || state.test_summary.returncode !== 0) return "PENDING";
  if (!state.review_summary) return "RUNNING";
  if (!state.review_summary.approved && state.repair_round > 0 && state.workflow_status !== "FAILED") return "RUNNING";
  return state.review_summary.approved ? "SUCCESS" : "FAILED";
}

function reviewerAction(state) {
  if (state.workflow_status === "SUCCESS") return state.review_summary?.summary || "Approved";
  if (state.review_summary && !state.review_summary.approved && state.repair_round > 0 && state.workflow_status !== "FAILED") return "Re-reviewing repaired patch";
  if (!state.review_summary) return "Waiting for clean tests";
  return state.review_summary.summary || (state.review_summary.approved ? "Approved" : "Issues found");
}

function workflowAction(state) {
  if (state.error) return state.error;
  return state.workflow_status === "SUCCESS" ? "All checks passed" : "Waiting for final node";
}

function firstFailureMessage(testSummary) {
  const item = (testSummary.failed_tests || [])[0] || {};
  const message = String(item.message || item.name || "Tests failed");
  const match = message.match(/ModuleNotFoundError: No module named '[^']+'/);
  if (match) return match[0];
  return message.length > 180 ? `${message.slice(0, 177)}...` : message;
}
