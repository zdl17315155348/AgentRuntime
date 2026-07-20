async function apiGet(path) {
  const resp = await fetch(path);
  if (!resp.ok) throw new Error(await resp.text());
  return resp.json();
}

async function apiPost(path, body) {
  const resp = await fetch(path, {
    method: "POST",
    headers: {"content-type": "application/json"},
    body: JSON.stringify(body || {})
  });
  if (!resp.ok) throw new Error(await resp.text());
  return resp.json();
}

function renderJson(id, value) {
  document.getElementById(id).textContent = JSON.stringify(value, null, 2);
}

function renderMetrics(id, items) {
  document.getElementById(id).innerHTML = `<div class="metric-grid">${items.map(item => `
    <div class="metric"><div class="label">${escapeHtml(item.label)}</div><div class="value">${escapeHtml(String(item.value ?? ""))}</div></div>
  `).join("")}</div>`;
}

function escapeHtml(value) {
  return String(value).replace(/[&<>"']/g, (ch) => {
    const map = { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" };
    return map[ch];
  });
}
