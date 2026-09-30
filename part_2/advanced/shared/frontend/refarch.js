/* A technical reference architecture: tiers, components with icons, labelled data flows, a legend, and a
   player that simulates one execution step by step. Standalone: it needs only a root element and a spec.

   spec = {
     tiers: [{ id, title, note }],                           // drawn top to bottom
     components: [{ id, tier, col, name, tech, kind, note }], // kind picks the icon and the legend entry
     flows: [{ id, from, to, label, kind, dy }],             // kind: request | data | control | store | event
     runs: [{ id, title, blurb, steps: [{ flow, note, state }] }],
   }
   RefArch.render(root, spec) draws it and wires the player. */
const RefArch = (() => {
  const ICONS = {
    person: '<circle cx="12" cy="8" r="4"/><path d="M4 21c0-4 3.6-7 8-7s8 3 8 7"/>',
    browser: '<rect x="3" y="4" width="18" height="16" rx="2"/><path d="M3 9h18M7 6.5h.01M10 6.5h.01"/>',
    api: '<rect x="3" y="5" width="18" height="6" rx="1.5"/><rect x="3" y="13" width="18" height="6" rx="1.5"/><path d="M7 8h.01M7 16h.01"/>',
    loop: '<path d="M4 12a8 8 0 0 1 14-5.3M20 12a8 8 0 0 1-14 5.3"/><path d="M18 3v4h-4M6 21v-4h4"/>',
    model: '<path d="M12 3a4 4 0 0 1 4 4c2 0 4 2 4 4s-2 4-4 4a4 4 0 0 1-8 0c-2 0-4-2-4-4s2-4 4-4a4 4 0 0 1 4-4z"/><path d="M12 7v12M8 11h8"/>',
    decide: '<circle cx="12" cy="13" r="8"/><path d="M12 13l4-4M12 5V3M5 13H3M21 13h-2"/>',
    gate: '<path d="M4 20V6a2 2 0 0 1 2-2h12a2 2 0 0 1 2 2v14"/><path d="M8 12l3 3 5-6"/>',
    tools: '<path d="M14.7 6.3a4 4 0 0 0-5.4 5.4L3 18v3h3l6.3-6.3a4 4 0 0 0 5.4-5.4l-2.6 2.6-2.1-2.1z"/>',
    mcp: '<circle cx="6" cy="12" r="2.5"/><circle cx="18" cy="6" r="2.5"/><circle cx="18" cy="18" r="2.5"/><path d="M8.3 11l7.4-3.7M8.3 13l7.4 3.7"/>',
    search: '<circle cx="11" cy="11" r="6"/><path d="M20 20l-4.5-4.5"/>',
    database: '<ellipse cx="12" cy="6" rx="8" ry="3"/><path d="M4 6v12c0 1.7 3.6 3 8 3s8-1.3 8-3V6"/><path d="M4 12c0 1.7 3.6 3 8 3s8-1.3 8-3"/>',
    vector: '<rect x="4" y="4" width="16" height="16" rx="2"/><path d="M4 10h16M4 14h16M10 4v16M14 4v16"/>',
    memory: '<rect x="6" y="6" width="12" height="12" rx="2"/><path d="M9 3v3M15 3v3M9 18v3M15 18v3M3 9h3M3 15h3M18 9h3M18 15h3"/>',
    checkpoint: '<path d="M5 21V4"/><path d="M5 4h12l-3 4 3 4H5"/>',
    ledger: '<rect x="4" y="3" width="16" height="18" rx="2"/><path d="M8 8h8M8 12h8M8 16h5"/>',
    timer: '<circle cx="12" cy="13" r="8"/><path d="M12 9v4l3 2M10 2h4"/>',
    mail: '<rect x="3" y="5" width="18" height="14" rx="2"/><path d="M3 7l9 6 9-6"/>',
    calendar: '<rect x="3" y="5" width="18" height="16" rx="2"/><path d="M3 10h18M8 3v4M16 3v4"/>',
    doc: '<path d="M6 3h8l4 4v14H6z"/><path d="M14 3v4h4M9 12h6M9 16h6"/>',
    file: '<path d="M6 3h8l4 4v14H6z"/><path d="M14 3v4h4"/>',
    shield: '<path d="M12 3l8 3v6c0 5-3.5 8-8 9-4.5-1-8-4-8-9V6z"/><path d="M9 12l2 2 4-4"/>',
    cloud: '<path d="M7 18a4 4 0 0 1-.6-8A6 6 0 0 1 18 9a4 4 0 0 1 1 8.9H7z"/>',
    booking: '<rect x="3" y="6" width="18" height="12" rx="2"/><path d="M3 11h18M7 15h4"/>',
    bell: '<path d="M6 16V11a6 6 0 0 1 12 0v5l2 2H4z"/><path d="M10 21h4"/>',
    sse: '<path d="M4 12h4l2-6 4 12 2-6h4"/>',
    output: '<path d="M4 4h10l6 6v10H4z"/><path d="M14 4v6h6M8 15l3 3 5-6"/>',
    agent: '<rect x="4" y="7" width="16" height="12" rx="3"/><circle cx="9" cy="13" r="1.5"/><circle cx="15" cy="13" r="1.5"/><path d="M12 3v4M8 19v2M16 19v2"/>',
    skills: '<path d="M4 6h16v12H4z"/><path d="M8 10h8M8 14h5"/><path d="M4 6l2-3h12l2 3"/>',
  };
  const KINDS = {
    person: ["People", "person"], channel: ["Channel", "browser"], control: ["Control plane", "api"],
    model: ["Reasoning model", "model"], decide: ["System One model", "decide"], gate: ["Human gate", "gate"],
    tool: ["Tool or connector", "tools"], external: ["External service", "cloud"], store: ["Data store", "database"],
    output: ["Output", "output"], observe: ["Observability", "ledger"],
  };
  const esc = (v) => String(v ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const icon = (name) => `<svg viewBox="0 0 24 24" class="ra-icon" aria-hidden="true">${ICONS[name] || ICONS.api}</svg>`;

  const W = 196, H = 66, COLW = 214, TIERH = 128, LEFT = 128, TOP = 34;
  const place = (spec) => {
    const tierIndex = Object.fromEntries(spec.tiers.map((t, i) => [t.id, i]));
    const pos = {};
    for (const c of spec.components) pos[c.id] = { x: LEFT + c.col * COLW, y: TOP + tierIndex[c.tier] * TIERH + 26 };
    const cols = Math.max(...spec.components.map(c => c.col)) + 1;
    return { pos, width: LEFT + cols * COLW + 20, height: TOP + spec.tiers.length * TIERH + 10 };
  };
  const anchor = (a, b) => {
    // leave from the side of the node that faces the other node; prefer vertical when tiers differ
    const ac = { x: a.x + W / 2, y: a.y + H / 2 }, bc = { x: b.x + W / 2, y: b.y + H / 2 };
    if (Math.abs(bc.y - ac.y) > H) return { x: ac.x, y: bc.y > ac.y ? a.y + H : a.y };
    return { x: bc.x > ac.x ? a.x + W : a.x, y: ac.y };
  };
  const pathFor = (pa, pb) => {
    const s = anchor(pa, pb), e = anchor(pb, pa);
    const vertical = Math.abs(e.y - s.y) > Math.abs(e.x - s.x);
    return vertical ? `M${s.x},${s.y} C${s.x},${(s.y + e.y) / 2} ${e.x},${(s.y + e.y) / 2} ${e.x},${e.y}`
                    : `M${s.x},${s.y} C${(s.x + e.x) / 2},${s.y} ${(s.x + e.x) / 2},${e.y} ${e.x},${e.y}`;
  };

  const draw = (spec) => {
    const { pos, width, height } = place(spec);
    const tiers = spec.tiers.map((t, i) => `<g class="ra-tier"><rect x="8" y="${TOP + i * TIERH}" width="${width - 16}" height="${TIERH - 8}" rx="10"/><text x="20" y="${TOP + i * TIERH + 18}" class="ra-tier-title">${esc(t.title)}</text>${t.note ? `<text x="20" y="${TOP + i * TIERH + 32}" class="ra-tier-note">${esc(t.note)}</text>` : ""}</g>`).join("");
    const flows = spec.flows.map(f => {
      const d = pathFor(pos[f.from], pos[f.to]);
      return `<g class="ra-flow ra-flow-${f.kind || "data"}" data-flow="${esc(f.id)}"><path d="${d}" class="ra-edge" marker-end="url(#ra-arrow)"/><path d="${d}" class="ra-edge-glow"/></g>`;
    }).join("");
    const labels = spec.flows.map(f => {
      const s = anchor(pos[f.from], pos[f.to]), e = anchor(pos[f.to], pos[f.from]);
      const mx = (s.x + e.x) / 2 + (f.dx || 0), my = (s.y + e.y) / 2 + (f.dy || 0);
      return `<text x="${mx}" y="${my}" class="ra-label" data-flow-label="${esc(f.id)}">${esc(f.label)}</text>`;
    }).join("");
    const nodes = spec.components.map(c => {
      const p = pos[c.id], k = KINDS[c.kind] || KINDS.control;
      return `<g class="ra-node ra-kind-${c.kind}" data-node="${esc(c.id)}" transform="translate(${p.x},${p.y})" tabindex="0">
        <rect width="${W}" height="${H}" rx="10"/>
        <foreignObject x="10" y="11" width="30" height="44"><div xmlns="http://www.w3.org/1999/xhtml" class="ra-iconbox">${icon(c.icon || k[1])}</div></foreignObject>
        <text x="46" y="27" class="ra-name">${esc(c.name)}</text>
        <text x="46" y="45" class="ra-tech">${esc(c.tech || "")}</text></g>`;
    }).join("");
    return `<svg class="ra-svg" viewBox="0 0 ${width} ${height}" role="img" aria-label="Reference architecture">
      <defs><marker id="ra-arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="8" markerHeight="8" orient="auto-start-reverse"><path d="M0,0 L10,5 L0,10 z"/></marker></defs>
      ${tiers}${flows}${labels}${nodes}
      <circle class="ra-token" r="7" style="display:none"/></svg>`;
  };

  const legend = (spec) => {
    const kinds = [...new Set(spec.components.map(c => c.kind))].filter(k => KINDS[k]);
    const flowKinds = { request: "request", data: "data", control: "control", store: "write or read", event: "event or timer" };
    return `<div class="ra-legend"><div>${kinds.map(k => `<span class="ra-legend-item ra-kind-${k}">${icon(KINDS[k][1])}${esc(KINDS[k][0])}</span>`).join("")}</div>
      <div>${Object.entries(flowKinds).filter(([k]) => spec.flows.some(f => (f.kind || "data") === k)).map(([k, t]) => `<span class="ra-legend-item"><i class="ra-swatch ra-flow-${k}"></i>${t}</span>`).join("")}</div></div>`;
  };

  const render = (root, spec) => {
    root.innerHTML = `<div class="ra">
      <div class="ra-diagram-wrap">${draw(spec)}</div>${legend(spec)}
      <div class="ra-side"><div class="ra-detail" id="ra-detail"><strong>Select a component</strong><span>to read what it is, what it runs on and what flows through it.</span></div>
      <div class="ra-player"><div class="ra-player-head"><label>Simulate a run</label><select id="ra-run">${spec.runs.map(r => `<option value="${esc(r.id)}">${esc(r.title)}</option>`).join("")}</select>
        <div class="ra-controls"><button type="button" id="ra-play" class="primary small">Play</button><button type="button" id="ra-step" class="secondary small">Step</button><button type="button" id="ra-reset" class="secondary small">Reset</button><label class="ra-speed">speed <input id="ra-speed" type="range" min="1" max="4" value="2"></label></div></div>
        <p class="ra-blurb" id="ra-blurb"></p><ol class="ra-steps" id="ra-steps"></ol></div></div></div>`;
    const svg = root.querySelector(".ra-svg"), byId = Object.fromEntries(spec.components.map(c => [c.id, c]));
    const flowsById = Object.fromEntries(spec.flows.map(f => [f.id, f]));
    const detail = root.querySelector("#ra-detail");
    const showComponent = (id) => {
      const c = byId[id]; if (!c) return;
      const ins = spec.flows.filter(f => f.to === id).map(f => `${byId[f.from]?.name}: ${f.label}`);
      const outs = spec.flows.filter(f => f.from === id).map(f => `${f.label} → ${byId[f.to]?.name}`);
      detail.innerHTML = `<strong>${esc(c.name)}</strong><em>${esc(c.tech || "")}</em><span>${esc(c.note || "")}</span>
        ${ins.length ? `<b>Receives</b><ul>${ins.map(t => `<li>${esc(t)}</li>`).join("")}</ul>` : ""}${outs.length ? `<b>Sends</b><ul>${outs.map(t => `<li>${esc(t)}</li>`).join("")}</ul>` : ""}`;
      root.querySelectorAll(".ra-node").forEach(n => n.classList.toggle("selected", n.dataset.node === id));
    };
    root.querySelectorAll(".ra-node").forEach(n => { n.onclick = () => showComponent(n.dataset.node); n.onkeydown = (e) => { if (e.key === "Enter") showComponent(n.dataset.node); }; });

    // the player
    let run = spec.runs[0], index = -1, timer = null, animating = false;
    const stepsBox = root.querySelector("#ra-steps"), blurb = root.querySelector("#ra-blurb"), token = svg.querySelector(".ra-token");
    const playButton = root.querySelector("#ra-play");
    const listSteps = () => { blurb.textContent = run.blurb || ""; stepsBox.innerHTML = run.steps.map((s, i) => { const f = flowsById[s.flow]; return `<li data-i="${i}"><b>${esc(byId[f?.from]?.name || "")}</b> → <b>${esc(byId[f?.to]?.name || "")}</b><span>${esc(f?.label || "")}</span><em>${esc(s.note || "")}</em>${s.state ? `<code>${esc(s.state)}</code>` : ""}</li>`; }).join(""); };
    const clear = () => { root.querySelectorAll(".ra-node.active, .ra-node.done, .ra-flow.active, .ra-flow.done").forEach(n => n.classList.remove("active", "done")); root.querySelectorAll(".ra-steps li").forEach(l => l.classList.remove("active", "done")); token.style.display = "none"; };
    const reset = () => { clearTimeout(timer); timer = null; animating = false; index = -1; clear(); playButton.textContent = "Play"; };
    const speed = () => Number(root.querySelector("#ra-speed").value);
    const animateAlong = (path, done) => {
      const length = path.getTotalLength(); const duration = 1400 / speed(); const start = performance.now(); token.style.display = "";
      const frame = (now) => { const t = Math.min(1, (now - start) / duration); const p = path.getPointAtLength(t * length); token.setAttribute("cx", p.x); token.setAttribute("cy", p.y); if (t < 1 && animating) requestAnimationFrame(frame); else done(); };
      requestAnimationFrame(frame);
    };
    const playStep = (then) => {
      if (index >= run.steps.length - 1) { playButton.textContent = "Play"; timer = null; animating = false; return; }
      index += 1; const step = run.steps[index], flow = flowsById[step.flow];
      root.querySelectorAll(".ra-node.active, .ra-flow.active").forEach(n => { n.classList.remove("active"); n.classList.add("done"); });
      root.querySelectorAll(".ra-steps li").forEach((l, i) => { l.classList.toggle("active", i === index); l.classList.toggle("done", i < index); });
      const li = stepsBox.querySelector(`li[data-i="${index}"]`); if (li) li.scrollIntoView({ block: "nearest", behavior: "smooth" });
      if (!flow) { then && then(); return; }
      const g = svg.querySelector(`.ra-flow[data-flow="${flow.id}"]`); g && g.classList.add("active");
      svg.querySelector(`.ra-node[data-node="${flow.from}"]`)?.classList.add("active");
      animating = true;
      animateAlong(g.querySelector(".ra-edge"), () => { animating = false; svg.querySelector(`.ra-node[data-node="${flow.to}"]`)?.classList.add("active"); showComponent(flow.to); then && then(); });
    };
    const play = () => {
      if (timer || animating) { clearTimeout(timer); timer = null; animating = false; playButton.textContent = "Play"; return; }
      if (index >= run.steps.length - 1) reset();
      playButton.textContent = "Pause";
      const loop = () => playStep(() => { if (index < run.steps.length - 1 && playButton.textContent === "Pause") timer = setTimeout(loop, 500 / speed()); else { playButton.textContent = "Play"; timer = null; } });
      loop();
    };
    playButton.onclick = play;
    root.querySelector("#ra-step").onclick = () => { if (animating) return; clearTimeout(timer); timer = null; playButton.textContent = "Play"; playStep(); };
    root.querySelector("#ra-reset").onclick = reset;
    root.querySelector("#ra-run").onchange = (e) => { run = spec.runs.find(r => r.id === e.target.value); reset(); listSteps(); };
    listSteps();
    return { showComponent, reset };
  };
  return { render, ICONS };
})();
