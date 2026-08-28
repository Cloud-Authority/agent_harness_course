const $ = (id) => document.getElementById(id);
let threadId = null;

const escapeHtml = (value) => String(value ?? '').replace(/[&<>'"]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','"':'&quot;'}[c]));
const toast = (message) => { $('toast').textContent = message; $('toast').classList.add('show'); setTimeout(() => $('toast').classList.remove('show'), 3200); };
async function api(path, options={}) {
  const response = await fetch(path, {headers:{'Content-Type':'application/json'}, ...options});
  const body = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(body.detail || `${response.status} ${response.statusText}`);
  return body;
}
function busy(button, value) { button.disabled = value; button.classList.toggle('loading', value); }

async function loadStatus() {
  const status = await api('/api/status');
  $('status-dot').classList.toggle('ready', !!status.ready);
  $('status-title').textContent = status.ready ? 'Oracle persistence ready' : 'Oracle unavailable';
  const p = status.persistence || {};
  const memory = p.agent_memory || {};
  const catalog = p.catalog || {};
  const counts = catalog.counts || {};
  const alignment = status.notebook_alignment || {};
  $('status-detail').textContent = status.ready ? `${p.checkpointer} · ${memory.provider || 'Agent Memory'} · ${catalog.index || 'semantic vector catalogs'} · ${counts.skills || 0} skills · ${counts.tools || 0} tools · Oracle ${p.oracle_version || 'connected'}` : (status.error || status.remediation);
  $('notebook-alignment').textContent = alignment.teaching_graph_nodes ? `${alignment.teaching_graph_nodes}-node teaching graph · ${alignment.persistence_profile || 'Oracle-only'}` : 'notebook reference';
  $('start').disabled = !status.ready;
  if (status.workflow_view) renderWorkflow(status.workflow_view);
}

function timeline(items, titleKey, metaFn) {
  if (!items?.length) return '<div class="empty">No records yet.</div>';
  return `<div class="timeline">${items.map((item, i) => `<div class="timeline-item"><div class="timeline-index">${String(i+1).padStart(2,'0')}</div><div><div class="timeline-title">${escapeHtml(item[titleKey] || 'checkpoint')}</div><div class="timeline-meta">${escapeHtml(metaFn(item))}</div></div></div>`).join('')}</div>`;
}

const nodeWidth = (node) => node.kind === 'boundary' ? 92 : 158;
function workflowPath(edge, nodes) {
  const source = nodes.get(edge.source);
  const target = nodes.get(edge.target);
  if (!source || !target) return '';
  const x1 = Number(source.x) + nodeWidth(source) / 2;
  const y1 = Number(source.y);
  const x2 = Number(target.x) - nodeWidth(target) / 2;
  const y2 = Number(target.y);
  const bend = Math.max(28, (x2 - x1) * .45);
  return `M ${x1} ${y1} C ${x1 + bend} ${y1}, ${x2 - bend} ${y2}, ${x2} ${y2}`;
}

function renderWorkflow(view) {
  if (!view?.nodes?.length) return;
  const nodes = new Map(view.nodes.map(node => [node.id, node]));
  const allowed = new Set(['pending', 'ready', 'completed', 'paused', 'failed', 'skipped']);
  const edgeMarkup = (view.edges || []).map(edge => {
    const status = allowed.has(edge.status) ? edge.status : 'pending';
    const source = nodes.get(edge.source);
    const target = nodes.get(edge.target);
    const labelX = source && target ? (Number(source.x) + Number(target.x)) / 2 : 0;
    const labelY = source && target ? (Number(source.y) + Number(target.y)) / 2 - 10 : 0;
    return `<g class="workflow-edge status-${status}"><path d="${workflowPath(edge, nodes)}" marker-end="url(#workflow-arrow)"></path>${edge.label ? `<text x="${labelX}" y="${labelY}">${escapeHtml(edge.label)}</text>` : ''}</g>`;
  }).join('');
  const nodeMarkup = view.nodes.map(node => {
    const status = allowed.has(node.status) ? node.status : 'pending';
    const width = nodeWidth(node);
    return `<g class="workflow-node status-${status}" transform="translate(${Number(node.x)},${Number(node.y)})" tabindex="0" role="group" aria-label="${escapeHtml(node.label)}: ${escapeHtml(status)}"><rect x="${-width/2}" y="-38" width="${width}" height="76" rx="15"></rect><circle cx="${-width/2 + 15}" cy="-22" r="5"></circle><text class="workflow-node-label" x="0" y="-5" text-anchor="middle">${escapeHtml(node.label)}</text><text class="workflow-node-kind" x="0" y="16" text-anchor="middle">${escapeHtml(node.kind.replaceAll('_',' '))}</text><title>${escapeHtml(node.detail || '')}</title></g>`;
  }).join('');
  const svg = $('workflow-svg');
  const graphWidth = Math.max(1040, ...view.nodes.map(node => Number(node.x) + nodeWidth(node))) + 40;
  const graphHeight = Math.max(500, ...view.nodes.map(node => Number(node.y) + 90));
  svg.setAttribute('viewBox', `0 0 ${graphWidth} ${graphHeight}`);
  svg.style.width = `${graphWidth}px`;
  svg.style.maxWidth = 'none';
  svg.innerHTML = `<defs><marker id="workflow-arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse"><path d="M 0 0 L 10 5 L 0 10 z"></path></marker></defs>${edgeMarkup}${nodeMarkup}`;
  const label = String(view.run_status || 'not_started').replaceAll('_', ' ');
  $('workflow-status').textContent = label;
  $('workflow-status').className = `badge ${view.run_status === 'published' ? 'accent' : view.run_status === 'resumable' ? 'danger' : view.run_status === 'pending_approval' ? 'warn' : ''}`;
  const trace = view.trace || [];
  $('execution-trace').className = trace.length ? 'execution-trace' : 'execution-trace empty';
  $('execution-trace').innerHTML = trace.length ? trace.slice(-14).map((item, index) => `<div class="trace-event"><span class="trace-index">${String(Math.max(1, trace.length - 13 + index)).padStart(2,'0')}</span><span class="trace-node">${escapeHtml(item.node_id || 'control plane')}</span><strong>${escapeHtml(item.event_type)}</strong><time>${escapeHtml(item.timestamp || '')}</time></div>`).join('') : 'Start a run to populate the node-level execution trace.';
}

function render(data) {
  threadId = data.thread_id;
  const state = data.state || {};
  $('run-status').textContent = data.status.replaceAll('_',' ');
  $('run-status').className = `badge ${data.status === 'published' ? 'accent' : 'warn'}`;
  $('refresh').disabled = false;
  $('resume').disabled = !(data.status === 'resumable');
  $('approve').disabled = !(data.status === 'pending_approval');
  $('reject').disabled = !(data.status === 'pending_approval');
  $('start').textContent = 'Start another high-risk thread';
  const error = data.error || data.last_error;
  const promotion = state.promotion;
  $('notice').textContent = error ? `${error.type}: ${error.message}` : data.status === 'pending_approval' ? 'Execution is durably paused. Inspect the exact report and remediation envelope before deciding.' : data.status === 'published' ? `Publication verified. Promotion result: ${promotion?.status || 'pending'}. Start another thread to demonstrate recurrence.` : `Thread ${data.thread_id}`;
  $('metrics').innerHTML = `<div class="metric"><div class="metric-value">${data.checkpoint_history?.length || 0}</div><div class="metric-label">checkpoints</div></div><div class="metric"><div class="metric-value">${data.episodic_audit?.length || 0}</div><div class="metric-label">audit events</div></div><div class="metric"><div class="metric-value">${state.loaded_skills?.length || 0}</div><div class="metric-label">full skills</div></div><div class="metric"><div class="metric-value">${state.sandbox_trace?.length || 0}</div><div class="metric-label">sandbox runs</div></div>`;
  const findings = state.findings || [];
  $('state-rows').innerHTML = [
    ['next node', data.next?.join(', ') || 'END'],
    ['risk route', state.draft?.risk || '—'],
    ['risk score', state.risk_assessment?.score ?? '—'],
    ['findings', findings.length],
    ['sanctions', state.sanctions_result?.status || '—'],
    ['outcome', state.outcome || '—'],
    ['learning', promotion?.status || '—']
  ].map(([a,b]) => `<div class="row"><span class="row-label">${escapeHtml(a)}</span><span class="row-value">${escapeHtml(b)}</span></div>`).join('');
  const candidates = state.skill_candidates || [];
  const selectedSkillNames = new Set((state.loaded_skills || []).map(item => item.name));
  $('skillbox').className = candidates.length ? 'stack' : 'empty';
  $('skillbox').innerHTML = candidates.length ? candidates.map(item => `<div class="row"><span><strong>${escapeHtml(item.name)}</strong><br><span class="kicker">${escapeHtml(item.description)} · sha ${escapeHtml(String(item.sha || '').slice(0,12))}</span></span><span class="badge ${selectedSkillNames.has(item.name) ? 'accent' : ''}">${selectedSkillNames.has(item.name) ? 'full body loaded' : 'manifest only'}</span></div>`).join('') : 'Start a run to retrieve skills by meaning.';
  const toolCandidates = state.tool_candidates || [];
  const selectedTools = new Set(state.selected_tools || []);
  $('toolbox').className = toolCandidates.length ? 'stack' : 'empty';
  $('toolbox').innerHTML = toolCandidates.length ? toolCandidates.map(item => `<div class="row"><span><strong>${escapeHtml(item.name)}</strong><br><span class="kicker">${escapeHtml(item.category)} · cosine distance ${escapeHtml(item.distance)}</span></span><span class="badge ${selectedTools.has(item.name) ? 'accent' : ''}">${selectedTools.has(item.name) ? 'bound' : 'not bound'}</span></div>`).join('') : 'Start a run to retrieve the top-k tool contracts.';
  const sandboxTrace = state.sandbox_trace || [];
  $('sandbox-trace').className = sandboxTrace.length ? 'stack' : 'empty';
  $('sandbox-trace').innerHTML = sandboxTrace.length ? sandboxTrace.map((item, index) => `<details class="row" ${index === sandboxTrace.length - 1 ? 'open' : ''}><summary><strong>${String(index+1).padStart(2,'0')} · ${escapeHtml(item.tool)}</strong> <span class="badge ${item.output?.host_recomputation_matched ? 'accent' : ''}">${item.execution?.isolation_proven ? 'remote isolated' : 'test profile'} · ${item.execution?.session_closed ? 'closed' : 'open'}</span></summary><pre class="code">INPUT\n${escapeHtml(JSON.stringify(item.input, null, 2))}\n\nEXECUTION\n${escapeHtml(JSON.stringify(item.execution, null, 2))}\n\nOUTPUT\n${escapeHtml(JSON.stringify(item.output, null, 2))}</pre></details>`).join('') : 'No sandbox executions yet.';
  $('promotion').className = promotion ? 'code' : 'empty';
  $('promotion').textContent = promotion ? JSON.stringify(promotion, null, 2) : 'The promotion node runs after outcome capture.';
  const ledger = state.idempotency || [];
  $('idempotency').className = ledger.length ? 'stack' : 'empty';
  $('idempotency').innerHTML = ledger.length ? ledger.map(x => `<div class="row"><span class="row-label">${escapeHtml(x.operation)}</span><span class="badge ${x.reused ? 'accent' : ''}">${x.reused ? 'reused' : 'committed'}</span></div>`).join('') : 'Run the failure path to reveal reuse.';
  const envelope = data.interrupts?.[0] || state.approval;
  $('approval').className = envelope ? 'code' : 'empty';
  $('approval').textContent = envelope ? JSON.stringify(envelope, null, 2) : 'The envelope appears at the interrupt.';
  $('checkpoints').className = data.checkpoint_history?.length ? '' : 'empty';
  $('checkpoints').innerHTML = timeline(data.checkpoint_history, 'next', x => `step ${x.step ?? '—'} · ${x.source || 'checkpoint'} · ${x.created_at}`);
  const audits = [...(data.episodic_audit || [])].sort((a,b) => String(a.timestamp).localeCompare(String(b.timestamp)));
  $('audit').className = audits.length ? '' : 'empty';
  $('audit').innerHTML = timeline(audits, 'event_type', x => `${x.timestamp} · ${JSON.stringify(x.details)}`);
  const publication = state.publication;
  $('artifact').className = publication ? 'code' : 'empty';
  $('artifact').textContent = publication ? JSON.stringify(publication, null, 2) : 'Nothing has been published.';
  renderWorkflow(data.workflow_view);
}

async function action(button, fn) {
  busy(button, true);
  try { render(await fn()); } catch (error) { toast(error.message); }
  finally { busy(button, false); if (button === $('start')) $('start').disabled = false; }
}
$('start').addEventListener('click', () => action($('start'), () => api('/api/runs', {method:'POST', body:JSON.stringify({requested_by:$('operator').value, fail_once_at:$('failure').value})})));
$('resume').addEventListener('click', () => action($('resume'), () => api(`/api/runs/${encodeURIComponent(threadId)}/resume`, {method:'POST'})));
$('approve').addEventListener('click', () => action($('approve'), () => api(`/api/runs/${encodeURIComponent(threadId)}/decision`, {method:'POST', body:JSON.stringify({approved:true, decided_by:$('operator').value, comment:'Exact supplier report reviewed in the control room'})})));
$('reject').addEventListener('click', () => action($('reject'), () => api(`/api/runs/${encodeURIComponent(threadId)}/decision`, {method:'POST', body:JSON.stringify({approved:false, decided_by:$('operator').value, comment:'Supplier report rejected in the control room'})})));
$('refresh').addEventListener('click', () => action($('refresh'), () => api(`/api/runs/${encodeURIComponent(threadId)}`)));
loadStatus().catch(error => toast(error.message));
