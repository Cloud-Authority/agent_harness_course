/* ERPA custom-harness appbook — no-build shell adapted from the Oracle Developer Hub palo-stack appbook. */
const CHAPTERS = [
  { id:"foundation", n:1, title:"Reference Architecture", blurb:"Follow data through the final Kata Store, the custom harness, its execution boundaries and the Oracle AI Database substrate.", endpoint:"/api/foundation/status", tag:"End-to-end technical map", kind:"architecture" },
  { id:"memory_layer", n:2, title:"Memory & ScratchFS", blurb:"Chat through the LangGraph agent, inspect each durable-memory and filesystem write, then explicitly promote selected ScratchFS notes.", endpoint:"/api/memory_layer/status", tag:"OAMP · SecureFile · trigger", kind:"memory" },
  { id:"semantic_layer", n:3, title:"Living Semantic Layer", blurb:"Run the same question with literal schema matching and with governed views, comments, hints, metrics and V$SQL-derived meaning.", endpoint:"/api/semantic_layer/status", tag:"Controlled A/B comparison", kind:"semantic" },
  { id:"retrieval", n:4, title:"Retrieval", blurb:"Send one query through keyword, Oracle vector, hybrid and reranked retrieval; inspect every answer and assembled context window.", endpoint:"/api/retrieval/status", tag:"Four retrieval strategies", kind:"retrieval" },
  { id:"skills", n:5, title:"Skills", blurb:"Retrieve compact ACTIVE skill manifests, inspect ranking, and watch the harness disclose only the selected procedure body.", endpoint:"/api/skills/status", tag:"Progressive disclosure", kind:"skills" },
  { id:"tools_and_mcp", n:6, title:"Trusted Tools", blurb:"The Custom Toolbox retrieves schemas by meaning, then validates and invokes only allowlisted functions. Generated code has one route: E2B.", endpoint:"/api/tools_and_mcp/status", tag:"CustomToolbox · E2B", actions:[{label:"Discover tool schemas",path:"/api/tools_and_mcp/retrieve",field:"query",placeholder:"What should ERPA do?",value:"Why did WarmLayer spike in the UK last week?"}] },
  { id:"the_loop", n:7, title:"LangGraph Loop", blurb:"Watch selective context → Claude Opus 4.8 adaptive thinking → bounded tools → OAMP persist, with OracleSaver at every super-step.", endpoint:"/api/the_loop/status", tag:"Claude · OracleSaver", actions:[{label:"Stream traced turn",path:"/api/the_loop/turn",stream:"/api/the_loop/stream",field:"message",placeholder:"Talk to ERPA",value:"Morning brief."}] },
  { id:"cache", n:8, title:"Semantic Cache", blurb:"Compare the same conversation with the graph forced to run and with OracleSemanticCache enabled, including wall time, tokens and trace shape.", endpoint:"/api/cache/status", tag:"langchain-oracledb 1.5.0", kind:"cache" },
  { id:"mission_control", n:9, title:"Mission Control", blurb:"Run the complete assistant with LangSmith traces, E2B artifacts, Oracle checkpoints and DBMS_SCHEDULER delivery.", endpoint:"/api/mission_control/status", tag:"Trace · schedule · evidence", actions:[
    {label:"Send to ERPA",path:"/api/mission_control/chat",field:"message",placeholder:"Talk to ERPA",value:"Show me ThermaCore stock across regions."},
    {label:"Run scheduled brief now",path:"/api/mission_control/schedule/run-now",field:null}
  ] },
  { id:"storefront", n:10, title:"Kata Store", blurb:"Shop the same product and inventory rows ERPA reasons over, complete a transactional checkout, and ask the floating assistant about catalog, stock and performance.", endpoint:"/api/storefront/catalog", tag:"Commerce · live inventory · ERPA", kind:"storefront" }
];

const $ = (selector) => document.querySelector(selector);
const escapeHTML = (value) => String(value ?? "").replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
let currentResult = null;
let currentView = "answer";
let storefrontProducts = [];
let storefrontCart = JSON.parse(localStorage.getItem("erpa-store-cart") || "{}");
let activeProductSku = null;
const explorerState = { tables:[], selected:null, result:null, offset:0, limit:50, events:[], active:new Map(), recent:new Map(), source:null };

function renderSidebar() {
  $("#chapters").innerHTML = CHAPTERS.map(c =>
    `<a class="nav" data-id="${c.id}" href="#${c.id}"><span class="num">${String(c.n).padStart(2,"0")}</span><span>${c.title}</span></a>`
  ).join("");
}
function markdown(text) {
  const lines = escapeHTML(text).split("\n");
  let list = false, out = "";
  for (const raw of lines) {
    const line = raw.replace(/\*\*(.*?)\*\*/g,"<strong>$1</strong>").replace(/\`(.*?)\`/g,"<code>$1</code>");
    if (line.startsWith("## ")) { if(list){out+="</ul>";list=false;} out+=`<h2>${line.slice(3)}</h2>`; }
    else if (line.startsWith("### ")) { if(list){out+="</ul>";list=false;} out+=`<h3>${line.slice(4)}</h3>`; }
    else if (line.startsWith("- ")) { if(!list){out+="<ul>";list=true;} out+=`<li>${line.slice(2)}</li>`; }
    else if (!line.trim()) { if(list){out+="</ul>";list=false;} }
    else { if(list){out+="</ul>";list=false;} out+=`<p>${line}</p>`; }
  }
  if(list) out+="</ul>";
  return out;
}
function traceHTML(trace) {
  if (!trace) return "";
  const spans = (trace.spans || []).map(s => `<div class="trace-step"><i class="dot ${escapeHTML(s.kind)}"></i><span class="trace-node">${escapeHTML(s.name)}</span><span class="trace-time">${Number(s.duration_ms||0).toFixed(2)} ms</span></div>`).join("");
  return `<div class="trace"><div class="trace-summary"><span class="pill">${escapeHTML(trace.shape || "trace")}</span><span class="pill">${trace.cache_hit ? "cache hit" : "cache miss"}</span><span class="pill">${trace.tokens || 0} tokens</span><span class="pill">${Number(trace.latency_ms||0).toFixed(1)} ms</span></div>${spans}</div>`;
}
function outputHTML(result) {
  if (currentView === "json" || !result) return `<pre class="json">${escapeHTML(JSON.stringify(result,null,2))}</pre>`;
  if (currentView === "trace") return result.trace ? traceHTML(result.trace) : `<pre class="json">${escapeHTML(JSON.stringify(result,null,2))}</pre>`;
  if (result.answer) {
    const chart = result.data && result.data.chart_svg ? `<div class="chart">${result.data.chart_svg}</div>` : "";
    return `<div class="result-copy">${markdown(result.answer)}${chart}</div>${traceHTML(result.trace)}`;
  }
  return `<pre class="json">${escapeHTML(JSON.stringify(result,null,2))}</pre>`;
}
function renderOutput() {
  const output = $("#output");
  if (!currentResult) { output.className="panel-body output empty"; output.innerHTML="Run the chapter interaction to see grounded output and trace data."; return; }
  output.className="panel-body output";
  output.innerHTML=outputHTML(currentResult);
}
function controlsHTML(chapter) {
  if (!chapter.actions?.length) return `<p class="action-copy">This chapter is a live status view. Refresh it to inspect the warmed substrate.</p><div class="actions"><button class="primary" data-refresh>Refresh status</button></div>`;
  const primary = chapter.actions[0];
  const field = primary.field ? `<label for="chapter-input">Workshop input</label><textarea id="chapter-input" placeholder="${escapeHTML(primary.placeholder)}">${escapeHTML(primary.value)}</textarea>` : "";
  return `<p class="action-copy">Change the prompt, then run the interaction. Results are generated against the shared Kata fixtures.</p>${field}<div class="actions">${chapter.actions.map((a,i)=>`<button class="${i?"secondary":"primary"}" data-action="${i}">${escapeHTML(a.label)}</button>`).join("")}</div>`;
}
async function api(path, options={}) {
  const response=await fetch(path,{headers:{"Content-Type":"application/json"},...options});
  const payload=await response.json().catch(()=>({detail:"Invalid server response"}));
  if(!response.ok) throw new Error(payload.detail || `HTTP ${response.status}`);
  return payload;
}
function streamTurn(path, message) {
  return new Promise((resolve,reject)=>{
    const url=`${path}?message=${encodeURIComponent(message)}&thread_id=appbook-stream`;
    const source=new EventSource(url); let finished=false; const nodes=[];
    source.addEventListener("node",event=>{
      const node=JSON.parse(event.data); nodes.push(node.node);
      currentResult={streaming:true,nodes}; currentView="json"; renderOutput();
    });
    source.addEventListener("result",event=>{
      finished=true; source.close(); resolve(JSON.parse(event.data));
    });
    source.onerror=()=>{source.close();if(!finished)reject(new Error("SSE stream disconnected"));};
  });
}
async function loadStatus(chapter) {
  try {
    const data=await api(chapter.endpoint);
    currentResult=data; renderOutput();
    $("#global-status").classList.add("ready");
    $("#global-status span").textContent="Harness ready";
  } catch (error) {
    $("#output").className="panel-body output";
    $("#output").innerHTML=`<div class="error">${escapeHTML(error.message)}. Start this appbook with <code>./run.sh</code>.</div>`;
  }
}
async function runAction(chapter,index) {
  const action=chapter.actions[index], button=$(`[data-action="${index}"]`);
  const original=button.textContent; button.disabled=true; button.innerHTML='<span class="loading">Running</span>';
  try {
    let body={};
    if(action.field) body[action.field]=$("#chapter-input").value;
    if(action.field==="message") body.thread_id="appbook-thread";
    currentResult=action.stream
      ? await streamTurn(action.stream, body.message)
      : await api(action.path,{method:"POST",body:JSON.stringify(body)});
    currentView="answer"; renderOutput();
  } catch(error) {
    $("#output").className="panel-body output"; $("#output").innerHTML=`<div class="error">${escapeHTML(error.message)}</div>`;
  } finally { button.disabled=false; button.textContent=original; }
}
function renderStage(id) {
  const productRoute=id.startsWith("storefront/product/");
  const chapter=CHAPTERS.find(c=>c.id===(productRoute?"storefront":id)) || CHAPTERS[0];
  document.title=`ERPA / ${chapter.title}`;
  document.querySelectorAll(".nav").forEach(n=>n.classList.toggle("active",n.dataset.id===chapter.id));
  if (chapter.kind === "storefront") {
    renderStorefrontStage(chapter,productRoute?decodeURIComponent(id.split("/").slice(2).join("/")):null);
    closeMenu();
    return;
  }
  const specialised={architecture:renderArchitectureStage,memory:renderMemoryStage,semantic:renderSemanticStage,retrieval:renderRetrievalStage,skills:renderSkillsStage,cache:renderCacheStage};
  if(specialised[chapter.kind]){specialised[chapter.kind](chapter);closeMenu();return;}
  $("#stage").innerHTML=`<div class="stage-inner">
    <header class="stage-head"><div><div class="eyebrow">CUSTOM HARNESS · CHAPTER ${String(chapter.n).padStart(2,"0")}</div><h1>${chapter.title}</h1><p class="blurb">${chapter.blurb}</p><div class="chapter-meta"><span class="pill">${chapter.tag}</span><span class="pill">Local mirror / live Oracle</span></div></div><button class="theme" id="theme" aria-label="Toggle colour theme">◐</button></header>
    <section class="demo"><div class="panel"><div class="panel-head"><h2 class="panel-title">Chapter control</h2><span class="eyebrow">LIVE</span></div><div class="panel-body">${controlsHTML(chapter)}</div></div>
    <div class="panel"><div class="panel-head"><h2 class="panel-title">Output</h2><div class="segmented"><button data-view="answer" class="active">Answer</button><button data-view="trace">Trace</button><button data-view="json">JSON</button></div></div><div id="output" class="panel-body output empty"></div></div></section>
  </div>`;
  currentResult=null; currentView="answer"; renderOutput();
  $("#theme").onclick=toggleTheme;
  document.querySelectorAll("[data-view]").forEach(button=>button.onclick=()=>{currentView=button.dataset.view;document.querySelectorAll("[data-view]").forEach(b=>b.classList.toggle("active",b===button));renderOutput();});
  document.querySelectorAll("[data-action]").forEach(button=>button.onclick=()=>runAction(chapter,Number(button.dataset.action)));
  const refresh=$("[data-refresh]"); if(refresh) refresh.onclick=()=>loadStatus(chapter);
  loadStatus(chapter);
  closeMenu();
}

function chapterHeader(chapter) {
  return `<header class="stage-head"><div><div class="eyebrow">CUSTOM HARNESS · CHAPTER ${String(chapter.n).padStart(2,"0")}</div><h1>${escapeHTML(chapter.title)}</h1><p class="blurb">${escapeHTML(chapter.blurb)}</p><div class="chapter-meta"><span class="pill">${escapeHTML(chapter.tag)}</span><span class="pill">Local mirror / live Oracle</span></div></div><button class="theme" id="theme" aria-label="Toggle colour theme">◐</button></header>`;
}
function mountChapter(chapter,body){$("#stage").innerHTML=`<div class="stage-inner">${chapterHeader(chapter)}${body}</div>`;$("#theme").onclick=toggleTheme;}
function setHarnessReady(){$("#global-status").classList.add("ready");$("#global-status span").textContent="Harness ready";}

async function renderArchitectureStage(chapter) {
  mountChapter(chapter,`<section class="architecture-wrap"><div class="arch-legend"><span><i class="built"></i>Built</span><span><i class="partial"></i>Partial</span><span><i class="missing"></i>Explicit gap</span><span class="arch-mode" id="arch-mode">Reading substrate…</span></div>
    <div class="architecture-flow">
      <div class="arch-lane"><b>EXPERIENCE</b><div class="arch-nodes"><article class="arch-node built"><span>01</span><strong>Kata Store</strong><small>Catalog · product pages · cart · ERPA chat</small></article><article class="arch-node built"><span>02</span><strong>Appbook labs</strong><small>Comparisons · traces · data explorer</small></article><article class="arch-node built"><span>03</span><strong>Scheduled brief</strong><small>Oracle Scheduler · queue worker</small></article></div></div>
      <div class="arch-arrow"><span>HTTPS / JSON / SSE</span></div>
      <div class="arch-lane"><b>APPLICATION BOUNDARY</b><div class="arch-nodes"><article class="arch-node built"><span>04</span><strong>FastAPI</strong><small>Typed routes · CORS · activity middleware</small></article><article class="arch-node partial"><span>05</span><strong>Approval ledger</strong><small>Draft → approve → execute</small></article><article class="arch-node built"><span>06</span><strong>Transaction stream</strong><small>Reads · writes · commit / rollback</small></article></div></div>
      <div class="arch-arrow"><span>THREAD + SESSION + USER</span></div>
      <div class="arch-lane focus"><b>AGENT HARNESS</b><div class="arch-nodes"><article class="arch-node built"><span>07</span><strong>LangGraph</strong><small>Context → model → tools → persist</small></article><article class="arch-node built"><span>08</span><strong>Claude Opus 4.8</strong><small>Adaptive thinking · tool calling</small></article><article class="arch-node built"><span>09</span><strong>CustomToolbox</strong><small>Semantic discovery · allowlist · schemas</small></article><article class="arch-node built"><span>10</span><strong>Skill registry</strong><small>Manifest retrieval · one-body disclosure</small></article></div></div>
      <div class="arch-fan"><span>SELECTIVE CONTEXT</span><span>SAFE EXECUTION</span><span>OBSERVABILITY</span></div>
      <div class="arch-lane triple"><b>RUNTIME SERVICES</b><div class="arch-nodes"><article class="arch-node built"><span>11</span><strong>OAMP</strong><small>Facts · preferences · episodes · guidelines</small></article><article class="arch-node built"><span>12</span><strong>ScratchFS</strong><small>Plans · notes · artifacts · promotion</small></article><article class="arch-node built"><span>13</span><strong>OracleSemanticCache</strong><small>Scoped answer bypass before graph</small></article><article class="arch-node built"><span>14</span><strong>OracleSaver</strong><small>Durable LangGraph super-steps</small></article><article class="arch-node built"><span>15</span><strong>E2B</strong><small>Generated Python; fails closed</small></article><article class="arch-node partial"><span>16</span><strong>LangSmith</strong><small>Graph · model · retrieval · tool spans</small></article></div></div>
      <div class="arch-arrow database"><span>SQL · VECTOR · SECUREFILE · CHECKPOINT</span></div>
      <div class="arch-lane oracle"><b>ORACLE AI DATABASE 26AI</b><div class="arch-nodes"><article class="arch-node built"><span>17</span><strong>Commerce data</strong><small>Products · variants · inventory · orders</small></article><article class="arch-node built"><span>18</span><strong>Living semantic layer</strong><small>Views · comments · hints · V$SQL</small></article><article class="arch-node built"><span>19</span><strong>Vector services</strong><small>In-DB embeddings · OracleVS</small></article><article class="arch-node built"><span>20</span><strong>Harness state</strong><small>Memory · cache · files · checkpoints</small></article></div></div>
      <div class="arch-gaps"><article class="arch-node missing"><strong>MCP transport</strong><small>Not in this single-agent build</small></article><article class="arch-node missing"><strong>Multi-agent delegation</strong><small>Explicit future capability</small></article><article class="arch-node missing"><strong>Self-modification</strong><small>Prohibited by design</small></article><article class="arch-node partial"><strong>Prompt caching</strong><small>Documented seam; not enabled</small></article></div>
    </div><section class="component-ledger"><header><div><span class="eyebrow">IMPLEMENTATION LEDGER</span><h2>Component contracts</h2></div><div id="component-counts"></div></header><div id="component-grid" class="component-grid"><div class="store-loading">Loading runtime component status…</div></div></section></section>`);
  try{const data=await api(chapter.endpoint);setHarnessReady();$("#arch-mode").textContent=`${data.mode} · ${data.substrate}`;$("#component-counts").innerHTML=Object.entries(data.counts||{}).map(([k,v])=>`<span class="pill">${escapeHTML(k)} ${v}</span>`).join("");$("#component-grid").innerHTML=(data.components||[]).map(item=>`<article><i class="${item.status.includes("missing")?"missing":item.status.includes("partial")?"partial":"built"}"></i><div><strong>${escapeHTML(item.concern)}</strong><span>${escapeHTML(item.component)}</span><p>${escapeHTML(item.role)}</p></div><em>${escapeHTML(item.status)}</em></article>`).join("");}catch(error){$("#component-grid").innerHTML=`<div class="error">${escapeHTML(error.message)}</div>`;}
}

const memoryLab={session:sessionStorage.getItem("erpa-memory-session")||`memory-lab-${Date.now().toString(36)}`,thread:"memory-lab-thread",messages:[]};sessionStorage.setItem("erpa-memory-session",memoryLab.session);
function renderMemoryStage(chapter){mountChapter(chapter,`<section class="memory-lab"><div class="lab-chat panel"><div class="panel-head"><h2 class="panel-title">LangGraph conversation</h2><span class="eyebrow">${escapeHTML(memoryLab.session)}</span></div><div class="lab-messages" id="memory-messages"><div class="lab-message assistant">Ask ERPA a business question. The right-hand inspector will show the durable OAMP write and the current ScratchFS plan and observation note.</div></div><div class="example-row"><button>Which ThermaCore sizes are low?</button><button>Remember that I prefer numbers first.</button><button>Why did WarmLayer spike?</button></div><form class="lab-composer" id="memory-form"><textarea id="memory-input" placeholder="Talk to the LangGraph agent…">Which ThermaCore sizes are low?</textarea><button class="primary">Send to ERPA</button></form></div>
  <div class="memory-inspector panel"><div class="panel-head"><h2 class="panel-title">Live state inspector</h2><button class="promote-button" id="promote-memory">Promote selected notes</button></div><div class="memory-tabs"><button class="active" data-memory-tab="memories">OAMP memory</button><button data-memory-tab="scratch">ScratchFS</button><button data-memory-tab="trace">Graph trace</button></div><div class="memory-state" id="memory-state"><div class="explorer-empty">Starting a logical session…</div></div></div></section>`);$("#memory-form").onsubmit=runMemoryChat;$("#memory-messages").parentElement.querySelectorAll(".example-row button").forEach(b=>b.onclick=()=>{$("#memory-input").value=b.textContent;runMemoryChat(new Event("submit"));});$("#promote-memory").onclick=promoteMemory;document.querySelectorAll("[data-memory-tab]").forEach(b=>b.onclick=()=>{document.querySelectorAll("[data-memory-tab]").forEach(x=>x.classList.toggle("active",x===b));renderMemoryState(memoryLab.state,b.dataset.memoryTab);});api("/api/memory_layer/session/start",{method:"POST",body:JSON.stringify({session_id:memoryLab.session,thread_id:memoryLab.thread,user_id:"planner-01"})}).then(state=>{memoryLab.state=state;renderMemoryState(state,"memories");setHarnessReady();}).catch(error=>$("#memory-state").innerHTML=`<div class="error">${escapeHTML(error.message)}</div>`);}
async function runMemoryChat(event){event.preventDefault();const input=$("#memory-input"),message=input.value.trim();if(!message)return;const messages=$("#memory-messages");messages.insertAdjacentHTML("beforeend",`<div class="lab-message user">${escapeHTML(message)}</div><div class="lab-message assistant loading-message"><span class="loading">Running graph</span></div>`);input.value="";messages.scrollTop=messages.scrollHeight;try{const result=await api("/api/memory_layer/chat",{method:"POST",body:JSON.stringify({message,thread_id:memoryLab.thread,session_id:memoryLab.session})});messages.querySelector(".loading-message")?.remove();messages.insertAdjacentHTML("beforeend",`<div class="lab-message assistant">${markdown(result.answer)}</div>`);memoryLab.state=result.session;memoryLab.trace=result.trace;renderMemoryState(result.session,document.querySelector("[data-memory-tab].active")?.dataset.memoryTab||"memories");}catch(error){messages.querySelector(".loading-message")?.remove();messages.insertAdjacentHTML("beforeend",`<div class="lab-message assistant error">${escapeHTML(error.message)}</div>`);}messages.scrollTop=messages.scrollHeight;}
function renderMemoryState(state,tab="memories"){const target=$("#memory-state");if(!target||!state)return;if(tab==="scratch"){target.innerHTML=`<div class="state-summary"><span>${escapeHTML(state.status)}</span><span>${state.scratch_files.length} files</span><span>Y = promoted · S = staged · N = working</span></div>${state.scratch_files.map(file=>`<details class="state-record" open><summary><span>${escapeHTML(file.path)}</span><em>${file.promote_on_end?"PROMOTE":"WORKING"} · ${escapeHTML(file.promotion_state)}</em></summary><pre>${escapeHTML(file.content)}</pre></details>`).join("")||'<div class="explorer-empty">No working files yet.</div>'}`;return;}if(tab==="trace"){target.innerHTML=memoryLab.trace?traceHTML(memoryLab.trace):'<div class="explorer-empty">Run a turn to inspect LangGraph spans.</div>';return;}target.innerHTML=`<div class="state-summary">${Object.entries(state.memory_counts).map(([k,v])=>`<span>${escapeHTML(k)} <b>${v}</b>${state.memory_writes_this_turn?.[k]?` <i>+${state.memory_writes_this_turn[k]}</i>`:""}</span>`).join("")}</div>${Object.entries(state.memories).map(([kind,items])=>`<section class="memory-group"><h3>${escapeHTML(kind)}</h3>${items.slice(-5).reverse().map(item=>`<article class="state-record"><strong>${escapeHTML(item.content)}</strong><small>${escapeHTML(item.metadata?.source||"OAMP")} · ${escapeHTML(item.memory_id)}</small></article>`).join("")}</section>`).join("")}`;}
async function promoteMemory(){const button=$("#promote-memory");button.disabled=true;button.textContent="Triggering promotion…";try{const result=await api("/api/memory_layer/session/end",{method:"POST",body:JSON.stringify({session_id:memoryLab.session,thread_id:memoryLab.thread,user_id:"planner-01"})});memoryLab.state=await api(`/api/memory_layer/session/${encodeURIComponent(memoryLab.session)}`);document.querySelectorAll("[data-memory-tab]").forEach(b=>b.classList.toggle("active",b.dataset.memoryTab==="scratch"));renderMemoryState(memoryLab.state,"scratch");button.textContent=`Promoted ${result.promoted} chunk${result.promoted===1?"":"s"}`;}catch(error){button.textContent=error.message;}finally{button.disabled=false;}}

function comparisonShell(title,subtitle){return `<div class="comparison-card"><header><span class="eyebrow">${escapeHTML(subtitle)}</span><h2>${escapeHTML(title)}</h2></header><div class="comparison-answer explorer-empty">Run the shared query to compare this path.</div></div>`;}
function renderSemanticStage(chapter){mountChapter(chapter,`<section class="compare-lab"><form class="shared-query" id="semantic-form"><label>One question · two execution paths</label><div><input id="semantic-input" value="Which regions are most profitable this quarter?"/><button class="primary">Run both</button></div><div class="example-row"><button type="button">Which regions are most profitable this quarter?</button><button type="button">Which ThermaCore sizes are low?</button><button type="button">Why did WarmLayer spike?</button></div></form><div class="comparison-grid two" id="semantic-results">${comparisonShell("Without semantic layer","Literal schema matching")}${comparisonShell("With living semantic layer","Governed meaning")}</div></section>`);$("#semantic-form").onsubmit=runSemanticCompare;document.querySelectorAll("#semantic-form .example-row button").forEach(b=>b.onclick=()=>{$("#semantic-input").value=b.textContent;runSemanticCompare(new Event("submit"));});setHarnessReady();}
async function runSemanticCompare(event){event.preventDefault();const query=$("#semantic-input").value.trim(),cards=document.querySelectorAll("#semantic-results .comparison-card");cards.forEach(c=>c.querySelector(".comparison-answer").innerHTML='<span class="loading">Executing</span>');try{const result=await api("/api/semantic_layer/compare",{method:"POST",body:JSON.stringify({question:query,thread_id:"semantic-lab"})});[[cards[0],result.without_semantic_layer],[cards[1],result.with_semantic_layer]].forEach(([card,data])=>{card.querySelector(".comparison-answer").className="comparison-answer";card.querySelector(".comparison-answer").innerHTML=`<div class="result-copy">${markdown(data.answer)}</div><details><summary>Inspect assembled context</summary><pre class="json">${escapeHTML(JSON.stringify(data.context,null,2))}</pre></details>`;});}catch(error){cards.forEach(c=>c.querySelector(".comparison-answer").innerHTML=`<div class="error">${escapeHTML(error.message)}</div>`);}}

const retrievalOrder=["keyword","vector","hybrid","rerank"];
function renderRetrievalStage(chapter){mountChapter(chapter,`<section class="compare-lab"><form class="shared-query" id="retrieval-form"><label>One real question · four independent retrieval pipelines</label><div><input id="retrieval-input" value="What should Alex do about the Berlin thermal jacket shortage?"/><button class="primary">Run all four with Claude</button></div><div class="example-row"><button type="button">What should Alex do about the Berlin thermal jacket shortage?</button><button type="button">How do we protect full price while fixing a broken middle-size curve?</button><button type="button">Why did UK base-layer demand jump without a campaign?</button></div></form><aside class="retrieval-proof" id="retrieval-proof"><strong>Ready for a grounded Claude comparison</strong><p>Clicking <b>Run all four with Claude</b> ranks the local institutional corpus four ways, then sends each method’s five displayed passages to Anthropic separately. No retrieval runs automatically.</p></aside><div class="comparison-grid four" id="retrieval-results">${retrievalOrder.map(method=>comparisonShell(method,method==="vector"?"Oracle in-DB vector":method)).join("")}</div></section>`);$("#retrieval-form").onsubmit=runRetrievalCompare;document.querySelectorAll("#retrieval-form .example-row button").forEach(b=>b.onclick=()=>{$("#retrieval-input").value=b.textContent;});setHarnessReady();}
async function runRetrievalCompare(event){event.preventDefault();const cards=document.querySelectorAll("#retrieval-results .comparison-card"),proof=$("#retrieval-proof");cards.forEach(c=>c.querySelector(".comparison-answer").innerHTML='<span class="loading">Retrieving sources, then asking Claude</span>');try{const result=await api("/api/retrieval/compare",{method:"POST",body:JSON.stringify({query:$("#retrieval-input").value.trim()})});proof.classList.toggle("verified",result.experiment.rankings_differ);proof.innerHTML=`<strong>${result.experiment.rankings_differ?"Verified: the rankings differ":"The rankings converged for this query"}</strong><p>${escapeHTML(result.experiment.corpus_documents)} real institutional documents · ${escapeHTML(result.experiment.answer_policy)}</p><div class="retrieval-top-sources">${retrievalOrder.map(method=>`<span><b>${escapeHTML(method)}</b>${escapeHTML(result.experiment.top_sources[method])}</span>`).join("")}</div>`;retrievalOrder.forEach((method,index)=>{const data=result.methods[method],card=cards[index],generation=data.generation||{};card.querySelector("h2").textContent=data.label;card.querySelector(".comparison-answer").className="comparison-answer";card.querySelector(".comparison-answer").innerHTML=`<p class="method-explain">${escapeHTML(data.explanation)}</p><div class="claude-answer-label"><span>CLAUDE ANSWER</span><small>${escapeHTML(generation.model||result.experiment.answer_model)} · ${escapeHTML(generation.thinking||result.experiment.thinking)} thinking · ${Number(generation.latency_ms||0).toFixed(0)} ms</small></div><div class="result-copy claude-result">${markdown(data.answer)}</div><section class="retrieved-sources"><h3>Retrieved sources</h3><ol>${data.sources.map(source=>`<li><b>S${source.rank}</b><span><strong>${escapeHTML(source.title)}</strong><small>${escapeHTML(source.source)} · relevance ${Number(source.score||0).toFixed(3)}</small></span></li>`).join("")}</ol></section><details><summary>Inspect retrieved context · ${data.context_window.items} sources · ~${data.context_window.estimated_tokens} tokens</summary><div class="context-stack">${data.context.map(item=>`<article><b>S${item.rank} · ${escapeHTML(item.kind)}</b><strong>${escapeHTML(item.title)}</strong><p>${escapeHTML(item.content)}</p><small>${escapeHTML(item.source)} · ${escapeHTML(item.provider)}${item.score!==null&&item.score!==undefined?` · relevance ${Number(item.score).toFixed(3)}`:""}</small></article>`).join("")}</div></details>`;});}catch(error){proof.innerHTML=`<strong>Retrieval experiment failed</strong><p>${escapeHTML(error.message)}</p>`;cards.forEach(c=>c.querySelector(".comparison-answer").innerHTML=`<div class="error">${escapeHTML(error.message)}</div>`);}}

function renderSkillsStage(chapter){mountChapter(chapter,`<section class="skills-lab"><form class="shared-query" id="skills-form"><label>Task for the skill retriever</label><div><input id="skills-input" value="Investigate the WarmLayer demand spike in the UK"/><button class="primary">Retrieve + disclose</button></div><div class="example-row"><button type="button">Investigate the WarmLayer demand spike in the UK</button><button type="button">Which ThermaCore sizes need restocking?</button><button type="button">Review return reasons by product line</button></div></form><div class="skill-pipeline"><section><header><span>1</span><div><b>Available manifests</b><small>Compact metadata only</small></div></header><div class="skill-catalog" id="skill-catalog"><div class="store-loading">Loading skill registry…</div></div></section><i>→</i><section><header><span>2</span><div><b>Retrieved manifests</b><small>Ranked for this task</small></div></header><div id="skill-matches" class="skill-catalog"><div class="explorer-empty">Run an example query.</div></div></section><i>→</i><section><header><span>3</span><div><b>Disclosed procedure</b><small>One full approved body</small></div></header><div id="skill-body" class="skill-body"><div class="explorer-empty">No skill body loaded.</div></div></section></div></section>`);$("#skills-form").onsubmit=runSkills;document.querySelectorAll("#skills-form .example-row button").forEach(b=>b.onclick=()=>{$("#skills-input").value=b.textContent;runSkills(new Event("submit"));});api(chapter.endpoint).then(data=>{$("#skill-catalog").innerHTML=data.metadata.map(s=>`<article><strong>${escapeHTML(s.name)}</strong><p>${escapeHTML(s.description)}</p></article>`).join("");setHarnessReady();});}
async function runSkills(event){event.preventDefault();$("#skill-matches").innerHTML='<span class="loading">Ranking</span>';$("#skill-body").innerHTML='<span class="loading">Waiting for selection</span>';try{const data=await api("/api/skills/match",{method:"POST",body:JSON.stringify({query:$("#skills-input").value.trim()})});$("#skill-matches").innerHTML=data.matched.map((s,i)=>`<article class="${i===0?"selected":""}"><span>#${i+1}</span><strong>${escapeHTML(s.name)}</strong><p>${escapeHTML(s.description)}</p></article>`).join("")||'<div class="explorer-empty">No skill matched.</div>';const skill=data.disclosed_skill;$("#skill-body").innerHTML=skill?`<span class="eyebrow">LOADED AFTER RETRIEVAL</span><h3>${escapeHTML(skill.name)}</h3><p>${escapeHTML(skill.instructions)}</p><details><summary>Authority and token delta</summary><pre class="json">${escapeHTML(JSON.stringify({source:skill.source,tokens:data.token_comparison,sequence:data.sequence},null,2))}</pre></details>`:'<div class="explorer-empty">No skill was disclosed.</div>';}catch(error){$("#skill-body").innerHTML=`<div class="error">${escapeHTML(error.message)}</div>`;}}

function renderCacheStage(chapter){mountChapter(chapter,`<section class="compare-lab"><form class="shared-query" id="cache-form"><label>One question · cache bypass versus semantic hit</label><div><input id="cache-input" value="Why did WarmLayer spike in the UK last week?"/><button class="primary">Compare execution</button></div><div class="example-row"><button type="button">Why did WarmLayer spike in the UK last week?</button><button type="button">Which ThermaCore sizes are low?</button><button type="button">Which regions are most profitable this quarter?</button></div></form><div class="comparison-grid two" id="cache-results">${comparisonShell("Cache disabled","Full LangGraph execution")}${comparisonShell("Semantic cache enabled","Boundary bypass")}</div></section>`);$("#cache-form").onsubmit=runCacheCompare;document.querySelectorAll("#cache-form .example-row button").forEach(b=>b.onclick=()=>{$("#cache-input").value=b.textContent;runCacheCompare(new Event("submit"));});setHarnessReady();}
async function runCacheCompare(event){event.preventDefault();const cards=document.querySelectorAll("#cache-results .comparison-card");cards.forEach(c=>c.querySelector(".comparison-answer").innerHTML='<span class="loading">Measuring</span>');try{const result=await api("/api/cache/compare",{method:"POST",body:JSON.stringify({query:$("#cache-input").value.trim()})});[[cards[0],result.without_cache,"Full graph"],[cards[1],result.with_semantic_cache,"Cache hit"]].forEach(([card,data,badge])=>{card.querySelector(".comparison-answer").className="comparison-answer";card.querySelector(".comparison-answer").innerHTML=`<div class="timing"><strong>${Number(data.elapsed_ms).toFixed(2)}<small> ms</small></strong><span>${data.tokens} tokens</span><em>${badge}</em></div><div class="result-copy">${markdown(data.answer)}</div>${traceHTML(data.trace)}`;});cards[1].insertAdjacentHTML("beforeend",`<div class="cache-delta">Saved ${Number(result.delta_ms).toFixed(2)} ms · ${escapeHTML(result.implementation)}</div>`);}catch(error){cards.forEach(c=>c.querySelector(".comparison-answer").innerHTML=`<div class="error">${escapeHTML(error.message)}</div>`);}}

function productArt(product,index) {
  const palettes=[
    ["#d7ff79","#204b3f"],["#ffb59f","#612f36"],["#9ddcff","#163b62"],
    ["#e4c7ff","#49305e"],["#ffd980","#5c4214"],["#b4ead7","#205448"]
  ];
  const [light,dark]=palettes[index%palettes.length];
  const outer=/Outerwear/i.test(product.category);
  const bottoms=/Bottoms/i.test(product.category);
  const accessory=/Accessories/i.test(product.category);
  const shape=accessory
    ? `<path d="M89 79c0-28 18-47 45-47s45 19 45 47v51H89V79Z" fill="${dark}"/><path d="M110 79c0-17 8-27 24-27s24 10 24 27" fill="none" stroke="${light}" stroke-width="8"/>`
    : bottoms
      ? `<path d="M91 34h86l-7 98-31-4-5-57-7 57-31 4-5-98Z" fill="${dark}"/><path d="M94 48h80" stroke="${light}" stroke-width="4" opacity=".65"/>`
      : `<path d="m94 38 24-12h32l24 12 26 32-24 16-13-18v67H105V68L92 86 68 70l26-32Z" fill="${dark}"/><path d="M118 27c2 15 30 15 32 0" fill="none" stroke="${light}" stroke-width="5"/>${outer?`<path d="M134 46v89M106 74h56" stroke="${light}" stroke-width="3" opacity=".65"/>`:""}`;
  return `<svg viewBox="0 0 268 176" role="img" aria-label="Illustration of ${escapeHTML(product.name)}"><defs><linearGradient id="g${index}" x1="0" y1="0" x2="1" y2="1"><stop stop-color="${light}"/><stop offset="1" stop-color="#f4f1e9"/></linearGradient></defs><rect width="268" height="176" rx="18" fill="url(#g${index})"/><circle cx="226" cy="35" r="42" fill="${dark}" opacity=".08"/><circle cx="42" cy="151" r="61" fill="${dark}" opacity=".08"/>${shape}<text x="16" y="159" fill="${dark}" font-family="IBM Plex Mono" font-size="9" font-weight="600">${escapeHTML(product.sku)}</text></svg>`;
}

function money(value) { return new Intl.NumberFormat("en-GB",{style:"currency",currency:"GBP"}).format(Number(value||0)); }
function productStock(product) { return Math.max(0, Number(product.total_stock||0)-Number(product.reserved||0)); }
function cartQuantity() { return Object.values(storefrontCart).reduce((sum,item)=>sum+item.quantity,0); }
function saveCart() { localStorage.setItem("erpa-store-cart",JSON.stringify(storefrontCart)); }

function renderStorefrontStage(chapter, productSku=null) {
  activeProductSku=productSku;
  $("#stage").innerHTML=`<div class="storefront">
    <header class="store-nav"><a class="store-logo" href="#storefront"><span>K</span>KATA / GOODS</a><nav><a href="#store-products">New</a><a href="#store-products">Women</a><a href="#store-products">Men</a><a href="#store-products">Core</a></nav><div class="store-actions"><button class="store-icon" id="store-theme" aria-label="Toggle colour theme">◐</button><button class="store-cart-button" id="cart-open">Bag <span id="cart-count">${cartQuantity()}</span></button></div></header>
    <main id="store-content">
    <section class="store-hero"><div class="hero-copy"><span class="store-kicker">The AW26 field collection</span><h1>Built for weather.<br><em>Ready for motion.</em></h1><p>Technical layers and everyday essentials from the live Kata catalog. Every stock figure below comes from the application database.</p><a href="#store-products" class="shop-link">Shop the collection <span>→</span></a></div><div class="hero-art"><div class="hero-card hero-card-one"><span>FIELD / 01</span></div><div class="hero-card hero-card-two"><span>CORE / 26</span></div><div class="hero-orbit">60<br><small>styles</small></div></div></section>
    <section class="store-promise"><span>Complimentary delivery over £120</span><span>30-day returns</span><span>Inventory verified in real time</span></section>
    <section class="store-products" id="store-products"><header><div><span class="store-kicker">Shop all</span><h2>The catalog</h2></div><p id="store-product-count">Loading live inventory…</p></header>
      <div class="store-filters"><label><span class="sr-only">Search products</span><input id="store-search" placeholder="Search the collection" /></label><select id="store-category"><option value="">All categories</option></select><select id="store-sort"><option value="featured">Featured</option><option value="price-low">Price: low to high</option><option value="price-high">Price: high to low</option><option value="stock">Most in stock</option></select></div>
      <div class="product-grid" id="product-grid"><div class="store-loading">Reading products, variants and inventory…</div></div>
    </section>
    </main>
    <footer class="store-footer"><div class="store-logo"><span>K</span>KATA / GOODS</div><div><strong>Collections</strong><a href="#store-products">Outerwear</a><a href="#store-products">Core essentials</a><a href="#store-products">Accessories</a></div><div><strong>Customer care</strong><span>Delivery & returns</span><span>Product care</span><span>Size guide</span></div><p>Educational commerce surface powered by the same ERPA harness and application database.</p></footer>
    <div class="cart-scrim" id="cart-scrim" hidden></div><aside class="cart-drawer" id="cart-drawer" aria-label="Shopping bag"><header><div><span class="store-kicker">Your selection</span><h2>Shopping bag</h2></div><button id="cart-close" aria-label="Close bag">×</button></header><div id="cart-lines" class="cart-lines"></div><div class="cart-checkout" id="cart-checkout"></div></aside>
    <button class="erpa-launcher" id="erpa-launcher" aria-label="Chat with ERPA"><span class="erpa-avatar">ER</span><span>Ask ERPA</span><i></i></button>
    <aside class="erpa-chat" id="erpa-chat" aria-label="ERPA shopping assistant"><header><div class="erpa-avatar">ER</div><div><strong>ERPA</strong><span><i></i> Catalog intelligence online</span></div><button id="erpa-close" aria-label="Close assistant">×</button></header><div class="erpa-messages" id="erpa-messages"><div class="chat-message assistant">I can inspect the live catalog and inventory, explain demand, or compare product performance. What would you like to know?</div><div class="chat-suggestions"><button>Which ThermaCore sizes are low?</button><button>What is trending in the UK?</button><button>Show my morning brief</button></div></div><form id="erpa-form"><input id="erpa-input" autocomplete="off" placeholder="Ask about products or inventory…" /><button aria-label="Send">↑</button></form></aside>
    <div class="store-toast" id="store-toast" role="status"></div>
  </div>`;
  $("#store-theme").onclick=toggleTheme;
  $("#cart-open").onclick=()=>toggleCart(true); $("#cart-close").onclick=()=>toggleCart(false); $("#cart-scrim").onclick=()=>toggleCart(false);
  $("#erpa-launcher").onclick=()=>toggleErpa(true); $("#erpa-close").onclick=()=>toggleErpa(false);
  $("#erpa-form").onsubmit=sendStorefrontChat;
  $("#erpa-messages").addEventListener("click",event=>{if(event.target.matches(".chat-suggestions button")){ $("#erpa-input").value=event.target.textContent; sendStorefrontChat(event); }});
  loadStorefront(productSku); renderCart();
}

async function loadStorefront(productSku=activeProductSku) {
  try {
    const payload=await api("/api/storefront/catalog");
    storefrontProducts=payload.products;
    $("#global-status").classList.add("ready"); $("#global-status span").textContent="Harness ready";
    const select=$("#store-category");
    if(select){
      select.innerHTML='<option value="">All categories</option>'+payload.categories.map(c=>`<option>${escapeHTML(c)}</option>`).join("");
      $("#store-search").oninput=renderProducts; select.onchange=renderProducts; $("#store-sort").onchange=renderProducts;
      renderProducts();
    }
    if(productSku) await renderProductDetail(productSku);
  } catch(error) { const target=$("#product-grid")||$("#store-content"); if(target)target.innerHTML=`<div class="error store-detail-error">${escapeHTML(error.message)}</div>`; }
}

function renderProducts() {
  const search=($("#store-search")?.value||"").toLowerCase(), category=$("#store-category")?.value||"", sort=$("#store-sort")?.value||"featured";
  let products=storefrontProducts.filter(p=>(!category||p.category===category)&&(!search||`${p.name} ${p.product_line} ${p.category} ${p.fabric}`.toLowerCase().includes(search)));
  products=[...products].sort((a,b)=>sort==="price-low"?a.base_price-b.base_price:sort==="price-high"?b.base_price-a.base_price:sort==="stock"?productStock(b)-productStock(a):Number(b.is_core)-Number(a.is_core));
  $("#store-product-count").textContent=`${products.length} styles · inventory as of 29 Sep 2026`;
  $("#product-grid").innerHTML=products.map((p,index)=>{const stock=productStock(p), colours=String(p.colours||"").split(",").filter(Boolean).slice(0,4); return `<article class="product-card" data-product="${escapeHTML(p.sku)}" tabindex="0" role="link" aria-label="View ${escapeHTML(p.name)}"><div class="product-image">${productArt(p,index)}<span class="product-badge">${p.is_core?"Core":"Seasonal"}</span><button class="quick-add" data-add="${escapeHTML(p.sku)}" ${stock<1?"disabled":""}>${stock<1?"Sold out":"Quick add +"}</button></div><div class="product-info"><div><span>${escapeHTML(p.category)} · ${escapeHTML(p.season)}</span><h3>${escapeHTML(p.name)}</h3></div><strong>${money(p.base_price)}</strong></div><div class="product-meta"><div class="swatches">${colours.map((c,i)=>`<i title="${escapeHTML(c)}" style="--swatch:${["#20231f","#d7d0bd","#667564","#8c5e4c"][i%4]}"></i>`).join("")}</div><span class="stock ${stock<25?"low":""}">${stock.toLocaleString()} available</span></div></article>`;}).join("") || '<div class="store-loading">No styles match those filters.</div>';
  $("#product-grid").querySelectorAll("[data-add]").forEach(button=>button.onclick=event=>{event.stopPropagation();addToCart(button.dataset.add);});
  $("#product-grid").querySelectorAll("[data-product]").forEach(card=>{const open=()=>location.hash=`storefront/product/${encodeURIComponent(card.dataset.product)}`;card.onclick=event=>{if(!event.target.closest("button"))open();};card.onkeydown=event=>{if(event.key==="Enter"||event.key===" "){event.preventDefault();open();}};});
}

async function renderProductDetail(sku) {
  const content=$("#store-content"); if(!content)return;
  content.innerHTML='<div class="store-loading product-loading"><span class="loading">Reading live product inventory</span></div>';
  const detail=await api(`/api/storefront/products/${encodeURIComponent(sku)}`), product=detail.product;
  const catalogProduct=storefrontProducts.find(item=>item.sku===sku)||product;
  const sizes=Object.entries(detail.by_size||{}), regions=Object.entries(detail.by_region||{});
  const peak=Math.max(1,...regions.map(([,units])=>Number(units)));
  const colourPalette=["#20231f","#d7d0bd","#667564","#8c5e4c","#315472","#b88967"];
  content.innerHTML=`<section class="product-detail">
    <a class="product-back" href="#storefront">← Back to the collection</a>
    <div class="product-detail-grid"><div class="product-detail-art">${productArt(catalogProduct,storefrontProducts.findIndex(item=>item.sku===sku))}<span>LIVE CATALOG · ${escapeHTML(detail.snapshot_date)}</span></div>
      <div class="product-detail-copy"><span class="store-kicker">${escapeHTML(product.category)} · ${escapeHTML(product.season)}</span><h1>${escapeHTML(product.name)}</h1><div class="product-price">${money(product.base_price)}</div><p class="product-intro">A technical Kata layer in ${escapeHTML(product.fabric||"performance fabric")}. Availability is calculated from on-hand less reserved stock across every live location.</p>
        <section class="product-choice"><header><strong>Colour</strong><span>${detail.colours.length} available</span></header><div class="detail-colours">${detail.colours.map((colour,index)=>`<button title="${escapeHTML(colour)}"><i style="--swatch:${colourPalette[index%colourPalette.length]}"></i>${escapeHTML(colour)}</button>`).join("")}</div></section>
        <section class="product-choice"><header><strong>Size</strong><span>${Number(detail.available).toLocaleString()} units available</span></header><div class="detail-sizes">${sizes.map(([size,units])=>`<button class="${Number(units)<25?"low":""}" title="${Number(units).toLocaleString()} units"><b>${escapeHTML(size)}</b><small>${Number(units).toLocaleString()}</small></button>`).join("")}</div></section>
        <button class="product-add" id="product-add" ${detail.available<1?"disabled":""}>${detail.available<1?"Sold out":"Add to bag"}</button>
        <div class="product-facts"><div><span>Fabric</span><strong>${escapeHTML(product.fabric||"—")}</strong></div><div><span>Collection</span><strong>${escapeHTML(product.collection_name||product.collection||"Core")}</strong></div><div><span>Product line</span><strong>${escapeHTML(product.product_line||"—")}</strong></div></div>
      </div></div>
    <section class="regional-stock"><header><div><span class="store-kicker">Database evidence</span><h2>Availability by region</h2></div><p>Derived from ${detail.inventory.length} variant-location rows.</p></header><div>${regions.map(([region,units])=>`<article><span>${escapeHTML(region)}</span><div><i style="--stock-width:${(Number(units)/peak*100).toFixed(1)}%"></i></div><strong>${Number(units).toLocaleString()}</strong></article>`).join("")}</div><details><summary>Inspect variant and location rows</summary><div class="product-inventory-table"><table><thead><tr><th>Variant</th><th>Colour</th><th>Size</th><th>Region</th><th>City</th><th>On hand</th><th>Reserved</th><th>In transit</th></tr></thead><tbody>${detail.inventory.map(row=>`<tr><td>${escapeHTML(row.variant_id)}</td><td>${escapeHTML(row.colour)}</td><td>${escapeHTML(row.size)}</td><td>${escapeHTML(row.region)}</td><td>${escapeHTML(row.city)}</td><td>${Number(row.on_hand).toLocaleString()}</td><td>${Number(row.reserved).toLocaleString()}</td><td>${Number(row.in_transit).toLocaleString()}</td></tr>`).join("")}</tbody></table></div></details></section>
  </section>`;
  $("#product-add").onclick=()=>addToCart(sku);
  document.title=`Kata / ${product.name}`;
}

function addToCart(sku) {
  const product=storefrontProducts.find(p=>p.sku===sku); if(!product) return;
  const existing=storefrontCart[sku]||{sku,name:product.name,price:Number(product.base_price),quantity:0};
  existing.quantity=Math.min(existing.quantity+1,10); storefrontCart[sku]=existing; saveCart(); renderCart(); showToast(`${product.name} added to your bag`);
}
function changeCart(sku,delta) { if(!storefrontCart[sku]) return; storefrontCart[sku].quantity+=delta; if(storefrontCart[sku].quantity<1) delete storefrontCart[sku]; saveCart(); renderCart(); }
function renderCart() {
  const count=$("#cart-count"); if(count) count.textContent=cartQuantity();
  const lines=$("#cart-lines"), checkout=$("#cart-checkout"); if(!lines||!checkout) return;
  const items=Object.values(storefrontCart);
  if(!items.length){lines.innerHTML='<div class="empty-cart"><span>0</span><h3>Your bag is empty</h3><p>Add a piece from the live catalog to begin.</p></div>';checkout.innerHTML="";return;}
  lines.innerHTML=items.map(item=>`<div class="cart-line"><div class="cart-thumb">${productArt(item,0)}</div><div><strong>${escapeHTML(item.name)}</strong><span>${escapeHTML(item.sku)}</span><div class="quantity"><button data-delta="-1" data-sku="${escapeHTML(item.sku)}">−</button><span>${item.quantity}</span><button data-delta="1" data-sku="${escapeHTML(item.sku)}">+</button></div></div><b>${money(item.price*item.quantity)}</b></div>`).join("");
  lines.querySelectorAll("[data-delta]").forEach(button=>button.onclick=()=>changeCart(button.dataset.sku,Number(button.dataset.delta)));
  const total=items.reduce((sum,item)=>sum+item.price*item.quantity,0);
  checkout.innerHTML=`<div class="checkout-total"><span>Subtotal</span><strong>${money(total)}</strong></div><p>Delivery calculated at the next step. This workshop checkout writes a real order and inventory transaction.</p><label>Name<input id="checkout-name" value="Demo Shopper" /></label><label>Email<input id="checkout-email" type="email" value="shopper@example.test" /></label><button class="checkout-button" id="checkout-button">Complete demo order</button>`;
  $("#checkout-button").onclick=checkoutCart;
}
function toggleCart(open) { $("#cart-drawer")?.classList.toggle("open",open); if($("#cart-scrim")) $("#cart-scrim").hidden=!open; }
function showToast(message) { const toast=$("#store-toast"); if(!toast)return; toast.textContent=message; toast.classList.add("show"); setTimeout(()=>toast.classList.remove("show"),2600); }
async function checkoutCart() {
  const button=$("#checkout-button"), original=button.textContent; button.disabled=true; button.textContent="Writing transaction…";
  try {
    const result=await api("/api/storefront/checkout",{method:"POST",body:JSON.stringify({customer_name:$("#checkout-name").value,email:$("#checkout-email").value,lines:Object.values(storefrontCart).map(({sku,quantity})=>({sku,quantity}))})});
    storefrontCart={}; saveCart(); renderCart(); toggleCart(false); showToast(`Order ${result.order_id} committed · ${money(result.total)}`);
    await loadStorefront(); await refreshExplorerAfterWrite((explorerState.tables.find(t=>/store_orders$/i.test(t.name))||{}).name);
  } catch(error){showToast(error.message);} finally { if(button.isConnected){button.disabled=false;button.textContent=original;} }
}
function toggleErpa(open) { if(open&&$("#data-explorer")?.classList.contains("open"))toggleExplorer(false); $("#erpa-chat")?.classList.toggle("open",open); if(open)setTimeout(()=>$("#erpa-input")?.focus(),150); }
async function sendStorefrontChat(event) {
  event.preventDefault(); const input=$("#erpa-input"), message=input.value.trim(); if(!message)return;
  const messages=$("#erpa-messages"); messages.querySelector(".chat-suggestions")?.remove(); messages.insertAdjacentHTML("beforeend",`<div class="chat-message user">${escapeHTML(message)}</div><div class="chat-message assistant typing"><i></i><i></i><i></i></div>`); input.value=""; messages.scrollTop=messages.scrollHeight;
  try { const result=await api("/api/storefront/chat",{method:"POST",body:JSON.stringify({message,thread_id:"storefront-shopper"})}); messages.querySelector(".typing")?.remove(); messages.insertAdjacentHTML("beforeend",`<div class="chat-message assistant">${markdown(result.answer)}</div>`); }
  catch(error){messages.querySelector(".typing")?.remove();messages.insertAdjacentHTML("beforeend",`<div class="chat-message assistant error">${escapeHTML(error.message)}</div>`);}
  messages.scrollTop=messages.scrollHeight;
}

function toggleExplorer(force) {
  const explorer=$("#data-explorer"), opening=force ?? !explorer.classList.contains("open");
  explorer.classList.toggle("open",opening); $("#explorer-body").hidden=!opening; $("#explorer-toggle").setAttribute("aria-expanded",String(opening)); document.body.classList.toggle("explorer-open",opening);
  if(opening&&!explorerState.tables.length) loadExplorerCatalog();
}
function initializeExplorerResize() {
  const explorer=$("#data-explorer"), handle=$("#explorer-resizer");
  const saved=Number(localStorage.getItem("erpa-explorer-height"));
  if(Number.isFinite(saved)&&saved>=220) document.documentElement.style.setProperty("--explorer-height",`${Math.min(saved,window.innerHeight-80)}px`);
  handle.addEventListener("pointerdown",event=>{
    if(!explorer.classList.contains("open"))return;
    event.preventDefault(); handle.setPointerCapture(event.pointerId);
    const startY=event.clientY,startHeight=explorer.getBoundingClientRect().height;
    explorer.classList.add("resizing");document.body.classList.add("explorer-resizing");
    const move=moveEvent=>{
      const next=Math.max(220,Math.min(window.innerHeight-80,startHeight+(startY-moveEvent.clientY)));
      document.documentElement.style.setProperty("--explorer-height",`${Math.round(next)}px`);
    };
    const stop=()=>{
      handle.removeEventListener("pointermove",move);handle.removeEventListener("pointerup",stop);handle.removeEventListener("pointercancel",stop);
      explorer.classList.remove("resizing");document.body.classList.remove("explorer-resizing");
      localStorage.setItem("erpa-explorer-height",String(Math.round(explorer.getBoundingClientRect().height)));
    };
    handle.addEventListener("pointermove",move);handle.addEventListener("pointerup",stop);handle.addEventListener("pointercancel",stop);
  });
}
async function loadExplorerCatalog() {
  try { const payload=await api("/api/data_explorer/tables"); explorerState.tables=payload.tables; $("#explorer-summary").textContent=`${payload.tables.length} tables · ${payload.tables.reduce((n,t)=>n+Math.max(0,t.row_count),0).toLocaleString()} rows · ${payload.mode}`; renderExplorerTables(); if(!explorerState.selected){const inventory=payload.tables.find(t=>t.name.toLowerCase()==="inventory");if(inventory)selectExplorerTable(inventory.name);} }
  catch(error){$("#explorer-summary").textContent=error.message;}
}
function renderExplorerTables() {
  const filter=($("#explorer-filter").value||"").toLowerCase();
  $("#explorer-table-list").innerHTML=explorerState.tables.filter(t=>!filter||`${t.name} ${t.layer}`.toLowerCase().includes(filter)).map(t=>{const event=explorerState.active.get(t.name.toLowerCase()), recent=explorerState.recent.get(t.name.toLowerCase());return `<button class="table-item ${explorerState.selected===t.name?"selected":""} ${event?`tx-${event.operation.toLowerCase()}`:recent?`flash-${recent.operation.toLowerCase()}`:""}" data-table="${escapeHTML(t.name)}"><span><i></i>${escapeHTML(t.name)}</span><b>${t.row_count<0?"—":Number(t.row_count).toLocaleString()}</b>${event?`<em>${event.operation}</em>`:""}</button>`;}).join("");
  $("#explorer-table-list").querySelectorAll("[data-table]").forEach(button=>button.onclick=()=>selectExplorerTable(button.dataset.table));
}
async function selectExplorerTable(name,offset=0) {
  explorerState.selected=name; explorerState.offset=offset; renderExplorerTables(); $("#explorer-grid").innerHTML='<div class="explorer-empty">Reading rows…</div>';
  try { explorerState.result=await api(`/api/data_explorer/tables/${encodeURIComponent(name)}/rows?limit=${explorerState.limit}&offset=${offset}`); renderExplorerRows(); }
  catch(error){$("#explorer-grid").innerHTML=`<div class="error">${escapeHTML(error.message)}</div>`;}
}
function renderExplorerRows() {
  const data=explorerState.result, table=explorerState.tables.find(t=>t.name===data.table)||explorerState.tables.find(t=>t.name.toLowerCase()===data.table.toLowerCase()); if(!data)return;
  $("#explorer-layer").textContent=`${table?.layer||"database"} · ${data.columns.length} columns`; $("#explorer-table-name").textContent=data.table; const start=data.row_count?data.offset+1:0,end=Math.min(data.offset+data.rows.length,data.row_count); $("#explorer-page").textContent=`${start.toLocaleString()}–${end.toLocaleString()} of ${Number(data.row_count).toLocaleString()}`; $("#explorer-prev").disabled=data.offset===0; $("#explorer-next").disabled=end>=data.row_count;
  const event=explorerState.active.get(data.table.toLowerCase()), recent=explorerState.recent.get(data.table.toLowerCase()), pulse=event||recent, prefix=event?"tx":"flash";
  $("#explorer-grid").innerHTML=`<table class="data-table ${pulse?`${prefix}-${pulse.operation.toLowerCase()}`:""}"><thead><tr>${data.columns.map(c=>`<th><span>${escapeHTML(c.name)}</span><small>${escapeHTML(c.type)}${c.primary_key?" · PK":""}</small></th>`).join("")}</tr></thead><tbody>${data.rows.map((row,index)=>`<tr data-row-key="${escapeHTML(data.row_keys[index])}" class="${pulse&&(!pulse.row_key||pulse.row_key===data.row_keys[index])?`${prefix}-${pulse.operation.toLowerCase()}`:""}">${data.columns.map(c=>`<td title="${escapeHTML(row[c.name])}">${formatCell(row[c.name])}</td>`).join("")}</tr>`).join("")}</tbody></table>`;
}
function formatCell(value) { if(value===null)return '<span class="null">NULL</span>'; const rendered=typeof value==="object"?JSON.stringify(value):String(value); return escapeHTML(rendered.length>180?rendered.slice(0,180)+"…":rendered); }
function onTransaction(event) {
  explorerState.events.unshift(event); explorerState.events=explorerState.events.slice(0,40); const table=event.table.toLowerCase();
  if(event.status==="active") explorerState.active.set(table,event); else { if(explorerState.active.get(table)?.transaction_id===event.transaction_id)explorerState.active.delete(table); explorerState.recent.set(table,event); setTimeout(()=>{if(explorerState.recent.get(table)?.transaction_id===event.transaction_id){explorerState.recent.delete(table);renderExplorerTables();if(explorerState.result?.table.toLowerCase()===table)renderExplorerRows();}},1400); }
  const latest=[...explorerState.active.values()].at(-1); $("#explorer-live-label").textContent=latest?`${latest.operation} · ${latest.table}`:"Live transactions"; $("#data-explorer").classList.toggle("transacting",explorerState.active.size>0); renderExplorerTables(); if(explorerState.result?.table.toLowerCase()===table)renderExplorerRows(); renderActivity();
}
function renderActivity() { $("#activity-list").innerHTML=explorerState.events.map(e=>`<div class="activity-event ${e.status} ${e.operation.toLowerCase()}"><i></i><div><strong>${escapeHTML(e.operation)} <span>${escapeHTML(e.table)}</span> <em>${escapeHTML(e.status.replace("_"," "))}</em></strong><small>${escapeHTML(e.route)} · ${escapeHTML(e.detail||e.status)}</small></div><time>${new Date(e.occurred_at).toLocaleTimeString([],{hour:"2-digit",minute:"2-digit",second:"2-digit"})}</time></div>`).join("")||'<div class="explorer-empty">Waiting for database activity…</div>'; }
function connectActivity() { if(explorerState.source)explorerState.source.close(); const source=new EventSource("/api/data_explorer/activity"); explorerState.source=source; source.addEventListener("transaction",event=>{try{onTransaction(JSON.parse(event.data));}catch(_){}}); source.addEventListener("ready",()=>$("#explorer-live-label").textContent="Live transactions"); source.onerror=()=>$("#explorer-live-label").textContent="Reconnecting…"; }
async function loadRecentActivity(){try{const payload=await api("/api/data_explorer/activity/recent");explorerState.events=payload.events;renderActivity();}catch(_){}}
async function refreshExplorerAfterWrite(table){await loadExplorerCatalog();if(table&&explorerState.selected?.toLowerCase()===table.toLowerCase())await selectExplorerTable(explorerState.selected,0);}
function toggleTheme() {
  const next=document.documentElement.dataset.theme==="light"?"dark":"light";
  document.documentElement.dataset.theme=next; localStorage.setItem("erpa-theme",next);
}
function openMenu(){ $("#sidebar").classList.add("open"); $("#scrim").hidden=false; }
function closeMenu(){ $("#sidebar").classList.remove("open"); $("#scrim").hidden=true; }
window.addEventListener("hashchange",()=>renderStage(location.hash.slice(1)));
$("#menu").onclick=openMenu; $("#scrim").onclick=closeMenu;
$("#explorer-toggle").onclick=()=>toggleExplorer(); $("#explorer-refresh").onclick=loadExplorerCatalog; $("#explorer-filter").oninput=renderExplorerTables; $("#explorer-prev").onclick=()=>selectExplorerTable(explorerState.selected,Math.max(0,explorerState.offset-explorerState.limit)); $("#explorer-next").onclick=()=>selectExplorerTable(explorerState.selected,explorerState.offset+explorerState.limit);
initializeExplorerResize(); renderSidebar(); renderStage(location.hash.slice(1)); loadExplorerCatalog(); loadRecentActivity(); connectActivity();
