/* ERPA / MemoRizz appbook — focused interactive agent-harness path. */
const API="/api/workshop";
const COMPONENT_ROWS=[
  ["Agent loop","MemAgent","Context → model/tool iterations → persistence","Built in"],
  ["Construction","MemAgentBuilder","Composes model, policy, memory, tools, skills, MCP","Built in"],
  ["Memory substrate","OracleProvider","Durable Oracle vector retrieval and writes","Built in"],
  ["Application memory","Assistant mode","Conversation, KB, persona, entity, short-term, summaries","Built in"],
  ["Semantic cache","SemanticCache / CacheManager","Skips repeat inference inside a governed scope","Built in"],
  ["Function tools","Toolbox / ToolManager","Persists metadata; executes trusted callables","Built in"],
  ["Skills","Skillbox","Semantically retrieved procedures with lifecycle and authority","Built in"],
  ["MCP","MCPClientManager","Notion transport, auth, policy, result limits, audit","Built in"],
  ["Sandbox","SandboxManager + E2B","Runs generated or skill code outside the host","Built in"],
  ["Context","Summaries + TOOL_LOG","Compaction and expandable result pointers","Built in"],
  ["Orchestration","MultiAgentOrchestrator + SharedMemory","Delegation and consolidation","Built in"],
  ["Human approval","Durable approval checkpoints","Controls external mutations","Built in"]
];

const CHAPTERS=[
  {id:"overview",n:"01",title:"Use case & harness map",tag:"Start here",
   blurb:"ERPA is an evidence-led retail-planning assistant for Alex Moreau. The lesson is the policy-bearing system around the model—not a clever prompt in isolation.",
   decision:"Facts, memory, procedures, side effects, and human authority must stay separate so each can be governed and audited.",
   sections:[
     {title:"The scenario in eight steps",ordered:[
       "Alex asks ERPA for the morning brief or a focused operating question.",
       "The harness scopes identity: user, durable memory workspace, and conversation thread.",
       "Oracle’s semantic cache is checked before paying for inference.",
       "Assistant-mode memories and only the relevant Skillbox procedures are retrieved.",
       "The agent discovers a small set of trusted tools and delegates independent research when useful.",
       "Inventory, sales, margin, and competitor evidence are separated into new actions and already-handled items.",
       "Advice returns immediately; email and Notion changes become reviewable proposals.",
       "A human approves one concrete mutation, which executes through an audited boundary." ]},
     {title:"Harness assembly and runtime",text:"MemAgentBuilder composes the OpenAI model adapter, ERPA instruction and persona, Assistant mode, OracleProvider, semantic cache, Toolbox, Skillbox, Notion MCP, E2B, continual learning, and loop limits. The appbook keeps this in one live factory so individual UI handlers do not rebuild harness policy."},
   ],
   flows:[
     {title:"Decision flow",nodes:["Alex’s request","Scope identity","Cache?","Recall memory + skills","Discover tools","Delegate + execute","Assemble brief","Side effect?","Approve + audit"]},
     {title:"Application sequence",nodes:["App","MemAgent","Oracle cache","Oracle memory","Skillbox","Toolbox + MCP","E2B / delegates","Answer + durable write"]}
   ],
   architecture:true,
   table:{columns:["Harness concern","MemoRizz component","Role in ERPA","Status"],rows:COMPONENT_ROWS}},

  {id:"memory",n:"02",title:"Agent memory",tag:"Assistant mode",
   blurb:"Assistant mode activates conversation, knowledge, persona, entity, short-term, and summary memory. ERPA adds workflow memory, Skillbox, and tool-log storage for learning and context control.",
   decision:"Memory types have different owners, lifetimes, retrieval policies, and failure modes. A single undifferentiated transcript cannot safely replace them.",
   sections:[{title:"Identity isolation",text:"memory_id names the durable ERPA workspace, thread_id identifies one ordered conversation, and user_id binds retrieval, skills, and cache entries to Alex."},
     {title:"Oracle and prompt composition",text:"OracleProvider stores durable memory and uses the in-database ALL_MINILM_L12_V2 embedding model. MemoRizz assembles runtime policy, the ERPA developer instruction, persona, retrieved memory and skills, disclosed tool schemas, then the user request in authority order."},
     {title:"Benefits",text:"The assistant can remember scope and operating rules, suppress work already handled, resume conversations, compact older context, and share approved evidence across delegates without leaking another user’s state."}],
   flows:[{title:"Assistant-mode context",nodes:["Conversation","Knowledge","Persona","Entity","Short-term","Summaries","Context for model","Workflow + Skillbox + Tool log"]}],
   experience:"memory"},

  {id:"tools",n:"03",title:"Tools & execution",tag:"Toolbox",
   blurb:"Trusted Python functions expose narrow Oracle operations. MemoRizz’s Toolbox persists searchable metadata, while two stable meta-tools progressively disclose and invoke only the relevant functions.",
   decision:"Progressive disclosure saves prompt tokens and reduces accidental tool choice, but discovery never grants execution authority: invocation is still bound to a host allowlist and an exact signature.",
   sections:[{title:"Deterministic metadata",text:"Registration uses augment=False and a metadata-only provider that fails closed if a future edit accidentally requests LLM augmentation. Function signatures remain the source of truth."},
     {title:"Authoritative data and isolated computation",text:"Business facts remain outside prompts and memory. Narrow tools read product, inventory, paid-order, sales, margin, and competitor tables with bound arguments. Generated analysis code runs through MemoRizz SandboxManager in an E2B microVM; database credentials remain on the host."}],
   flows:[{title:"DeterministicToolMetadataOnly registration",nodes:["Trusted Python function","Inspect signature","Register with augment=False","Oracle TOOLBOX metadata","Semantic discovery","Allowlisted invocation"]}],
   table:{columns:["Tool","What it does","Output","Boundary"],rows:[
     ["morning_brief_inputs","Reads low stock and open POs","Actions + suppressions","No general SQL"],
     ["inventory_status","Filters stock by product/region","Size-level rows","Bound parameters"],
     ["sales_signal","Compares current and prior weeks","Units, baseline, change","Fixed metric"],
     ["regional_profitability","Ranks governed margin","Value + percentage","Definition fixed in code"],
     ["competitor_insight","Reads curated signals","Date, observation, URL","No invented browsing"],
     ["customer_demand","Aggregates paid orders by product","Customers + purchased units","No customer PII"],
     ["paid_sales_by_region","Ranks paid products within each sales market","Regional top products + chart series","Paid orders only"],
     ["create_email_draft","Creates reviewable content","Draft + proposal ID","Cannot send"]]},
   experience:"tools"},

  {id:"skills",n:"04",title:"Skills & disclosure",tag:"Oracle Skillbox",
   blurb:"Twenty useful retail-planning procedures are persisted in Oracle Skillbox rather than pasted into every prompt. Only the few that match the request enter ERPA’s context window.",
   decision:"Tool schemas describe capabilities; skills describe reusable procedures. Retrieve each independently and disclose only what semantically matches the current task.",
   sections:[{title:"Lifecycle and authority",text:"Skillbox records carry status, preconditions, queries, tools used, user scope, and an injection role. Continual learning can capture workflows, shadow-evaluate them, and promote only after policy thresholds are met."}],
   flows:[{title:"Progressive skill disclosure",nodes:["User request","Skillbox vector match","Status + user scope","Inject matching procedure","Execute allowlisted tools"]}],
   experience:"skills"},

  {id:"mcp",n:"05",title:"MCP & Notion",tag:"External collaboration",
   blurb:"ERPA uses Notion to read operating context and prepare merchandising updates. MemoRizz connects to Notion’s streamable HTTP MCP endpoint with bearer-token or OAuth authentication.",
   decision:"MCP expands the capability boundary. Transport, authentication, retries, result-size limits, mutation approval, and audit belong to the harness—not to prompt convention.",
   sections:[{title:"ERPA’s Notion use",text:"A morning brief may incorporate Notion guidance, then prepare an exact page update. The appbook drafts the title and content, but the mutation remains blocked until a human approves that specific proposal."}],
   flows:[{title:"Notion mutation path",nodes:["ERPA draft","MCP policy","Exact proposal","Human review","Approved mcp_call_tool","Audit result"]}],
   action:{label:"Draft Notion update",name:"notion_draft"}},

  {id:"context",n:"06",title:"Context engineering",tag:"Compact, offload, disclose",
   blurb:"Retrieval chooses relevant facts; summarisation preserves meaning; compaction replaces older detail with references; progressive disclosure keeps tools and skills out of context until needed.",
   decision:"Context is a finite operational budget. The harness must decide what stays inline, what becomes a lossless pointer, and what can be expanded later—not merely truncate tokens at the model boundary.",
   sections:[{title:"MemoRizz behavior",text:"Large tool results move to Oracle TOOL_LOG when they exceed 500 characters, leaving one expandable pointer. Summary records retain source IDs. The retrieval tool itself must never be re-offloaded or it can create pointer-to-pointer loops."}],
   flows:[{title:"Compaction pipeline",nodes:["Full history + all schemas","Retrieve relevant memory","Summarise older turns","Offload large tool output","Disclose matching tools/skills","Smaller accountable context"]}],
   experience:"context"},

  {id:"cache",n:"07",title:"Semantic cache",tag:"Before inference",
   blurb:"A scoped Oracle vector lookup happens before context construction. A sufficiently similar, unexpired query can return without invoking the model or tools.",
   decision:"Caching is a routing decision, not a memory pasted into the prompt. Similarity does not establish freshness, so inventory mutations require invalidation and the TTL must match the business domain.",
   sections:[{title:"Why it matters",text:"A warm hit avoids model latency and token cost. The notebook’s live run persisted one Oracle cache row, incremented hit_count, returned the same answer, and was materially faster on the second request."}],
   flows:[{title:"Cache path",nodes:["Scoped query","Oracle embedding","Vector match ≥ 0.86?","Warm: return","Cold: memory + model + tools","Store response + TTL"]}],
   experience:"cache"},

  {id:"delegation",n:"08",title:"Orchestration & shared memory",tag:"Scale the harness",
   blurb:"ERPA delegates independent inventory/sales and competitor tasks to specialist MemAgents, then consolidates their outputs through shared workflow memory.",
   decision:"Delegation scales capability only when task ownership, evidence exchange, completion events, and final responsibility remain explicit. Shared memory is the coordination protocol—not a shared unbounded transcript.",
   sections:[{title:"The pattern",text:"The root decomposes the morning brief into bounded subtasks. Specialists run in parallel against the same scoped business context. Shared memory records workflow_start, decomposition, task start/completion, and workflow_complete so the root can consolidate and an operator can audit."},
     {title:"Why shared context matters",text:"Without a governed blackboard, delegates repeat work, lose suppressions, disagree on definitions, or leak context between users. Shared records give each specialist the minimum approved evidence while the root remains accountable for the final answer."}],
   flows:[{title:"Delegation",nodes:["ERPA root","Task decomposition","Brief specialist"],branches:["Market specialist","Shared Oracle blackboard","Consolidated morning brief"]}],
   experience:"orchestration"},

  {id:"hitl",n:"09",title:"Human in the loop",tag:"External side effects",
   blurb:"Advice and drafting may proceed automatically. Sending email or mutating Notion pauses on a concrete proposal that the host application owns.",
   decision:"Approval state must live outside the model’s tool surface. The model cannot approve its own action, reinterpret an old approval, or broaden one approved mutation into another.",
   sections:[{title:"MemoRizz today",text:"MemoRizz 0.5 provides durable approval proposals and structured ApprovalResumeResult evidence. The teaching profile makes the proposal explicit and resumes only by proposal ID without performing an external mutation; the live harness can retain the exact tool result, optional model continuation, consumption state, and error evidence separately."}],
   flows:[{title:"Approval sequence",nodes:["Draft exact action","Persist pending proposal","Show destination + content","Human approves ID","Execute once","Audit outcome"]}],
   action:{label:"Draft email",name:"approval_draft"}},

  {id:"scenarios",n:"10",title:"Functional scenarios",tag:"Acceptance suite",
   blurb:"Seven scenarios probe different seams of the same harness: brief composition, inventory, sales, governed profitability, competitor evidence, email drafting, and Notion drafting.",
   decision:"A workshop scenario should assert business evidence, not merely that the model returned non-empty text. Each response has visible anchors that can fail.",
   sections:[{title:"Expected evidence",text:"Morning brief: 3 actions + PO-BER-THC-OPEN. Inventory: XS/M/L/XXL. Sales: 101 vs 26. Profitability: UK £173,000. Competitors: both dates and URLs. Communications: drafted, never silently executed."}],
   action:{label:"Run scenario",name:"scenario",input:{kind:"select",field:"question",label:"Scenario",options:[
     ["Prepare my morning brief.","Morning brief"],["Show ThermaCore inventory across all regions and sizes.","Inventory status"],
     ["Why did WarmLayer spike in the UK this week?","Sales signal"],["Rank regions by profitability using our governed definition.","Profitability"],
     ["What competitor signals matter for WarmLayer?","Competitor insight"],["Draft an email with today's morning brief. Do not send it.","Email draft"],
     ["Draft, but do not execute, a Notion update for today's brief.","Notion draft"]]}}},

  {id:"cleanup",n:"11",title:"Scoped cleanup",tag:"Repeatable runs",
   blurb:"The workshop removes only its own appbook records, cache entries, tool logs, shared events, and approval proposals so the next learner starts from a known state.",
   decision:"Cleanup is part of harness operability. It must be scoped by ownership and identity—never drop unrelated schemas, package tables, or business data as a convenience.",
   sections:[{title:"What happens",text:"The action reports counts before deletion and removes only course_* tables inside the local appbook store. The following request idempotently reseeds the fixture."}],
   flows:[{title:"Reset contract",nodes:["Resolve owned tables","Count records","Delete scoped rows","Preserve unrelated state","Idempotent reseed next request"]}],
   action:{label:"Run scoped cleanup",name:"cleanup",danger:true}},

  {id:"storefront",n:"12",title:"Kata ecommerce store",tag:"Customer experience",
   blurb:"The final section turns the harness into a complete retail experience: a browsable catalogue, live availability, a persisted bag, and a floating ERPA assistant grounded in the same product and inventory data.",
   decision:"The customer interface is another channel into the same governed MemAgent. It can read catalogue and inventory facts, but business actions and external side effects retain their existing tool and approval boundaries.",
   sections:[{title:"One harness, another channel",text:"Store questions use the ERPA persona, Assistant-mode memory, progressive Skillbox and Toolbox context, and the OracleProvider target. Adding to the bag creates a visible database write in the data explorer."}],
   experience:"storefront"}
];

const $=selector=>document.querySelector(selector);
const esc=value=>String(value??"").replace(/[&<>"']/g,char=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[char]));
let result=null;
let view="answer";

function sidebar(){
  $("#chapters").innerHTML=CHAPTERS.map(c=>`<a class="nav" data-id="${c.id}" href="#${c.id}"><span class="num">${c.n}</span><span>${esc(c.title)}</span></a>`).join("");
}

function markdown(text){
  let out="",list=false;
  for(const raw of esc(text).split("\n")){
    const line=raw.replace(/\*\*(.*?)\*\*/g,"<strong>$1</strong>").replace(/\`(.*?)\`/g,"<code>$1</code>").replace(/(https:\/\/[^\s<]+)/g,'<a href="$1" target="_blank" rel="noreferrer">$1</a>');
    if(line.startsWith("## ")){if(list){out+="</ul>";list=false}out+=`<h2>${line.slice(3)}</h2>`}
    else if(line.startsWith("### ")){if(list){out+="</ul>";list=false}out+=`<h3>${line.slice(4)}</h3>`}
    else if(line.startsWith("- ")){if(!list){out+="<ul>";list=true}out+=`<li>${line.slice(2)}</li>`}
    else if(!line.trim()){if(list){out+="</ul>";list=false}}
    else{if(list){out+="</ul>";list=false}out+=`<p>${line}</p>`}
  }
  if(list)out+="</ul>";
  return out;
}

function flow(flow){
  const nodes=[...(flow.nodes||[]),...(flow.branches||[])];
  return `<section class="flow"><h3>${esc(flow.title)}</h3><div class="flow-track">${nodes.map((node,index)=>`<div class="flow-node"><span>${String(index+1).padStart(2,"0")}</span>${esc(node)}</div>${index<nodes.length-1?'<i class="flow-arrow">→</i>':''}`).join("")}</div></section>`;
}

const REFERENCE_NODES=[
  {id:"planner",x:80,y:56,w:190,h:54,href:"overview",kind:"channel",title:"Retail planner",sub:"Alex / operator",tip:"An authenticated user enters through an application channel; user, thread, and memory scope travel with the request."},
  {id:"notebook",x:315,y:56,w:190,h:54,href:"overview",kind:"channel",title:"Course notebook",sub:"learning channel",tip:"The standalone notebook exercises the same harness contracts with transparent setup and acceptance checks."},
  {id:"store",x:550,y:56,w:190,h:54,href:"storefront",kind:"channel",title:"KATA storefront",sub:"customer channel",tip:"The ecommerce experience uses ERPA for catalogue, inventory, demand, and scenario questions."},
  {id:"api",x:315,y:156,w:425,h:58,href:"overview",kind:"application",title:"ERPA application boundary",sub:"API · identity · request lifecycle · UI state",tip:"The host application owns authentication, scoped IDs, request lifecycle, proposals, and presentation."},
  {id:"builder",x:74,y:300,w:190,h:58,href:"overview",kind:"control",title:"MemAgentBuilder",sub:"construction-time composition",tip:"Composes the model, instruction, persona, Assistant mode, Oracle provider, tools, skills, MCP, cache, sandbox, and loop limits."},
  {id:"policy",x:74,y:388,w:190,h:58,href:"memory",kind:"control",title:"Instruction + persona",sub:"authority and identity",tip:"ERPA's stable developer instruction and persona are composed above retrieved memory and tool output."},
  {id:"scope",x:74,y:476,w:190,h:58,href:"memory",kind:"control",title:"Scope + policy",sub:"user · memory · thread",tip:"Identity, tool allowlists, cache scope, TTLs, and side-effect policy constrain every turn."},
  {id:"runtime",x:304,y:292,w:516,h:72,href:"memory",kind:"runtime",title:"MemoRizz MemAgent runtime",sub:"bounded agent loop · observe → decide → act → persist",tip:"The central control loop assembles context, invokes the model, validates capability calls, observes results, and persists the turn."},
  {id:"cache",x:304,y:400,w:154,h:62,href:"cache",kind:"service",title:"Cache router",sub:"pre-inference",tip:"Checks a scoped semantic cache before context construction; a valid warm hit bypasses model inference."},
  {id:"context",x:480,y:400,w:164,h:62,href:"context",kind:"service",title:"Context engine",sub:"retrieve · compact · disclose",tip:"Retrieves memory, summarises history, offloads large results, and discloses only relevant tools and skills."},
  {id:"model",x:666,y:400,w:154,h:62,href:"overview",kind:"model",title:"Model adapter",sub:"bounded prompt + tool calls",tip:"Normalises provider generation and tool calling. The model proposes; the harness owns memory, execution, and approval."},
  {id:"tools",x:304,y:500,w:154,h:62,href:"tools",kind:"service",title:"Tool router",sub:"discover · validate · invoke",tip:"Discovers narrow Toolbox schemas and invokes only trusted host functions with validated arguments."},
  {id:"skills",x:480,y:500,w:164,h:62,href:"skills",kind:"service",title:"Skill retrieval",sub:"progressive procedures",tip:"Queries active Skillbox procedures by semantic fit and injects only the few relevant to the current request."},
  {id:"orchestrator",x:666,y:500,w:154,h:62,href:"delegation",kind:"service",title:"Orchestrator",sub:"delegate · consolidate",tip:"Decomposes independent work, runs specialist MemAgents, and consolidates bounded evidence through shared memory."},
  {id:"openai",x:918,y:292,w:208,h:58,href:"overview",kind:"external",title:"OpenAI model",sub:"inference provider",tip:"Receives the final bounded context and returns text or a proposed tool call through the MemoRizz model adapter."},
  {id:"e2b",x:918,y:378,w:208,h:58,href:"tools",kind:"external",title:"E2B sandbox",sub:"isolated code execution",tip:"Runs model-generated or skill computation in a restricted microVM; Oracle and application credentials stay on the host."},
  {id:"notion",x:918,y:464,w:208,h:58,href:"mcp",kind:"external",title:"Notion MCP",sub:"streamable HTTP",tip:"Reads collaboration context and exposes governed Notion mutations through authenticated MCP transport."},
  {id:"approval",x:918,y:550,w:208,h:58,href:"hitl",kind:"approval",title:"Human approval",sub:"durable side-effect gate",tip:"A person reviews one exact email or Notion proposal before that mutation can resume and execute."},
  {id:"specialists",x:918,y:636,w:208,h:58,href:"delegation",kind:"external",title:"Specialist MemAgents",sub:"brief + market delegates",tip:"Bounded specialists work in parallel while the root ERPA agent remains accountable for the final response."},
  {id:"memory",x:66,y:764,w:164,h:62,href:"memory",kind:"database",title:"Memory stores",sub:"conversation · KB · entity · summary",tip:"Oracle persists Assistant-mode memory with user, memory, and thread isolation."},
  {id:"cacheStore",x:244,y:764,w:146,h:62,href:"cache",kind:"database",title:"Semantic cache",sub:"vectors · TTL · hit count",tip:"Oracle stores query embeddings, responses, freshness metadata, and hit counts for pre-inference reuse."},
  {id:"skillStore",x:404,y:764,w:146,h:62,href:"skills",kind:"database",title:"Skillbox",sub:"active procedures",tip:"Oracle stores governed skills, lifecycle status, authority, preconditions, and tool dependencies."},
  {id:"toolStore",x:564,y:764,w:164,h:62,href:"tools",kind:"database",title:"Toolbox + tool log",sub:"schemas · result pointers",tip:"Oracle stores searchable tool metadata and offloaded results that can be expanded just in time."},
  {id:"sharedStore",x:742,y:764,w:146,h:62,href:"delegation",kind:"database",title:"Shared memory",sub:"workflow blackboard",tip:"Oracle records delegation lifecycle events and approved evidence exchanged between root and specialist agents."},
  {id:"businessStore",x:902,y:764,w:224,h:62,href:"tools",kind:"database",title:"Retail systems of record",sub:"products · inventory · orders · sales · margin",tip:"Authoritative operational facts remain outside model memory and are accessed only through narrow trusted tools."}
];

function referenceNode(node){
  return `<a class="ra-link" href="#${node.href}" data-tip="${esc(node.tip)}" aria-label="${esc(node.title)}: ${esc(node.tip)}"><title>${esc(node.tip)}</title><g class="ra-node ${node.kind}" transform="translate(${node.x} ${node.y})"><rect width="${node.w}" height="${node.h}" rx="8"/><text class="ra-title" x="${node.w/2}" y="${node.h/2-4}" text-anchor="middle">${esc(node.title)}</text><text class="ra-sub" x="${node.w/2}" y="${node.h/2+15}" text-anchor="middle">${esc(node.sub)}</text></g></a>`;
}

function referenceArchitecture(){
  return `<section class="reference-architecture"><div class="architecture-head"><div><span class="eyebrow">Technical reference architecture</span><h2>ERPA / MemoRizz logical architecture</h2></div><p>A layered logical view with explicit trust boundaries, control flow, execution services, and data services. Hover or focus a component; click to open its lesson.</p></div>
    <div class="reference-svg-wrap"><svg class="reference-svg" viewBox="0 0 1200 870" role="img" aria-labelledby="ra-title ra-desc"><title id="ra-title">ERPA on MemoRizz technical reference architecture</title><desc id="ra-desc">Application channels enter an ERPA application boundary, which invokes a MemoRizz MemAgent control plane. The harness routes model inference, tools, skills, sandbox execution, MCP, delegation and human approval while Oracle AI Database provides durable data services.</desc>
      <defs><marker id="arrow-main" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse"><path d="M0 0L10 5L0 10z"/></marker><marker id="arrow-read" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse"><path d="M0 0L10 5L0 10z"/></marker><marker id="arrow-action" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse"><path d="M0 0L10 5L0 10z"/></marker></defs>
      <rect class="ra-zone channel-zone" x="40" y="26" width="780" height="108" rx="12"/><text class="ra-zone-label" x="56" y="48">EXPERIENCE CHANNELS</text>
      <rect class="ra-zone application-zone" x="40" y="142" width="780" height="88" rx="12"/><text class="ra-zone-label" x="56" y="164">APPLICATION TRUST BOUNDARY</text>
      <rect class="ra-zone harness-zone" x="40" y="254" width="800" height="352" rx="12"/><text class="ra-zone-label" x="56" y="278">MEMORIZZ AGENT HARNESS · CONTROL PLANE</text>
      <rect class="ra-zone external-zone" x="884" y="254" width="276" height="460" rx="12"/><text class="ra-zone-label" x="900" y="278">EXTERNAL EXECUTION SERVICES</text>
      <rect class="ra-zone oracle-zone" x="40" y="728" width="1120" height="124" rx="12"/><text class="ra-zone-label" x="56" y="750">ORACLE AI DATABASE · MEMORY AND BUSINESS DATA PLANE</text>

      <g class="ra-flows">
        <path class="main" d="M175 110V156"/><path class="main" d="M410 110V156"/><path class="main" d="M645 110V156"/>
        <path class="main" d="M528 214V292"/><text x="540" y="250">scoped request</text>
        <path class="policy" d="M264 329H304"/><path class="policy" d="M264 417H480"/><path class="policy" d="M264 505H304"/>
        <path class="main" d="M430 364V400"/><path class="main" d="M458 431H480"/><text x="460" y="420">miss</text>
        <path class="main" d="M644 431H666"/><path class="return" d="M381 400V242H315"/><text x="325" y="257">valid cache hit</text>
        <path class="action" d="M820 431H918"/><path class="return" d="M918 335H820"/>
        <path class="main" d="M408 364V500"/><path class="main" d="M562 462V500"/><path class="main" d="M743 462V500"/>
        <path class="action" d="M458 531H870V407H918"/><path class="action" d="M458 531H870V493H918"/>
        <path class="action" d="M1022 522V550"/><path class="action" d="M1126 579H1142V493H1126"/>
        <path class="action" d="M820 531H870V665H918"/>
        <path class="read" d="M562 462V694H148V764"/><path class="read" d="M381 462V716H317V764"/>
        <path class="read" d="M562 562V764"/><path class="read" d="M381 562V702H646V764"/>
        <path class="read" d="M743 562V710H815V764"/><path class="read" d="M458 531H470V700H1014V764"/>
        <path class="return" d="M304 328H286V204H315"/><text x="84" y="620">response + trace returns through application boundary</text>
      </g>
      ${REFERENCE_NODES.map(referenceNode).join("")}
    </svg></div>
    <div class="architecture-inspector" id="architecture-tooltip"><span>Component inspector</span><strong>Hover or focus a component</strong><p>Each block links to the appbook lesson that demonstrates the responsibility.</p></div>
    <div class="architecture-legend"><span><i class="legend-line main"></i>request / control flow</span><span><i class="legend-line read"></i>retrieval / persistence</span><span><i class="legend-line action"></i>external execution</span><span><i class="legend-dot oracle"></i>Oracle data service</span></div></section>`;
}

function bindReferenceArchitecture(){
  const inspector=$("#architecture-tooltip");if(!inspector)return;
  const reset=()=>inspector.innerHTML="<span>Component inspector</span><strong>Hover or focus a component</strong><p>Each block links to the appbook lesson that demonstrates the responsibility.</p>";
  document.querySelectorAll(".ra-link").forEach(link=>{
    const show=()=>{const title=link.querySelector(".ra-title")?.textContent||"Component";inspector.innerHTML=`<span>Selected component</span><strong>${esc(title)}</strong><p>${esc(link.dataset.tip)}</p>`};
    link.addEventListener("mouseenter",show);link.addEventListener("focus",show);
    link.addEventListener("mouseleave",reset);link.addEventListener("blur",reset);
  });
}

function table(spec){
  if(!spec)return"";
  return `<div class="table-wrap"><table><thead><tr>${spec.columns.map(c=>`<th>${esc(c)}</th>`).join("")}</tr></thead><tbody>${spec.rows.map(row=>`<tr>${row.map(cell=>`<td>${esc(cell)}</td>`).join("")}</tr>`).join("")}</tbody></table></div>`;
}

function section(item){
  let body="";
  if(item.text)body+=`<p>${esc(item.text)}</p>`;
  if(item.code)body+=`<pre class="lesson-code"><code>${esc(item.code)}</code></pre>`;
  if(item.list)body+=`<ul>${item.list.map(value=>`<li>${esc(value)}</li>`).join("")}</ul>`;
  if(item.ordered)body+=`<ol>${item.ordered.map(value=>`<li>${esc(value)}</li>`).join("")}</ol>`;
  if(item.links)body+=`<ul class="links">${item.links.map(([label,url])=>`<li><a href="${esc(url)}" target="_blank" rel="noreferrer">${esc(label)} ↗</a></li>`).join("")}</ul>`;
  return `<article class="lesson-card"><h2>${esc(item.title)}</h2>${body}</article>`;
}

function experienceMarkup(chapter){
  if(chapter.experience==="memory")return `<section class="experience chat-experience"><div class="experience-head"><div><span class="eyebrow">MemAgent conversation</span><h2>Start, resume, and inspect memory threads</h2></div><span class="live-badge">MemAgent · OracleProvider</span></div><div class="memory-workspace"><aside class="thread-rail"><header><span>Conversation threads</span><button class="primary" id="memory-new-thread">+ New</button></header><div id="memory-thread-list"><p class="muted">Loading threads…</p></div></aside><div class="chat-shell"><div class="thread-current"><span>Active thread</span><code id="memory-thread-current">erpa-appbook-thread</code></div><div class="chat-messages" id="memory-chat"><div class="chat-bubble assistant"><small>ERPA</small><p>Ask what I remember about Alex, ThermaCore, the morning brief, or profitability. The exact assembled context appears beside this chat.</p></div></div><form class="chat-compose" id="memory-chat-form"><input id="memory-chat-input" value="What have I already decided about ThermaCore?" aria-label="Message ERPA"/><button class="primary">Send</button></form></div><aside class="context-inspector"><div class="inspector-head"><span>Current inference context</span><strong id="context-token-total">Waiting for a turn</strong></div><div id="context-window" class="context-window"><p class="muted">Prompt, persona, retrieved memory units, injected skills, tool schemas, and the active thread will appear here in provider order.</p></div></aside></div></section>`;
  if(chapter.experience==="tools")return `<section class="experience"><div class="experience-head"><div><span class="eyebrow">Tool + execution lab</span><h2>Watch ERPA discover, validate, execute, and isolate</h2></div><span class="live-badge">Toolbox → E2B</span></div><div class="experience-split"><div class="chat-shell"><div class="chat-messages" id="tools-chat"><div class="chat-bubble assistant"><small>ERPA</small><p>Ask me to inspect inventory, calculate a sales change, rank margin, or review competitor evidence.</p></div></div><form class="chat-compose" id="tools-chat-form"><input id="tools-chat-input" value="Show ThermaCore inventory and calculate the total shortfall."/><button class="primary">Use tools</button></form></div><aside class="execution-inspector"><div class="inspector-head"><span>Execution pipeline</span><strong id="sandbox-state">Idle</strong></div><div id="tool-stages" class="execution-stages"><p class="muted">Toolbox discovery and E2B console output will stream into this pane.</p></div><div class="sandbox-console" id="sandbox-console"><header><span></span><span></span><span></span><strong>E2B / code-interpreter-v1</strong></header><pre>$ waiting for isolated code…</pre></div></aside></div></section>`;
  if(chapter.experience==="skills")return `<section class="experience"><div class="experience-head"><div><span class="eyebrow">Progressive disclosure lab</span><h2>Twenty stored skills, a few injected</h2></div><span class="live-badge">Oracle Skillbox</span></div><div class="skill-query"><input id="skill-query" value="Prepare Alex's morning brief with an approved Notion update"/><button class="primary" id="skill-query-button">Retrieve matching skills</button></div><div class="experience-split skill-layout"><div><h3 class="pane-title">Available Skillbox records <span id="skill-count"></span></h3><div id="skill-catalog" class="skill-catalog"></div></div><aside class="context-inspector"><div class="inspector-head"><span>Injected into this turn</span><strong id="skill-injected-count">0 skills</strong></div><div id="skill-context" class="context-window"><p class="muted">Run semantic retrieval to see which procedures enter the context window.</p></div></aside></div></section>`;
  if(chapter.experience==="context")return `<section class="experience"><div class="experience-head"><div><span class="eyebrow">Interactive context engineering lab</span><h2>Send one query through two context strategies</h2></div><div class="context-actions"><button class="secondary" id="context-summarize">Summarise conversation</button><button class="secondary" id="context-offload">Offload tools</button></div></div><form class="shared-query" id="context-form"><input id="context-input" value="Can you show me a chart of the region revenue?"/><button class="primary" id="context-submit">Send to both</button></form><div class="context-lab-grid"><article class="context-agent"><header><div><strong>Full-context agent</strong><small>All schemas, calls, and tool outputs remain inline</small></div><div class="context-agent-metrics"><i id="baseline-agent-state">Ready</i><span id="before-tokens">0 tokens</span></div></header><div class="mini-chat" id="context-baseline-chat"></div><div id="context-before" class="context-window"><p class="muted">The complete schema catalogue, validated calls, and returned tool messages will appear here in model-input order.</p></div></article><article class="context-agent engineered"><header><div><strong>Engineered-context agent</strong><small>Relevant schemas, calls, outputs, summaries, and pointers</small></div><div class="context-agent-metrics"><i id="engineered-agent-state">Ready</i><span id="after-tokens">0 tokens</span></div></header><div class="mini-chat" id="context-engineered-chat"></div><div id="context-after" class="context-window"><p class="muted">Only progressively disclosed schemas and the exact current tool exchange will enter this model context.</p></div></article></div><div class="jit-panel"><div><span class="eyebrow">Just-in-time recovery</span><p>The next query expands summary and tool pointers when the current turn needs them.</p></div><pre id="jit-result" class="json">No recovery required yet.</pre></div></section>`;
  if(chapter.experience==="cache")return `<section class="experience"><div class="experience-head"><div><span class="eyebrow">Interactive A/B harness experiment</span><h2>Ask both agents and watch Oracle cache routing</h2></div><span class="live-badge">threshold ≥ 0.86</span></div><form class="shared-query" id="cache-form"><input id="cache-input" value="What is the current ThermaCore stock position by region and size?"/><button class="primary">Ask both agents</button></form><div class="cache-chat-grid"><article class="cache-agent"><header><span class="agent-avatar">A</span><div><strong>Cache disabled</strong><small>Always takes model + tool path</small></div><b id="baseline-latency">—</b></header><div class="mini-chat" id="baseline-chat"></div></article><article class="cache-agent cached"><header><span class="agent-avatar">B</span><div><strong>Oracle semantic cache</strong><small>Cold miss, then scoped warm hit</small></div><b id="cached-latency">—</b></header><div class="mini-chat" id="cached-chat"></div></article></div><div id="cache-summary" class="cache-summary"><p class="muted">Enter a query, then repeat it to observe a hit and measured latency reduction.</p></div></section>`;
  if(chapter.experience==="orchestration")return `<section class="experience"><div class="experience-head"><div><span class="eyebrow">Live multi-agent workflow</span><h2>Follow the active agent across a horizontal workflow</h2></div><span class="live-badge" id="orchestration-state">Idle</span></div><div class="orchestration-samples"><button data-workflow-query="Prepare Alex's morning brief with inventory, sales, and competitor evidence.">Morning brief</button><button data-workflow-query="Investigate ThermaCore stock, reconcile open purchase orders, measure WarmLayer sales, and compare the latest competitor signals before consolidating recommendations.">Trading investigation</button><button data-workflow-query="Review inventory risk and regional profitability, then assemble an executive brief with sourced market evidence.">Executive review</button></div><div class="orchestration-query"><input id="orchestration-query" value="Prepare Alex's morning brief with inventory, sales, and competitor evidence."/><button class="primary" id="orchestration-run">Run workflow</button></div><div class="agent-topology horizontal"><div class="agent-node root" data-stage="root" data-agent="ERPA"><span>01 · Root</span><strong>ERPA</strong><small>decompose request</small></div><i>→</i><div class="agent-node" data-stage="brief" data-agent="ERPA Brief Specialist"><span>02 · Delegate</span><strong>Brief specialist</strong><small>inventory + sales</small></div><i>→</i><div class="shared-node" data-stage="shared" data-agent="shared"><span>03 · Oracle</span><strong>Shared memory</strong><small>write blackboard</small></div><i>→</i><div class="agent-node" data-stage="market" data-agent="ERPA Market Specialist"><span>04 · Delegate</span><strong>Market specialist</strong><small>competitor evidence</small></div><i>→</i><div class="agent-node" data-stage="complete" data-agent="complete"><span>05 · Root</span><strong>Consolidate</strong><small>final accountability</small></div></div><div class="orchestration-panes"><div><h3 class="pane-title">Lifecycle events</h3><div id="orchestration-events" class="event-stream"></div></div><div><h3 class="pane-title">Selected agent context</h3><pre id="agent-context" class="json">Click a stage while the workflow runs.</pre></div></div></section>`;
  if(chapter.experience==="storefront")return `<section class="store-experience"><header class="store-nav"><strong>KATA / FIELD NOTES</strong><nav id="store-filters"><button class="store-filter active" data-category="all">All</button></nav><button class="bag-button">Bag <span id="bag-count">0</span></button></header><div class="store-hero"><div><span>AW26 · WEATHER SYSTEMS</span><h2>Built for the<br/><em>in-between.</em></h2><p>Twelve considered layers and accessories, grounded availability, and an assistant that understands both the catalogue and the retail operation.</p></div><div class="hero-orbit"><span>ERPA<br/>guided</span></div></div><section class="product-detail-page" id="product-detail" hidden></section><div class="product-grid" id="product-grid"><p class="muted">Loading catalogue…</p></div><button class="erpa-fab" id="erpa-fab" aria-label="Open ERPA store assistant"><span>ER</span><i></i></button><aside class="store-chat" id="store-chat" hidden><header><div><span class="agent-avatar">ER</span><div><strong>ERPA</strong><small>MemoRizz · Toolbox · E2B · Oracle memory</small></div></div><div class="store-chat-actions"><button id="store-chat-expand" aria-label="Open ERPA full screen" title="Full screen">⛶</button><button id="store-chat-close" aria-label="Close ERPA" title="Dismiss">×</button></div></header><div class="store-suggestions"><button data-store-prompt="What is the best-selling product?">Best seller</button><button data-store-prompt="Create a chart of regional stock for the RainShell Parka">Stock chart</button><button data-store-prompt="How many customers have bought it so far?">Customer demand</button><button data-store-prompt="Prepare my morning brief">Morning brief</button></div><div class="chat-messages" id="store-chat-messages"><div class="chat-bubble assistant"><small>ERPA</small><p>Ask about products, prices, sizes, live stock, paid customer demand, or layering. I can run trusted tools and render inventory charts inside E2B.</p></div></div><form class="chat-compose" id="store-chat-form"><input id="store-chat-input" placeholder="Ask about the collection or retail operation…"/><button class="primary">Send</button></form></aside></section>`;
  return "";
}

function contextBlock(item){
  const content=typeof item.content==="string"?item.content:JSON.stringify(item.content,null,2);
  return `<article class="context-block ${esc(item.state||item.role||"")}"><header><span>${esc(item.order||"•")} · ${esc(item.source||item.name||"context")}</span><strong>${esc(item.tokens||0)} tokens</strong></header><div class="context-role">${esc(item.role||item.state||"")}</div><pre>${esc(content||item.reference||"")}</pre>${item.reference?`<code>${esc(item.reference)}</code>`:""}</article>`;
}

function renderInferenceContext(snapshot,target="#context-window"){
  const pane=$(target);if(!pane||!snapshot)return;
  pane.innerHTML=(snapshot.blocks||[]).map(contextBlock).join("")||`<pre class="json">${esc(JSON.stringify(snapshot,null,2))}</pre>`;
  const total=$("#context-token-total");if(total)total.textContent=`${snapshot.estimated_tokens||0} / ${Number(snapshot.context_limit||0).toLocaleString()} estimated tokens`;
}

function appendChat(target,role,text,label=role==="user"?"You":"ERPA"){
  const pane=$(target);if(!pane)return;
  pane.insertAdjacentHTML("beforeend",`<div class="chat-bubble ${role}"><small>${esc(label)}</small><div>${role==="assistant"?markdown(text):`<p>${esc(text)}</p>`}</div></div>`);
  pane.scrollTop=pane.scrollHeight;
  return pane.lastElementChild;
}

function appendStoreResponse(data){
  const bubble=appendChat("#store-chat-messages","assistant",data.answer);
  if(!bubble)return;
  const body=bubble.querySelector(":scope > div");
  if(data.chart&&/^data:image\/png;base64,[A-Za-z0-9+/=]+$/.test(data.chart.data_url||"")){
    const figure=document.createElement("figure");figure.className="store-chart";
    const image=document.createElement("img");image.src=data.chart.data_url;image.alt=data.chart.alt||data.chart.title||"ERPA chart";
    const caption=document.createElement("figcaption");caption.textContent=`${data.chart.title} · ${data.chart.generated_by}`;
    figure.append(image,caption);body.append(figure);
  }
  if(data.execution){
    const details=document.createElement("details");details.className="store-execution";
    const summary=document.createElement("summary");
    const tool=data.execution.call?.tool_name||"Toolbox";
    const sandbox=data.sandbox?.executed?" → E2B complete":"";
    summary.textContent=`Execution evidence · ${tool}${sandbox}`;
    const pre=document.createElement("pre");pre.textContent=JSON.stringify({discovery:data.execution.discovery,call:{tool_name:data.execution.call?.tool_name,arguments_used:data.execution.call?.arguments_used},sandbox:data.sandbox?{executed:data.sandbox.executed,provider:data.sandbox.provider,template:data.sandbox.template,exit_code:data.sandbox.exit_code,metadata:data.sandbox.metadata}:null},null,2);
    details.append(summary,pre);body.append(details);
  }
  $("#store-chat-messages").scrollTop=$("#store-chat-messages").scrollHeight;
}

async function postAction(name,payload={}){
  return api(`${API}/actions/${name}`,{method:"POST",body:JSON.stringify({payload})});
}

function renderSkillCatalog(skills,injected=[]){
  const active=new Set(injected.map(item=>item.record_id));
  const catalog=$("#skill-catalog");if(catalog)catalog.innerHTML=(skills||[]).map(skill=>`<article class="skill-card ${active.has(skill.record_id)?"injected":""}"><header><span>${active.has(skill.record_id)?"Injected":"Active"}</span><strong>${esc(skill.name)}</strong></header><p>${esc(skill.content)}</p><small>${esc((skill.metadata?.tools||[]).join(" · "))}</small></article>`).join("");
  const count=$("#skill-count");if(count)count.textContent=`${(skills||[]).length} active`;
  const context=$("#skill-context");if(context)context.innerHTML=injected.length?injected.map(skill=>contextBlock({name:skill.name,state:"injected",tokens:Math.max(18,Math.round(skill.content.length/4)),content:skill.content,reference:`similarity ${skill.similarity}`})).join(""):'<p class="muted">No skill matched this request.</p>';
  const injectedCount=$("#skill-injected-count");if(injectedCount)injectedCount.textContent=`${injected.length} of ${(skills||[]).length} skills`;
}

function renderContextComparison(data){
  const baseline=data.baseline||data.before,engineered=data.engineered||data.after;
  $("#before-tokens").textContent=`${baseline.estimated_tokens} tokens`;
  $("#after-tokens").textContent=`${engineered.estimated_tokens} tokens`;
  $("#context-before").innerHTML=baseline.blocks.map(contextBlock).join("");
  $("#context-after").innerHTML=engineered.blocks.map(contextBlock).join("");
  if(data.recovery?.length)$("#jit-result").textContent=JSON.stringify(data.recovery,null,2);
}

function contextLoadingCard(label,index,state){
  return `<article class="context-load-stage ${state}" data-load-stage="${index}"><i></i><div><strong>${esc(label)}</strong><span>${state==="running"?"IN PROGRESS":"WAITING"}</span></div></article>`;
}

function beginContextLoading(){
  const stages=["Discover relevant Toolbox schemas","Validate the typed tool call","Execute the trusted Oracle function","Send tool output to the model"];
  let active=0;
  const paint=()=>{
    ["#context-before","#context-after"].forEach(selector=>{const pane=$(selector);if(pane)pane.innerHTML=`<div class="context-loading"><header><span class="context-spinner"></span><div><strong>Constructing inference context</strong><small>Observe each harness stage before synthesis</small></div></header>${stages.map((label,index)=>contextLoadingCard(label,index,index<active?"complete":index===active?"running":"waiting")).join("")}</div>`});
    $("#baseline-agent-state").textContent=stages[active]||"Synthesising";
    $("#engineered-agent-state").textContent=stages[active]||"Synthesising";
  };
  paint();
  const timer=setInterval(()=>{if(active<stages.length-1){active+=1;paint()}},650);
  const pending=[
    appendChat("#context-baseline-chat","assistant","Selecting a trusted tool and constructing the full model context…","Full-context agent"),
    appendChat("#context-engineered-chat","assistant","Disclosing the minimum tool set and constructing the engineered model context…","Engineered-context agent"),
  ];
  pending.forEach(item=>item?.classList.add("pending","context-pending"));
  return ()=>{clearInterval(timer);pending.forEach(item=>item?.remove())};
}

function appendContextResponse(target,data,label){
  const bubble=appendChat(target,"assistant",data.answer,label);
  const body=bubble?.querySelector(":scope > div");
  if(!body)return;
  if(data.chart&&/^data:image\/png;base64,[A-Za-z0-9+/=]+$/.test(data.chart.data_url||"")){
    const figure=document.createElement("figure");figure.className="context-chart";
    figure.innerHTML=`<img src="${data.chart.data_url}" alt="${esc(data.chart.alt)}"/><figcaption>${esc(data.chart.title)} · ${esc(data.chart.generated_by)}</figcaption>`;
    body.append(figure);
  }
  if(data.execution){
    const evidence=document.createElement("details");evidence.className="context-execution";
    evidence.innerHTML=`<summary>Tool exchange · ${esc(data.execution.call?.tool_name||"Toolbox")} · ${esc(data.execution.status||"complete")}</summary><pre>${esc(JSON.stringify({tool_call_id:data.execution.tool_call_id,disclosed:data.execution.discovery?.tools?.map(item=>item.name),call:data.execution.call,output:data.execution.output,sandbox:data.sandbox?{provider:data.sandbox.provider,executed:data.sandbox.executed,exit_code:data.sandbox.exit_code}:null},null,2))}</pre>`;
    body.append(evidence);
  }
}

function renderCacheRace(data){
  $("#baseline-latency").textContent=`${data.baseline.latency_ms.toFixed(2)} ms`;
  $("#cached-latency").textContent=`${data.cached.latency_ms.toFixed(2)} ms`;
  const match=data.cached.matched_query?`<p><strong>Semantic match:</strong> ${esc(data.cached.matched_query)}</p>`:"";
  $("#cache-summary").innerHTML=`<div class="metric-grid"><div class="metric"><span>Cache route</span><strong>${data.cached.cache_hit?"HIT":"MISS"}</strong></div><div class="metric"><span>Similarity</span><strong>${data.cached.similarity}</strong></div><div class="metric"><span>Hit count</span><strong>${data.cached.hit_count}</strong></div><div class="metric"><span>Measured speedup</span><strong>${data.speedup}×</strong></div></div>${match}<p>${esc(data.freshness_warning)}</p>`;
}

let orchestrationContexts={};
function setAgentState(name,state){const node=document.querySelector(`[data-agent="${CSS.escape(name)}"]`);if(node){node.classList.remove("running","complete");node.classList.add(state)}}
function setWorkflowStage(stage){
  const nodes=[...document.querySelectorAll("[data-stage]")],active=nodes.findIndex(node=>node.dataset.stage===stage);
  nodes.forEach((node,index)=>{node.classList.remove("running","complete");if(index<active)node.classList.add("complete");if(index===active)node.classList.add(stage==="complete"?"complete":"running")});
}
function appendOrchestrationEvent(event){
  const pane=$("#orchestration-events");if(!pane)return;
  pane.insertAdjacentHTML("beforeend",`<article class="event-row"><i></i><div><strong>${esc(event.entry_type)}</strong><span>${esc(event.agent_name)}</span></div><time>${new Date(event.created_at).toLocaleTimeString()}</time></article>`);pane.scrollTop=pane.scrollHeight;
  setWorkflowStage(event.stage||"root");
}

function renderProducts(catalog,category="all"){
  const grid=$("#product-grid");if(!grid)return;
  const products=catalog.products.filter(product=>category==="all"||product.category===category);
  grid.innerHTML=products.map(product=>`<article class="product-card" data-open-product="${product.product_id}" tabindex="0" role="link" aria-label="View ${esc(product.product_name)}"><div class="product-image"><img src="${esc(product.image)}" alt="Illustration of ${esc(product.product_name)}"/><span>${esc(product.category)}</span></div><div class="product-copy"><header><div><h3>${esc(product.product_name)}</h3><p>${esc(product.colour)}</p></div><strong>£${Number(product.price).toFixed(0)}</strong></header><p>${esc(product.tagline)}</p><div class="product-meta"><span>${product.total_stock} units</span><span>${esc(product.sizes.join(" · "))}</span></div><button class="store-add" data-product-id="${product.product_id}">Add to bag</button></div></article>`).join("");
  bindProductInteractions();
}

function bindCartButtons(root=document){
  root.querySelectorAll(".store-add").forEach(button=>button.onclick=async event=>{
    event.stopPropagation();
    const original=button.textContent;button.disabled=true;button.textContent="Adding…";
    const response=await postAction("cart_add",{product_id:Number(button.dataset.productId),quantity:1});
    $("#bag-count").textContent=response.catalog.cart_count;button.textContent="Added ✓";setTimeout(()=>{button.disabled=false;button.textContent=original},900);pollDataExplorer();
  });
}

function openProduct(productId){
  const product=window.erpaCatalog?.products.find(item=>item.product_id===Number(productId));if(!product)return;
  const detail=$("#product-detail"),rows=product.inventory||[];
  detail.innerHTML=`<button class="product-back" id="product-back">← Back to collection</button><div class="product-detail-layout"><div class="product-detail-image"><img src="${esc(product.image)}" alt="Illustration of ${esc(product.product_name)}"/><span>${esc(product.category)} · ${esc(product.colour)}</span></div><div class="product-detail-copy"><span class="eyebrow">KATA / FIELD NOTES</span><h2>${esc(product.product_name)}</h2><strong class="product-detail-price">£${Number(product.price).toFixed(0)}</strong><p class="product-detail-tagline">${esc(product.tagline)}</p><div class="product-detail-facts"><div><span>Available sizes</span><strong>${esc(product.sizes.join(" · "))}</strong></div><div><span>Live stock</span><strong>${product.total_stock} units</strong></div><div><span>Regions</span><strong>${esc(product.regions.join(" · "))}</strong></div></div><h3>Live regional availability</h3><div class="availability-list">${rows.map(row=>`<div><span>${esc(row.region)} · ${esc(row.size_code)}</span><strong>${row.on_hand} units</strong></div>`).join("")}</div><div class="product-detail-actions"><button class="store-add primary" data-product-id="${product.product_id}">Add to bag</button><button class="secondary" id="product-ask-erpa">Ask ERPA about this product</button></div></div></div>`;
  detail.hidden=false;$(".store-hero").hidden=true;$("#product-grid").hidden=true;$("#store-filters").hidden=true;
  $("#product-back").onclick=()=>{detail.hidden=true;$(".store-hero").hidden=false;$("#product-grid").hidden=false;$("#store-filters").hidden=false};
  $("#product-ask-erpa").onclick=()=>{$("#store-chat").hidden=false;$("#store-chat-input").value=`Tell me about the ${product.product_name}`;$("#store-chat-input").focus()};
  bindCartButtons(detail);detail.scrollIntoView({behavior:"smooth",block:"start"});
}

function bindProductInteractions(){
  bindCartButtons();
  document.querySelectorAll("[data-open-product]").forEach(card=>{
    card.onclick=event=>{if(!event.target.closest(".store-add"))openProduct(card.dataset.openProduct)};
    card.onkeydown=event=>{if(event.key==="Enter"||event.key===" "){event.preventDefault();openProduct(card.dataset.openProduct)}};
  });
}

function hydrateExperience(chapter,data){
  if(chapter.experience==="memory")renderMemoryThreads(data.threads||[]);
  if(chapter.experience==="skills"){window.erpaSkillCatalog=data.catalog||[];renderSkillCatalog(window.erpaSkillCatalog,data.skills||[])}
  if(chapter.experience==="storefront"){
    window.erpaCatalog=data;renderProducts(data);const count=$("#bag-count");if(count)count.textContent=data.cart_count||0;
    const categories=[...new Set(data.products.map(item=>item.category))];
    $("#store-filters").innerHTML=`<button class="store-filter active" data-category="all">All</button>${categories.map(category=>`<button class="store-filter" data-category="${esc(category)}">${esc(category)}</button>`).join("")}`;
    bindStoreFilters();
  }
}

function bindStoreFilters(){
  document.querySelectorAll(".store-filter").forEach(button=>button.onclick=()=>{document.querySelectorAll(".store-filter").forEach(item=>item.classList.toggle("active",item===button));renderProducts(window.erpaCatalog,button.dataset.category)});
}

let memoryThreadId="erpa-appbook-thread";
function renderMemoryThreads(threads=[]){
  const list=$("#memory-thread-list");if(!list)return;
  list.innerHTML=threads.length?threads.map(thread=>`<button class="thread-item ${thread.thread_id===memoryThreadId?"active":""}" data-memory-thread="${esc(thread.thread_id)}"><strong>${esc(thread.title)}</strong><span>${thread.turn_count} turns · ${new Date(thread.updated_at).toLocaleString()}</span></button>`).join(""):'<p class="muted">No saved threads yet. Start a new conversation.</p>';
  document.querySelectorAll("[data-memory-thread]").forEach(button=>button.onclick=()=>loadMemoryThread(button.dataset.memoryThread));
}

async function loadMemoryThread(threadId){
  const data=await postAction("memory_thread",{thread_id:threadId});memoryThreadId=threadId;
  $("#memory-thread-current").textContent=threadId;$("#memory-chat").innerHTML="";
  if(!data.messages.length)appendChat("#memory-chat","assistant","This is a new thread. Ask ERPA a question to begin its conversation memory.");
  data.messages.forEach(message=>appendChat("#memory-chat",message.role,message.content));
  renderInferenceContext(data.context_window);
  const threads=await postAction("memory_threads");renderMemoryThreads(threads.threads);
}

function bindExperience(chapter){
  if(chapter.experience==="memory"){
    $("#memory-new-thread").onclick=async()=>{const data=await postAction("memory_new_thread");memoryThreadId=data.thread_id;$("#memory-thread-current").textContent=memoryThreadId;$("#memory-chat").innerHTML="";appendChat("#memory-chat","assistant","New thread started. This conversation now has an independent thread ID and active history.");const saved=(await postAction("memory_threads")).threads;renderMemoryThreads([{thread_id:memoryThreadId,title:"New conversation",turn_count:0,updated_at:new Date().toISOString(),messages:[]},...saved]);$("#memory-chat-input").focus()};
    $("#memory-chat-form").onsubmit=async event=>{event.preventDefault();const input=$("#memory-chat-input"),query=input.value.trim();if(!query)return;appendChat("#memory-chat","user",query);input.value="";input.disabled=true;const data=await postAction("memory_chat",{query,thread_id:memoryThreadId});appendChat("#memory-chat","assistant",data.answer);renderInferenceContext(data.context_window);renderMemoryThreads((await postAction("memory_threads")).threads);input.disabled=false;input.focus();pollDataExplorer()};
  }
  if(chapter.experience==="tools")$("#tools-chat-form").onsubmit=async event=>{event.preventDefault();const input=$("#tools-chat-input"),query=input.value.trim();if(!query)return;appendChat("#tools-chat","user",query);input.disabled=true;$("#sandbox-state").textContent="Executing";const data=await postAction("tools_chat",{query});const bubble=appendChat("#tools-chat","assistant",data.answer);if(data.chart){const figure=document.createElement("figure");figure.className="store-chart";figure.innerHTML=`<img src="${data.chart.data_url}" alt="${esc(data.chart.alt)}"/><figcaption>${esc(data.chart.title)} · E2B</figcaption>`;bubble.querySelector(":scope > div").append(figure)}$("#tool-stages").innerHTML=data.stages.map(stage=>`<article class="execution-stage ${stage.status}"><i></i><div><strong>${esc(stage.name)}</strong><span>${esc(stage.status)}</span></div><pre>${esc(JSON.stringify(stage.detail,null,2))}</pre></article>`).join("");const sandbox=data.sandbox;$("#sandbox-state").textContent=sandbox.executed?"E2B complete":"E2B not executed";$("#sandbox-console pre").textContent=`$ python <<'ERPA_CODE'\n${sandbox.code}\nERPA_CODE\n\n${(sandbox.stdout||sandbox.expected_stdout||[]).join("\n")}\n${sandbox.error||sandbox.reason||"exit 0"}`;input.disabled=false;input.focus();pollDataExplorer()};
  if(chapter.experience==="skills")$("#skill-query-button").onclick=async()=>{const query=$("#skill-query").value;const data=await postAction("skills",{query});renderSkillCatalog(window.erpaSkillCatalog||[],data.skills||[]);pollDataExplorer()};
  if(chapter.experience==="context"){
    const contextAction=async action=>{const data=await postAction(action,{thread_id:"context-lab-thread"});renderContextComparison(data);if(data.answer){appendChat("#context-baseline-chat","assistant",data.answer,"Harness");appendChat("#context-engineered-chat","assistant",data.answer,"Harness")}pollDataExplorer()};
    $("#context-form").onsubmit=async event=>{
      event.preventDefault();const input=$("#context-input"),button=$("#context-submit"),query=input.value.trim();if(!query)return;
      appendChat("#context-baseline-chat","user",query);appendChat("#context-engineered-chat","user",query);
      input.disabled=true;button.disabled=true;button.classList.add("loading");button.textContent="Agents working";
      const stopLoading=beginContextLoading();
      try{
        const data=await postAction("context_turn",{query,thread_id:"context-lab-thread"});
        stopLoading();appendContextResponse("#context-baseline-chat",data,"Full-context agent");appendContextResponse("#context-engineered-chat",data,"Engineered-context agent");
        renderContextComparison(data);$("#baseline-agent-state").textContent="Tool complete";$("#engineered-agent-state").textContent="Tool complete";pollDataExplorer();
      }catch(error){
        stopLoading();appendChat("#context-baseline-chat","assistant",`The context turn failed: ${error.message}`);appendChat("#context-engineered-chat","assistant",`The context turn failed: ${error.message}`);$("#baseline-agent-state").textContent="Failed";$("#engineered-agent-state").textContent="Failed";
      }finally{
        input.disabled=false;button.disabled=false;button.classList.remove("loading");button.textContent="Send to both";input.focus();
      }
    };
    $("#context-summarize").onclick=()=>contextAction("context_summarize");$("#context-offload").onclick=()=>contextAction("context_offload");
  }
  if(chapter.experience==="cache")$("#cache-form").onsubmit=async event=>{event.preventDefault();const input=$("#cache-input"),query=input.value.trim();if(!query)return;appendChat("#baseline-chat","user",query);appendChat("#cached-chat","user",query);input.disabled=true;const data=await postAction("cache_query",{query});appendChat("#baseline-chat","assistant",data.baseline.answer,data.baseline.route);appendChat("#cached-chat","assistant",data.cached.answer,data.cached.cache_hit?"Oracle cache hit":"Cold model path");renderCacheRace(data);input.disabled=false;input.focus();pollDataExplorer()};
  if(chapter.experience==="orchestration"){
    document.querySelectorAll("[data-agent]").forEach(node=>node.onclick=()=>{$("#agent-context").textContent=JSON.stringify(orchestrationContexts[node.dataset.agent]||{state:"No context yet"},null,2)});
    document.querySelectorAll("[data-workflow-query]").forEach(button=>button.onclick=()=>{$("#orchestration-query").value=button.dataset.workflowQuery});
    $("#orchestration-run").onclick=()=>{document.querySelectorAll(".agent-node,.shared-node").forEach(node=>node.classList.remove("running","complete"));$("#orchestration-events").innerHTML="";$("#orchestration-state").textContent="Running";orchestrationContexts={};const source=new EventSource(`${API}/orchestration/stream?question=${encodeURIComponent($("#orchestration-query").value)}`);source.addEventListener("event",event=>{const data=JSON.parse(event.data);appendOrchestrationEvent(data);if(data.context){orchestrationContexts[data.agent_name]=data.context;if(data.stage==="shared")orchestrationContexts.shared=data.context;$("#agent-context").textContent=JSON.stringify(data.context,null,2)}});source.addEventListener("result",event=>{const data=JSON.parse(event.data);appendOrchestrationEvent(data);orchestrationContexts={...data.agent_contexts,shared:data.shared_memory_context,complete:{answer:data.answer}};$("#orchestration-state").textContent="Consolidated";$("#agent-context").textContent=JSON.stringify(data.shared_memory_context,null,2);source.close();pollDataExplorer()});source.onerror=()=>{source.close();if($("#orchestration-state").textContent!=="Consolidated")$("#orchestration-state").textContent="Stream ended"}};
  }
  if(chapter.experience==="storefront"){
    bindStoreFilters();
    $("#erpa-fab").onclick=()=>{$("#store-chat").hidden=false;$("#store-chat-input").focus()};$("#store-chat-close").onclick=()=>{$("#store-chat").hidden=true};
    $("#store-chat-expand").onclick=()=>{const chat=$("#store-chat"),expanded=chat.classList.toggle("fullscreen");$("#store-chat-expand").textContent=expanded?"↙":"⛶";$("#store-chat-expand").setAttribute("aria-label",expanded?"Exit full screen":"Open ERPA full screen")};
    document.querySelectorAll("[data-store-prompt]").forEach(button=>button.onclick=()=>{$("#store-chat-input").value=button.dataset.storePrompt;$("#store-chat-form").requestSubmit()});
    $("#store-chat-form").onsubmit=async event=>{event.preventDefault();const input=$("#store-chat-input"),query=input.value.trim();if(!query)return;appendChat("#store-chat-messages","user",query);input.value="";input.disabled=true;const pending=appendChat("#store-chat-messages","assistant","Discovering tools and assembling grounded context…");pending?.classList.add("pending");const data=await postAction("store_chat",{query,thread_id:"erpa-storefront-thread"});pending?.remove();appendStoreResponse(data);window.erpaCatalog=data.catalog;input.disabled=false;input.focus();pollDataExplorer()};
  }
}

function trace(t){
  if(!t)return"";
  return `<div class="trace"><div class="trace-summary"><span class="pill">${esc(t.shape||"trace")}</span><span class="pill">${t.tokens||0} tokens</span><span class="pill">${Number(t.latency_ms||0).toFixed(1)} ms</span></div>${(t.spans||[]).map(s=>`<div class="trace-step"><i class="dot ${esc(s.kind)}"></i><span class="trace-node">${esc(s.name)}</span><span class="trace-time">${Number(s.duration_ms||0).toFixed(2)} ms</span></div>`).join("")}</div>`;
}

function findProposal(value){
  if(!value||typeof value!=="object")return null;
  if(value.proposal_id&&["approval_required","pending"].includes(value.status))return value.proposal_id;
  for(const child of Object.values(value)){const found=findProposal(child);if(found)return found}
  return null;
}

function summaryCards(value){
  if(!value||typeof value!=="object")return `<p>${esc(value)}</p>`;
  const entries=Object.entries(value).filter(([,v])=>v===null||["string","number","boolean"].includes(typeof v)).slice(0,12);
  const cards=entries.length?`<div class="metric-grid">${entries.map(([key,val])=>`<div class="metric"><span>${esc(key.replaceAll("_"," "))}</span><strong>${esc(val)}</strong></div>`).join("")}</div>`:"";
  const arrays=Object.entries(value).filter(([,v])=>Array.isArray(v)&&v.length&&typeof v[0]==="object").slice(0,2);
  const dataTables=arrays.map(([key,rows])=>{
    const columns=[...new Set(rows.slice(0,8).flatMap(Object.keys))].filter(column=>rows.every(row=>row[column]===null||["string","number","boolean","undefined"].includes(typeof row[column]))).slice(0,6);
    if(!columns.length)return"";
    return `<h3 class="data-title">${esc(key.replaceAll("_"," "))}</h3>${table({columns,rows:rows.slice(0,12).map(row=>columns.map(c=>row[c]??"—"))})}`;
  }).join("");
  return cards+dataTables;
}

function output(){
  const el=$("#output");
  if(!el)return;
  if(!result){el.className="panel-body output empty";el.textContent="Run the interaction or inspect this part's live status.";return}
  el.className="panel-body output";
  const proposal=findProposal(result);
  if(view==="json")el.innerHTML=`<pre class="json">${esc(JSON.stringify(result,null,2))}</pre>`;
  else if(view==="trace")el.innerHTML=result.trace?trace(result.trace):`<div class="result-copy">${summaryCards(result)}</div>`;
  else el.innerHTML=`<div class="result-copy">${result.answer?markdown(result.answer):summaryCards(result)}</div>${result.trace?trace(result.trace):""}${proposal?`<div class="approval-bar"><div><strong>Human approval required</strong><span>Review the exact proposal in JSON, then resume by proposal ID.</span></div><button class="primary" data-approve="${esc(proposal)}">Approve exact action</button></div>`:""}`;
  const approve=$("[data-approve]");
  if(approve)approve.onclick=()=>approveProposal(approve.dataset.approve);
}

async function api(path,options={}){
  const response=await fetch(path,{headers:{"Content-Type":"application/json"},...options});
  const data=await response.json();
  if(!response.ok)throw Error(data.detail||`HTTP ${response.status}`);
  return data;
}

async function status(chapter){
  try{
    result=await api(`${API}/chapters/${chapter.id}`);output();hydrateExperience(chapter,result);
    $("#global-status").classList.add("ready");
    $("#global-status span").textContent=`${result.profile||"Harness"} ready`;
  }catch(error){
    if($("#output")){ $("#output").className="panel-body output";$("#output").innerHTML=`<div class="error">${esc(error.message)}. Start with <code>./run.sh</code>.</div>`; }
    else document.querySelector(".experience")?.insertAdjacentHTML("afterbegin",`<div class="error">${esc(error.message)}</div>`);
  }
}

function inputValue(action){
  if(!action.input)return{};
  const element=$("#chapter-input");
  return {[action.input.field]:element.value};
}

async function run(chapter){
  if(chapter.action.danger&&!window.confirm("Remove only the appbook-owned workshop records?"))return;
  const button=$("[data-run]"),old=button.textContent;
  button.disabled=true;button.innerHTML='<span class="loading">Running</span>';
  try{
    result=await api(`${API}/actions/${chapter.action.name}`,{method:"POST",body:JSON.stringify({payload:inputValue(chapter.action)})});
    view="answer";syncTabs();output();
  }catch(error){$("#output").innerHTML=`<div class="error">${esc(error.message)}</div>`}
  finally{button.disabled=false;button.textContent=old}
}

async function approveProposal(proposalId){
  const button=$("[data-approve]");if(button){button.disabled=true;button.textContent="Approving…"}
  try{result=await api(`${API}/actions/approve`,{method:"POST",body:JSON.stringify({payload:{proposal_id:proposalId}})});view="answer";syncTabs();output()}
  catch(error){$("#output").innerHTML=`<div class="error">${esc(error.message)}</div>`}
}

function syncTabs(){document.querySelectorAll("[data-view]").forEach(button=>button.classList.toggle("active",button.dataset.view===view))}

function controls(chapter){
  if(!chapter.action)return '<p class="action-copy">This part is explanatory. Refresh its runtime contract whenever you want to inspect the current profile.</p><div class="actions"><button class="secondary" data-refresh>Refresh status</button></div>';
  let input="";
  if(chapter.action.input){
    const spec=chapter.action.input;
    input=`<label for="chapter-input">${esc(spec.label)}</label>`;
    input+=spec.kind==="select"?`<select id="chapter-input">${spec.options.map(([value,label])=>`<option value="${esc(value)}">${esc(label)}</option>`).join("")}</select>`:`<textarea id="chapter-input">${esc(spec.value||"")}</textarea>`;
  }
  return `<p class="action-copy">Run this part against the appbook’s scoped harness state. Live external work remains opt-in.</p>${input}<div class="actions"><button class="${chapter.action.danger?"danger-button":"primary"}" data-run>${esc(chapter.action.label)}</button><button class="secondary" data-refresh>Reset to status</button></div>`;
}

function render(id){
  const chapter=CHAPTERS.find(item=>item.id===id)||CHAPTERS[0];
  document.querySelectorAll(".nav").forEach(node=>node.classList.toggle("active",node.dataset.id===chapter.id));
  $("#stage").innerHTML=`<div class="stage-inner">
    <header class="stage-head"><div><div class="eyebrow">MemoRizz appbook · Section ${chapter.n}</div><h1>${esc(chapter.title)}</h1><p class="blurb">${esc(chapter.blurb)}</p><div class="chapter-meta"><span class="pill">${esc(chapter.tag)}</span><span class="pill">Interactive appbook</span></div></div><button class="theme" id="theme" aria-label="Toggle theme">◐</button></header>
    <aside class="decision"><span>🔩</span><div><strong>Harness connection / decision</strong><p>${esc(chapter.decision)}</p></div></aside>
    <div class="lesson-grid">${(chapter.sections||[]).map(section).join("")}</div>
    ${(chapter.flows||[]).map(flow).join("")}
    ${chapter.architecture?referenceArchitecture():""}
    ${chapter.table?`<section class="lesson-table"><h2>Component view</h2>${table(chapter.table)}</section>`:""}
    ${chapter.experience?experienceMarkup(chapter):chapter.id==="overview"?"":`<section class="demo"><div class="panel"><div class="panel-head"><h2 class="panel-title">Section control</h2><span class="eyebrow">Interactive</span></div><div class="panel-body">${controls(chapter)}</div></div>
    <div class="panel"><div class="panel-head"><h2 class="panel-title">Runtime evidence</h2><div class="segmented"><button class="active" data-view="answer">Answer</button><button data-view="trace">Trace</button><button data-view="json">JSON</button></div></div><div id="output" class="panel-body output empty"></div></div></section>
    `}
  </div>`;
  result=null;view="answer";output();
  $("#theme").onclick=()=>{const next=document.documentElement.dataset.theme==="light"?"dark":"light";document.documentElement.dataset.theme=next;localStorage.setItem("erpa-theme",next)};
  document.querySelectorAll("[data-view]").forEach(button=>button.onclick=()=>{view=button.dataset.view;syncTabs();output()});
  const runButton=$("[data-run]");if(runButton)runButton.onclick=()=>run(chapter);
  const refresh=$("[data-refresh]");if(refresh)refresh.onclick=()=>status(chapter);
  if(chapter.experience)bindExperience(chapter);
  if(chapter.architecture)bindReferenceArchitecture();
  status(chapter);closeMenu();$("#stage").focus();
}

function openMenu(){$("#sidebar").classList.add("open");$("#scrim").hidden=false}
function closeMenu(){$("#sidebar").classList.remove("open");$("#scrim").hidden=true}
let explorerSnapshot=null,explorerTable="course_inventory",explorerPolling=false;
function shortCell(value){
  if(value===null||value===undefined)return"—";
  const rendered=typeof value==="string"?value:JSON.stringify(value);
  return rendered.length>92?`${rendered.slice(0,89)}…`:rendered;
}
function renderDataExplorer(){
  if(!explorerSnapshot)return;
  const active=explorerSnapshot.transactions.filter(item=>item.active);
  const activeTables=new Set(active.map(item=>item.table_name));
  const names=Object.keys(explorerSnapshot.tables);
  if(!names.includes(explorerTable))explorerTable=names[0];
  $("#explorer-tabs").innerHTML=names.map(name=>`<button class="explorer-tab ${name===explorerTable?"active":""} ${activeTables.has(name)?"transacting":""}" data-table="${esc(name)}"><span>${esc(name.replace("course_",""))}</span><b>${explorerSnapshot.tables[name].count}</b></button>`).join("");
  document.querySelectorAll(".explorer-tab").forEach(button=>button.onclick=()=>{explorerTable=button.dataset.table;renderDataExplorer()});
  const data=explorerSnapshot.tables[explorerTable],rows=data.rows||[];
  const columns=[...new Set(rows.flatMap(row=>Object.keys(row)))].filter(key=>key!=="__row_key");
  const activeRows=new Set(active.filter(item=>item.table_name===explorerTable&&item.row_key).map(item=>item.row_key));
  $("#explorer-table-name").textContent=explorerTable;$("#explorer-row-count").textContent=`${data.count} rows`;
  $("#explorer-table").innerHTML=rows.length?`<table><thead><tr>${columns.map(column=>`<th>${esc(column)}</th>`).join("")}</tr></thead><tbody>${rows.map(row=>`<tr class="${activeRows.has(row.__row_key)?"row-transacting":""}">${columns.map(column=>`<td title="${esc(typeof row[column]==="string"?row[column]:JSON.stringify(row[column]))}">${esc(shortCell(row[column]))}</td>`).join("")}</tr>`).join("")}</tbody></table>`:'<p class="muted explorer-empty">No rows in this table.</p>';
  $("#transaction-log").innerHTML=explorerSnapshot.transactions.length?explorerSnapshot.transactions.slice(0,24).map(tx=>`<article class="transaction ${tx.active?"active":""} ${tx.operation.toLowerCase()}"><i></i><div><header><strong>${esc(tx.operation)} · ${esc(tx.table_name)}</strong><time>${new Date(tx.committed_at).toLocaleTimeString()}</time></header><p>${esc(tx.detail||tx.row_key||"Database operation")}</p></div></article>`).join(""):'<p class="muted explorer-empty">No transactions recorded yet.</p>';
  const indicator=$("#transaction-indicator");indicator.classList.toggle("active",active.length>0);indicator.querySelector("b").textContent=active.length?`${active[0].operation} · ${active[0].table_name}`:"Idle";
  $("#explorer-subtitle").textContent=`${explorerSnapshot.target} · ${names.length} tables · ${active.length?"transaction in progress":"committed state"}`;
}
async function pollDataExplorer(){
  if(explorerPolling)return;explorerPolling=true;
  try{explorerSnapshot=await api(`${API}/data`);renderDataExplorer()}catch(error){$("#explorer-subtitle").textContent=`Explorer unavailable · ${error.message}`}finally{explorerPolling=false}
}
function initDataExplorer(){
  $("#explorer-toggle").onclick=()=>{const explorer=$("#data-explorer"),open=explorer.classList.toggle("open");$("#explorer-toggle").setAttribute("aria-expanded",String(open));if(open)pollDataExplorer()};
  const explorer=$("#data-explorer"),resizer=$("#explorer-resizer"),refresh=$("#explorer-refresh");
  const minHeight=220,maxHeight=()=>Math.max(minHeight,window.innerHeight-110);
  const setHeight=value=>{const height=Math.min(maxHeight(),Math.max(minHeight,Math.round(value)));explorer.style.setProperty("--explorer-height",`${height}px`);resizer.setAttribute("aria-valuenow",String(height));resizer.setAttribute("aria-valuemax",String(maxHeight()));localStorage.setItem("erpa-explorer-height",String(height))};
  const savedHeight=Number(localStorage.getItem("erpa-explorer-height"));if(Number.isFinite(savedHeight)&&savedHeight>0)setHeight(savedHeight);
  resizer.onpointerdown=event=>{if(!explorer.classList.contains("open"))return;event.preventDefault();resizer.setPointerCapture(event.pointerId);const startY=event.clientY,startHeight=$("#explorer-body").getBoundingClientRect().height;explorer.classList.add("resizing");resizer.onpointermove=move=>setHeight(startHeight+startY-move.clientY);resizer.onpointerup=()=>{explorer.classList.remove("resizing");resizer.onpointermove=null;resizer.onpointerup=null}};
  resizer.onkeydown=event=>{if(!["ArrowUp","ArrowDown"].includes(event.key))return;event.preventDefault();const current=$("#explorer-body").getBoundingClientRect().height||savedHeight||610;setHeight(current+(event.key==="ArrowUp"?32:-32))};
  refresh.onclick=async()=>{refresh.classList.add("refreshing");refresh.disabled=true;await pollDataExplorer();refresh.disabled=false;refresh.classList.remove("refreshing")};
  window.addEventListener("resize",()=>{const current=$("#explorer-body").getBoundingClientRect().height;if(current)setHeight(current)});
  pollDataExplorer();window.setInterval(pollDataExplorer,1200);
}
window.addEventListener("hashchange",()=>render(location.hash.slice(1)));
$("#menu").onclick=openMenu;$("#scrim").onclick=closeMenu;
sidebar();render(location.hash.slice(1));initDataExplorer();
