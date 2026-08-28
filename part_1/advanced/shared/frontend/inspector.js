(function () {
  'use strict';

  const escapeHTML = (value) => String(value ?? '').replace(/[&<>'"]/g, (char) => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', "'": '&#39;', '"': '&quot;'
  })[char]);
  const state = { open: false, tab: 'context', sources: [], source: null, table: null, offset: 0, limit: 40 };
  const byId = (id) => document.getElementById(id);

  async function request(path) {
    const response = await fetch(path, { headers: { Accept: 'application/json' } });
    const body = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(body.detail || `${response.status} ${response.statusText}`);
    return body;
  }

  function mount() {
    const existing = byId('advanced-inspector');
    if (existing?.classList.contains('aii-dock')) return;
    const dock = existing || document.createElement('section');
    dock.id = 'advanced-inspector';
    dock.className = 'aii-dock';
    dock.setAttribute('aria-label', 'LLM context window and application data explorer');
    dock.innerHTML = `
      <div class="aii-shell">
        <button class="aii-handle" id="aii-toggle" aria-expanded="false" aria-controls="aii-body">
          <span class="aii-title"><i class="aii-mark">CTX</i><strong>Harness inspector</strong><span>LLM context window · application data explorer</span></span>
          <span class="aii-live"><i></i><span id="aii-live-label">read-only</span></span>
          <span class="aii-chevron">⌃</span>
        </button>
        <div class="aii-body" id="aii-body" hidden>
          <header class="aii-toolbar">
            <div class="aii-tabs">
              <button class="aii-tab active" data-aii-tab="context">Context window</button>
              <button class="aii-tab" data-aii-tab="data">Data explorer</button>
            </div>
            <button class="aii-action" id="aii-refresh">Refresh evidence</button>
          </header>
          <section class="aii-pane" id="aii-context-pane">
            <div class="aii-empty">Open the inspector to load the current assembled model input.</div>
          </section>
          <section class="aii-pane" id="aii-data-pane" hidden>
            <div class="aii-empty">Open the data explorer to inspect the application schema.</div>
          </section>
        </div>
      </div>`;
    if (!dock.isConnected) document.body.appendChild(dock);
    byId('aii-toggle').addEventListener('click', () => toggle());
    byId('aii-refresh').addEventListener('click', () => refresh());
    dock.querySelectorAll('[data-aii-tab]').forEach((button) => button.addEventListener('click', () => selectTab(button.dataset.aiiTab)));
    window.AdvancedInspector = {
      refresh,
      refreshContext: async () => { state.tab = 'context'; if (state.open) await loadContext(); },
      refreshData: async () => { state.tab = 'data'; if (state.open) await loadSources(); },
      open: () => toggle(true),
      selectTab
    };
  }

  async function toggle(force) {
    state.open = force ?? !state.open;
    byId('advanced-inspector').classList.toggle('open', state.open);
    byId('aii-body').hidden = !state.open;
    byId('aii-toggle').setAttribute('aria-expanded', String(state.open));
    document.body.classList.toggle('aii-open', state.open);
    if (state.open) await refresh();
  }

  function selectTab(tab) {
    state.tab = tab;
    document.querySelectorAll('[data-aii-tab]').forEach((button) => button.classList.toggle('active', button.dataset.aiiTab === tab));
    byId('aii-context-pane').hidden = tab !== 'context';
    byId('aii-data-pane').hidden = tab !== 'data';
    if (state.open) refresh();
  }

  async function refresh() {
    const button = byId('aii-refresh');
    if (button) button.disabled = true;
    try {
      if (state.tab === 'context') await loadContext();
      else await loadSources();
      byId('aii-live-label').textContent = 'schema-scoped · sensitive fields redacted';
    } catch (error) {
      const target = state.tab === 'context' ? byId('aii-context-pane') : byId('aii-data-pane');
      target.innerHTML = `<div class="aii-empty aii-error">${escapeHTML(error.message)}</div>`;
    } finally {
      if (button) button.disabled = false;
    }
  }

  async function loadContext() {
    const payload = await request('/api/inspector/context');
    const used = Number(payload.estimated_tokens || 0);
    const max = payload.max_tokens ? Number(payload.max_tokens) : null;
    const sections = payload.sections || [];
    byId('aii-context-pane').innerHTML = `
      <div class="aii-context-layout">
        <aside class="aii-context-summary">
          <span class="aii-eyebrow">${escapeHTML(payload.phase || 'assembled')}</span>
          <h3>${payload.actual_model_call ? 'Actual model input' : 'Would-be model input'}</h3>
          <div class="aii-metrics">
            <div class="aii-metric"><b>${sections.length}</b><span>sections</span></div>
            <div class="aii-metric"><b>~${used.toLocaleString()}</b><span>tokens</span></div>
            <div class="aii-metric"><b>${escapeHTML(payload.provider || 'none')}</b><span>provider</span></div>
            <div class="aii-metric"><b>${max ? `${Math.round(used / max * 100)}%` : '—'}</b><span>budget used</span></div>
          </div>
          <p class="aii-claim"><strong>${escapeHTML(payload.model || 'no model')}</strong><br>${escapeHTML(payload.claim_boundary || '')}</p>
          ${payload.note ? `<p class="aii-claim">${escapeHTML(payload.note)}</p>` : ''}
        </aside>
        <div class="aii-context-sections">
          ${sections.length ? sections.map((section, index) => `
            <details class="aii-section" ${index === 0 ? 'open' : ''}>
              <summary><strong>${escapeHTML(section.title)}</strong><span>${escapeHTML(section.kind)} · ${Number(section.estimated_tokens || 0).toLocaleString()} tokens · ${escapeHTML(section.source)}</span></summary>
              <pre>${escapeHTML(section.content)}</pre>
            </details>`).join('') : '<div class="aii-empty">No assembled context has been recorded yet.</div>'}
        </div>
      </div>`;
  }

  async function loadSources() {
    const payload = await request('/api/inspector/sources');
    state.sources = payload.sources || [];
    if (!state.source && state.sources.length) state.source = state.sources[0].id;
    const activeSource = state.sources.find((item) => item.id === state.source) || state.sources[0];
    if (!activeSource) {
      byId('aii-data-pane').innerHTML = '<div class="aii-empty">No application data sources are available yet.</div>';
      return;
    }
    state.source = activeSource.id;
    if (!state.table || !activeSource.tables.some((item) => item.name === state.table)) {
      state.table = activeSource.tables[0]?.name || null;
      state.offset = 0;
    }
    byId('aii-data-pane').innerHTML = `
      <div class="aii-data-layout">
        <aside class="aii-data-sidebar">${state.sources.map((source) => `
          <section class="aii-source">
            <div class="aii-source-head"><strong>${escapeHTML(source.label)}</strong><span>${escapeHTML(source.kind)} · ${source.table_count} tables</span></div>
            <div class="aii-table-list">${source.tables.map((table) => `
              <button class="aii-table-button ${source.id === state.source && table.name === state.table ? 'active' : ''}" data-source="${escapeHTML(source.id)}" data-table="${escapeHTML(table.name)}">${escapeHTML(table.name)}<span>${table.row_count ?? '—'}</span></button>
            `).join('') || '<span class="aii-claim">No tables yet</span>'}</div>
          </section>`).join('')}</aside>
        <section class="aii-data-main">
          <header class="aii-data-head"><div><span class="aii-eyebrow">${escapeHTML(activeSource.label)}</span><h3 id="aii-table-title">${escapeHTML(state.table || 'Select a table')}</h3></div><div class="aii-pagination"><button class="aii-page-button" id="aii-prev">←</button><span id="aii-page">—</span><button class="aii-page-button" id="aii-next">→</button></div></header>
          <div class="aii-grid" id="aii-grid"><div class="aii-empty">Loading rows…</div></div>
        </section>
      </div>`;
    byId('aii-data-pane').querySelectorAll('[data-table]').forEach((button) => button.addEventListener('click', async () => {
      state.source = button.dataset.source; state.table = button.dataset.table; state.offset = 0; await loadSources();
    }));
    if (state.table) await loadRows();
  }

  async function loadRows() {
    const payload = await request(`/api/inspector/sources/${encodeURIComponent(state.source)}/tables/${encodeURIComponent(state.table)}/rows?limit=${state.limit}&offset=${state.offset}`);
    const rows = payload.rows || [];
    const columns = [...new Set(rows.flatMap((row) => Object.keys(row)))];
    byId('aii-table-title').textContent = payload.table;
    byId('aii-page').textContent = `${payload.row_count ? state.offset + 1 : 0}–${Math.min(state.offset + rows.length, payload.row_count)} of ${payload.row_count}`;
    byId('aii-prev').disabled = state.offset === 0;
    byId('aii-next').disabled = state.offset + state.limit >= payload.row_count;
    byId('aii-prev').onclick = async () => { state.offset = Math.max(0, state.offset - state.limit); await loadRows(); };
    byId('aii-next').onclick = async () => { state.offset += state.limit; await loadRows(); };
    byId('aii-grid').innerHTML = rows.length ? `<table><thead><tr>${columns.map((column) => `<th>${escapeHTML(column)}</th>`).join('')}</tr></thead><tbody>${rows.map((row) => `<tr>${columns.map((column) => `<td>${escapeHTML(typeof row[column] === 'object' && row[column] !== null ? JSON.stringify(row[column]) : row[column])}</td>`).join('')}</tr>`).join('')}</tbody></table>` : '<div class="aii-empty">This table has no rows.</div>';
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', mount);
  else mount();
})();
