const $ = id => document.getElementById(id);
const state = {runId: null, pollTimer: null};
const terminalStates = new Set(['succeeded', 'failed', 'canceled', 'interrupted', 'budget_exceeded', 'verification_failed']);

const esc = value => String(value ?? '').replace(
  /[&<>'"]/g,
  char => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', "'": '&#39;', '"': '&quot;'}[char]),
);

function toast(message) {
  $('toast').textContent = message;
  $('toast').classList.add('show');
  setTimeout(() => $('toast').classList.remove('show'), 3600);
}

async function api(path, options = {}) {
  const response = await fetch(path, {
    headers: {'Content-Type': 'application/json'},
    ...options,
  });
  const body = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(body.detail || `${response.status} ${response.statusText}`);
  return body;
}

function threadId() {
  let value = sessionStorage.getItem('metaharness-thread-id');
  if (!value) {
    value = `appbook-${crypto.randomUUID()}`;
    sessionStorage.setItem('metaharness-thread-id', value);
  }
  return value;
}

function node(id) {
  return document.querySelector(`[data-node="${id}"]`);
}

function setNode(id, status) {
  const element = node(id);
  if (!element) return;
  element.classList.remove('active', 'done', 'error', 'dim');
  if (status) element.classList.add(status);
}

function setMeta(status) {
  $('meta-boundary').classList.remove('active', 'done', 'error');
  node('meta').classList.remove('active', 'done', 'error');
  if (status) {
    $('meta-boundary').classList.add(status);
    node('meta').classList.add(status);
  }
}

function resetFlow() {
  ['request', 'meta', 'router', 'oracle-context', 'openai-live', 'anthropic-live', 'deepseek-live', 'oracle-evidence', 'response']
    .forEach(id => setNode(id, null));
  setMeta(null);
}

function hasPhase(events, phase) {
  return events.some(event => event.data?.phase === phase);
}

function renderEvents(events) {
  if (!events.length) {
    $('events').className = 'empty';
    $('events').textContent = 'Waiting for the first Oracle event row…';
    return;
  }
  $('events').className = 'event-list';
  $('events').innerHTML = events.map((event, index) => `
    <div class="event">
      <div class="event-seq">${String(event.sequence ?? index + 1).padStart(2, '0')}</div>
      <div class="event-type">${esc(event.type)}</div>
      <div class="event-data">${esc(JSON.stringify(event.data))}</div>
    </div>`).join('');
  $('events').scrollTop = $('events').scrollHeight;
}

function applyExecution(body) {
  const run = body.run || null;
  const events = body.events || [];
  const status = run?.status || body.phase || 'starting';
  const selected = run?.routing?.selected || body.result?.harness || null;
  const finished = terminalStates.has(status);
  const failed = finished && status !== 'succeeded';

  $('phase').textContent = body.phase === 'writing_memory' ? 'writing Oracle memory' : status;
  $('phase').className = `badge ${failed ? 'warn' : finished ? 'accent' : ''}`;
  $('execution-id').textContent = body.run_id || 'starting';

  setNode('request', run ? 'done' : 'active');
  setMeta(failed ? 'error' : finished ? 'done' : 'active');
  setNode('router', run?.routing?.selected ? 'done' : 'active');
  const contextReady = events.some(event => Boolean(event.data?.memory_context));
  setNode('oracle-context', contextReady ? 'done' : run ? 'active' : null);

  for (const harness of ['openai-live', 'anthropic-live', 'deepseek-live']) {
    if (selected && harness !== selected) {
      setNode(harness, 'dim');
      continue;
    }
    if (selected === harness) {
      if (failed) setNode(harness, 'error');
      else if (hasPhase(events, 'provider_response') || finished) setNode(harness, 'done');
      else if (hasPhase(events, 'provider_request')) setNode(harness, 'active');
      else setNode(harness, null);
    }
  }

  if (body.phase === 'writing_memory') setNode('oracle-evidence', 'active');
  else if (body.phase === 'complete') setNode('oracle-evidence', body.memory_error ? 'error' : 'done');
  else if (finished) setNode('oracle-evidence', 'active');
  else setNode('oracle-evidence', null);

  if (body.phase === 'complete') setNode('response', failed ? 'error' : 'done');
  else if (finished) setNode('response', 'active');
  else setNode('response', null);

  renderEvents(events);
  const result = body.result || run?.result || {};
  if (result.final_response) {
    $('response').className = 'result-copy';
    $('response').textContent = result.final_response;
  } else if (result.error || body.error) {
    $('response').className = 'notice';
    $('response').textContent = result.error || body.error;
  } else {
    $('response').className = 'empty';
    $('response').textContent = hasPhase(events, 'provider_request')
      ? 'The selected provider is generating a response…'
      : 'The outer loop is preparing the run…';
  }
}

async function pollExecution() {
  if (!state.runId) return;
  try {
    const body = await api(`/api/executions/${encodeURIComponent(state.runId)}`);
    applyExecution(body);
    if (!body.terminal) {
      state.pollTimer = setTimeout(pollExecution, 350);
    } else {
      $('run').disabled = false;
      $('run').classList.remove('loading');
    }
  } catch (error) {
    $('run').disabled = false;
    $('run').classList.remove('loading');
    toast(error.message);
  }
}

async function startExecution(event) {
  event.preventDefault();
  const query = $('query').value.trim();
  if (!query) return;
  clearTimeout(state.pollTimer);
  resetFlow();
  $('response').className = 'empty';
  $('response').textContent = 'Starting live execution…';
  $('events').className = 'empty';
  $('events').textContent = 'Waiting for the first Oracle event row…';
  $('run').disabled = true;
  $('run').classList.add('loading');
  try {
    const body = await api('/api/executions', {
      method: 'POST',
      body: JSON.stringify({query, harness: $('harness').value, thread_id: threadId()}),
    });
    state.runId = body.run_id;
    applyExecution(body);
    pollExecution();
  } catch (error) {
    $('run').disabled = false;
    $('run').classList.remove('loading');
    toast(error.message);
  }
}

function renderModal(body) {
  $('modal-title').textContent = body.title;
  $('modal-description').textContent = body.description;
  const windowData = body.context_window || {};
  const sections = windowData.sections || [];
  $('modal-body').innerHTML = `
    <div class="context-meta">
      <span class="badge ${body.selected ? 'accent' : ''}">${body.selected ? 'selected harness' : esc(windowData.phase || 'ready')}</span>
      <span class="badge">${esc(windowData.provider || 'host')}</span>
      <span class="badge">${esc(windowData.model || 'no model')}</span>
      <span class="badge">~${esc(windowData.estimated_tokens || 0)} tokens</span>
    </div>
    ${sections.map(section => `
      <section class="context-section">
        <h3>${esc(section.title)}</h3>
        <div class="source-meta">${esc(section.kind)} · ${esc(section.source)} · ~${esc(section.estimated_tokens)} tokens</div>
        <pre>${esc(section.content)}</pre>
      </section>`).join('') || '<div class="empty">This node has no assembled context yet.</div>'}
    <div class="notice">${esc(windowData.note || 'Private reasoning is not recorded.')}</div>`;
  $('node-modal').showModal();
}

async function openNode(nodeId) {
  try {
    const query = state.runId ? `?run_id=${encodeURIComponent(state.runId)}` : '';
    renderModal(await api(`/api/nodes/${encodeURIComponent(nodeId)}${query}`));
  } catch (error) {
    toast(error.message);
  }
}

async function loadStatus() {
  const status = await api('/api/status');
  $('status-dot').classList.toggle('ready', Boolean(status.ready));
  $('status-title').textContent = status.ready
    ? `MemoRizz ${status.memorizz_version} · Oracle ready`
    : 'Runtime unavailable';
  $('status-detail').textContent = status.ready
    ? `${status.oracle_version} · ${status.embedding_model} embeddings · ${status.run_count} durable runs`
    : (status.error || status.remediation);
  $('run').disabled = !status.ready;
  if (!status.ready) return;
  const byName = Object.fromEntries(status.harnesses.map(item => [item.name, item]));
  for (const [name, labelId] of [
    ['openai-live', 'openai-label'],
    ['anthropic-live', 'anthropic-label'],
    ['deepseek-live', 'deepseek-label'],
  ]) {
    const item = byName[name] || {};
    $(labelId).textContent = item.ready
      ? `${item.models?.[0] || name} · ready`
      : (item.error || 'not ready');
    const option = [...$('harness').options].find(candidate => candidate.value === name);
    if (option) option.disabled = !item.ready;
    if (!item.ready) node(name).classList.add('dim');
  }
}

$('query-form').addEventListener('submit', startExecution);
document.querySelectorAll('[data-node]').forEach(element => {
  element.addEventListener('click', () => openNode(element.dataset.node));
});
$('modal-close').onclick = () => $('node-modal').close();
$('node-modal').addEventListener('click', event => {
  if (event.target === $('node-modal')) $('node-modal').close();
});

loadStatus().catch(error => toast(error.message));
