const $ = id => document.getElementById(id);
const esc = value => String(value ?? '').replace(/[&<>'"]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','"':'&quot;'}[c]));
const terminal = status => ['completed', 'review_failed', 'failed'].includes(status);
const toast = message => {
  $('toast').textContent = message;
  $('toast').classList.add('show');
  setTimeout(() => $('toast').classList.remove('show'), 4400);
};

async function api(path, options = {}) {
  const response = await fetch(path, {headers: {'Content-Type': 'application/json'}, ...options});
  const body = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(body.detail || `${response.status} ${response.statusText}`);
  return body;
}

const POSITIONS = {
  request:[7,43], root:[20,43], market:[37,11], technical:[37,31],
  risk:[37,58], buyer:[37,80], tavily:[55,24], e2b:[55,60],
  oracle:[20,82], shared:[69,43], synthesis:[82,43], review:[94,43],
};

let runtimeReady = false;
let currentRun = null;
let stream = null;
let pollTimer = null;
let selectedRole = null;
let contextTimer = null;

function requestPayload() {
  const list = id => $(id).value.split(',').map(value => value.trim()).filter(Boolean);
  return {
    question: $('question').value,
    focus: $('focus').value,
    include_domains: list('include'),
    exclude_domains: list('exclude'),
    confirmed: $('confirm').checked,
    approver_id: 'appbook-operator',
  };
}

function metric(value, label) {
  return `<div class="metric"><div class="metric-value">${esc(value)}</div><div class="metric-label">${esc(label)}</div></div>`;
}

function nodeById(snapshot, id) {
  return (snapshot?.nodes || []).find(node => node.id === id);
}

function renderFlow(snapshot) {
  const canvas = $('flow-canvas');
  canvas.querySelectorAll('.flow-node').forEach(node => node.remove());
  $('flow-empty').style.display = snapshot ? 'none' : 'block';
  if (!snapshot) return;
  (snapshot.nodes || []).forEach(node => {
    const position = POSITIONS[node.id] || [50, 50];
    const element = document.createElement(node.clickable ? 'button' : 'div');
    if (node.clickable) element.type = 'button';
    element.className = `flow-node ${node.status || 'pending'} ${node.clickable ? 'clickable' : ''} ${selectedRole === node.id ? 'selected' : ''}`;
    element.dataset.node = node.id;
    element.style.left = `${position[0]}%`;
    element.style.top = `${position[1]}%`;
    element.title = node.detail || node.label;
    element.innerHTML = `<span class="node-kind">${esc(node.kind)} · ${esc(node.status)}</span><span class="node-label">${esc(node.label)}</span><span class="node-detail">${esc(node.detail)}</span>`;
    if (node.clickable) element.addEventListener('click', () => openAgentContext(node.id));
    canvas.appendChild(element);
  });
  requestAnimationFrame(() => drawEdges(snapshot));
}

function drawEdges(snapshot) {
  const canvas = $('flow-canvas');
  const svg = $('flow-edges');
  const bounds = canvas.getBoundingClientRect();
  svg.setAttribute('viewBox', `0 0 ${bounds.width} ${bounds.height}`);
  svg.innerHTML = `<defs><marker id="arrow" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="5" markerHeight="5" orient="auto-start-reverse"><path d="M 0 0 L 10 5 L 0 10 z" fill="#456a63"></path></marker></defs>`;
  (snapshot.edges || []).forEach(([from, to]) => {
    const source = canvas.querySelector(`[data-node="${CSS.escape(from)}"]`);
    const target = canvas.querySelector(`[data-node="${CSS.escape(to)}"]`);
    if (!source || !target) return;
    const a = source.getBoundingClientRect();
    const b = target.getBoundingClientRect();
    const x1 = a.left + a.width / 2 - bounds.left;
    const y1 = a.top + a.height / 2 - bounds.top;
    const x2 = b.left + b.width / 2 - bounds.left;
    const y2 = b.top + b.height / 2 - bounds.top;
    const dx = Math.max(34, Math.abs(x2 - x1) * .46);
    const path = document.createElementNS('http://www.w3.org/2000/svg', 'path');
    path.setAttribute('d', `M ${x1} ${y1} C ${x1 + dx} ${y1}, ${x2 - dx} ${y2}, ${x2} ${y2}`);
    const sourceNode = nodeById(snapshot, from);
    const targetNode = nodeById(snapshot, to);
    const active = sourceNode?.status !== 'pending' && ['running', 'completed', 'failed'].includes(targetNode?.status);
    path.setAttribute('class', `flow-edge ${active ? 'active' : ''}`);
    path.setAttribute('marker-end', 'url(#arrow)');
    svg.appendChild(path);
  });
}

function renderEvents(events) {
  const rows = (events || []).slice(-180).map(event => `<div class="event">
    <span class="event-seq">#${esc(event.seq)}</span>
    <span class="event-type">${esc(event.type)}</span>
    <span class="event-detail">${esc(event.detail || event.query || event.role || '')}</span>
  </div>`);
  $('events').innerHTML = rows.length ? rows.join('') : '<div class="empty">No events yet.</div>';
  $('events').scrollTop = $('events').scrollHeight;
}

function renderPlan(snapshot) {
  const nodes = Object.fromEntries((snapshot.nodes || []).map(node => [node.agent_id, node.id]));
  const tasks = snapshot.workflow?.tasks || [];
  $('plan').innerHTML = tasks.length ? tasks.map(task => `<div class="source">
    <div><span class="badge accent">${esc(nodes[task.assigned_agent_id] || task.assigned_agent_id)}</span> <strong>${esc(task.task_id)}</strong></div>
    <div class="source-copy">${esc(task.description)}</div>
    <div class="source-meta">priority ${esc(task.priority)} · ${esc(task.status)}</div>
  </div>`).join('') : '<div class="empty">The root model is still planning.</div>';
}

function renderEvidence(items) {
  $('evidence').className = items?.length ? 'stack' : 'empty';
  $('evidence').innerHTML = (items || []).length ? items.map(item => `<article class="source">
    <a href="${esc(item.url)}" target="_blank" rel="noreferrer">${esc(item.title)}</a>
    <div class="source-meta">${esc(item.evidence_id)} · ${esc(item.roles?.join(', ') || item.role)} · ${esc(item.provider)}</div>
    <div class="source-copy">${esc(item.snippet)}</div>
    <div class="source-meta">query: ${esc(item.query)}</div>
  </article>`).join('') : 'No evidence retrieved.';
}

function renderReview(review) {
  const entries = Object.entries(review || {}).filter(([name]) => name !== 'all_passed');
  $('review').innerHTML = entries.length ? entries.map(([name, passed]) => `<div class="check ${passed ? 'pass' : 'fail'}"><span>${esc(name.replaceAll('_', ' '))}</span><span class="badge ${passed ? 'accent' : 'warn'}">${passed ? 'pass' : 'fail'}</span></div>`).join('') : '<div class="empty">Review begins after synthesis.</div>';
}

function renderSnapshot(snapshot) {
  currentRun = snapshot;
  const metrics = snapshot.metrics || {};
  $('metrics').innerHTML = [
    metric(metrics.events ?? 0, 'streamed events'),
    metric(metrics.searches ?? 0, 'Tavily searches'),
    metric(metrics.sources ?? 0, 'unique sources'),
    metric(metrics.delegates_completed ?? 0, 'delegates complete'),
  ].join('');
  const statusText = snapshot.error ? `${snapshot.status}: ${snapshot.error}` : `${snapshot.status} · run ${snapshot.run_id.slice(0, 8)}`;
  $('run-status').textContent = statusText;
  $('run-status').classList.toggle('warn', ['failed', 'review_failed'].includes(snapshot.status));
  $('report').className = snapshot.report ? 'report' : 'empty';
  $('report').textContent = snapshot.report || 'The live report will appear here.';
  renderFlow(snapshot);
  renderEvents(snapshot.events);
  renderPlan(snapshot);
  renderEvidence(snapshot.evidence);
  renderReview(snapshot.review);
  $('start').disabled = !runtimeReady || !terminal(snapshot.status);
  if (terminal(snapshot.status) && selectedRole && $('context-dialog').open) refreshAgentContext();
}

async function loadStatus() {
  const status = await api('/api/status');
  runtimeReady = !!status.ready;
  $('status-dot').classList.toggle('ready', runtimeReady);
  $('status-title').textContent = runtimeReady ? 'Live MemoRizz runtime ready' : 'Runtime unavailable';
  if (!runtimeReady) {
    $('status-detail').textContent = status.error || status.remediation || 'Provider setup failed.';
    $('start').disabled = true;
    return;
  }
  const settings = status.settings || {};
  $('status-detail').textContent = `MemoRizz ${status.memorizz?.version} · ${settings.model} · ${settings.oracle_user}@${settings.oracle_dsn}`;
  $('architecture').textContent = `${status.architecture}\n\n${(status.pipeline || []).map((item, index) => `${index + 1}. ${item}`).join('\n')}`;
  $('start').disabled = !$('confirm').checked || !!status.active_run_id;
  if (status.active_run_id) {
    try {
      const snapshot = await api(`/api/research/runs/${encodeURIComponent(status.active_run_id)}`);
      renderSnapshot(snapshot);
      connectStream(snapshot.run_id);
    } catch (error) { toast(error.message); }
  }
}

async function startResearch() {
  const button = $('start');
  button.disabled = true;
  button.classList.add('loading');
  try {
    const snapshot = await api('/api/research/live', {method: 'POST', body: JSON.stringify(requestPayload())});
    renderSnapshot(snapshot);
    connectStream(snapshot.run_id);
  } catch (error) {
    toast(error.message);
    button.disabled = false;
  } finally {
    button.classList.remove('loading');
  }
}

function connectStream(runId) {
  if (stream) stream.close();
  if (pollTimer) clearInterval(pollTimer);
  stream = new EventSource(`/api/research/runs/${encodeURIComponent(runId)}/stream`);
  stream.addEventListener('update', event => {
    const payload = JSON.parse(event.data);
    if (payload.snapshot) renderSnapshot(payload.snapshot);
  });
  stream.addEventListener('complete', event => {
    const payload = JSON.parse(event.data);
    if (payload.snapshot) renderSnapshot(payload.snapshot);
    stream.close();
    stream = null;
  });
  stream.onerror = () => {
    if (stream) stream.close();
    stream = null;
    if (!pollTimer) pollTimer = setInterval(async () => {
      try {
        const snapshot = await api(`/api/research/runs/${encodeURIComponent(runId)}`);
        renderSnapshot(snapshot);
        if (terminal(snapshot.status)) { clearInterval(pollTimer); pollTimer = null; }
      } catch (error) { clearInterval(pollTimer); pollTimer = null; toast(error.message); }
    }, 900);
  };
}

async function openAgentContext(role) {
  if (!currentRun) return;
  selectedRole = role;
  renderFlow(currentRun);
  $('context-title').textContent = `${role[0].toUpperCase()}${role.slice(1)} context`;
  $('context-content').innerHTML = '<div class="empty-state">Reading live Oracle memory and context telemetry…</div>';
  $('context-dialog').showModal();
  await refreshAgentContext();
  clearInterval(contextTimer);
  if (!terminal(currentRun.status)) contextTimer = setInterval(refreshAgentContext, 1100);
}

async function refreshAgentContext() {
  if (!selectedRole || !currentRun || !$('context-dialog').open) return;
  try {
    const context = await api(`/api/research/runs/${encodeURIComponent(currentRun.run_id)}/agents/${encodeURIComponent(selectedRole)}/context`);
    const tools = (context.registered_tools || []).join(', ');
    const meta = `<div class="context-meta"><span class="badge accent">${esc(context.node?.status)}</span><span class="badge">${esc(context.model)}</span><span class="badge">${esc(context.estimated_tokens)} estimated tokens</span><span class="badge">${esc(context.private_memory_id)}</span></div>`;
    const note = `<div class="notice">${esc(context.note)}<br><small>Tools: ${esc(tools)}</small></div>`;
    const sections = (context.sections || []).map((section, index) => `<details class="context-section" ${index < 2 ? 'open' : ''}><summary>${esc(section.title)} · ${esc(section.kind)} · ${esc(section.estimated_tokens)} tokens</summary><pre>${esc(section.content)}</pre></details>`).join('');
    $('context-content').innerHTML = meta + note + sections;
  } catch (error) {
    $('context-content').innerHTML = `<div class="notice warn">${esc(error.message)}</div>`;
  }
}

function closeContext() {
  clearInterval(contextTimer);
  contextTimer = null;
  selectedRole = null;
  $('context-dialog').close();
  if (currentRun) renderFlow(currentRun);
}

$('confirm').addEventListener('change', () => {
  $('start').disabled = !runtimeReady || !$('confirm').checked || (currentRun && !terminal(currentRun.status));
});
$('start').addEventListener('click', startResearch);
$('context-close').addEventListener('click', closeContext);
$('context-dialog').addEventListener('cancel', event => { event.preventDefault(); closeContext(); });
window.addEventListener('resize', () => currentRun && drawEdges(currentRun));
loadStatus().catch(error => toast(error.message));
