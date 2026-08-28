# Instructor runbook — Advanced Harness Engineering

## Teaching outcome

Participants should leave able to distinguish model capability from harness
reliability. They will prove that long-running state, side-effect safety, evidence
quality, approvals, verification, and learning are host responsibilities that survive
outside one model turn.

Use the five notebooks in order:

1. recover one sequential workflow;
2. govern parallel research and cross-session learning;
3. place a stable MetaHarness operating layer around different live model loops;
4. evaluate harness strategies without confounding models, wrappers, providers, or task samples.
5. connect semantic memory and registries to a living ontology, GraphRAG, visible context, and governed workflow promotion.

## Preflight

Run this before the session, without displaying `.env`:

```bash
cd /path/to/agent_harness_course
.venv/bin/python -m pip install --upgrade -r part_1/advanced/requirements.txt
.venv/bin/python -m pytest -q part_1/advanced/tests
docker ps --format 'table {{.Names}}\t{{.Status}}\t{{.Ports}}'
```

Confirm:

- `memorizz` is 0.6.3 and resolves from this repository's `.venv/.../site-packages`;
- `oracleagentmemory` is 26.6.0 and the OAM managed store opens successfully;
- the local Oracle AI Database is healthy and its DSN/user/password work;
- the course user can create tables and vector indexes;
- Tavily, OpenAI, and Anthropic have enough quota for four searches, agent tool loops,
  embeddings, planning, drafting, and synthesis;
- the MetaHarness app can access `gpt-5.5`, plus `claude-opus-5` when its key is configured;
- the optional E2B exercise has quota and can create an egress-disabled sandbox;
- ports 8010–8013 are free.

If the local `AGENT` account is missing, locked, or returns `ORA-01017`, first make
`ORA_DSN` match the host port shown by Docker and run the secret-safe local provisioner.
It reads the password already stored in the ignored `.env`; it does not print it or put
it in process arguments:

```bash
.venv/bin/python part_1/advanced/scripts/provision_oracle_course_user.py
```

If the database owner approves the persistent schema-local scheduler privilege, use
`--enable-scheduler` to grant `CREATE JOB`. Do not grant `CREATE ANY JOB`. Without the
optional flag, the ontology app accurately demonstrates the same refresh procedure
through its labelled direct fallback.

Then isolate database readiness from embedding-provider readiness with the labelled
deterministic encoder and run the vector/checkpoint preflight:

```bash
ADVANCED_SEMANTIC_BACKEND=hash .venv/bin/python part_1/advanced/scripts/oracle_preflight.py
```

The Toolbox, Skillbox, and recipe catalogs request Oracle HNSW indexes. A small local
container may report `ORA-51962` when its vector-memory pool is full; the harness labels
that state and continues with exact Oracle cosine search. Do not describe that fallback
as HNSW, but it is still semantic vector retrieval.

Do not paste API keys into notebook source, terminal history, a screen share, or chat.
Notebooks with interactive credential entry use hidden `getpass` prompts. The
MetaHarness notebook and appbook read their live settings from the ignored course
`.env`; the server never sends credentials to the browser.

## Live/fallback boundary

The main teaching path is:

```dotenv
ADVANCED_BACKEND=oracle
ADVANCED_SEMANTIC_BACKEND=openai
ADVANCED_AGENT_MEMORY_SEARCH_STRATEGY=vector
ADVANCED_NOTEBOOK_LIVE=1
ADVANCED_USE_MODEL_SYNTHESIS=true
ADVANCED_RESEARCH_MEMORY_BACKEND=oracle
ADVANCED_OPENAI_MODEL=gpt-5.5
ADVANCED_ANTHROPIC_MODEL=claude-opus-5
ADVANCED_DEEPSEEK_MODEL=deepseek-v4-flash
E2B_API_KEY=<runtime secret>
ADVANCED_SANDBOX_LIVE=1
```

The acceptance/outage profile is:

```dotenv
ADVANCED_BACKEND=memory
ADVANCED_SEMANTIC_BACKEND=hash
ADVANCED_NOTEBOOK_LIVE=0
ADVANCED_SANDBOX_LIVE=0
ADVANCED_EVALUATION_LIVE=0
```

Always label the second profile. It proves local application mechanics but not
durability, Oracle vector search, live web retrieval, or frontier-model behavior. It
does not apply to the MetaHarness lesson, which has no offline execution branch.

## Module 1 — durable compliance workflow

Open the workflow notebook and appbook on port 8010.

### Demonstration sequence

1. Start with the component/provider table. Separate the LLM, embeddings, graph,
   checkpoints, Agent Memory, operation ledger, Toolbox, Skillbox, sandbox, verifier,
   and promotion policy.
2. Open the five source `SKILL.md` files. Confirm their exact bytes and SHA versions
   were saved in Oracle. Contrast them with OAM's small Skillbox-routing guideline;
   the SOP is no longer duplicated as prose memory.
3. Query the Skillbox by meaning. Show Level 1's small name/description manifest, then
   Level 2's full selected Skill body.
4. Query the Toolbox by meaning. Explain why Oracle stores JSON contracts and
   embeddings while Python retains callables and portable sandbox programs.
5. Inspect the LLM plan: selected Skills and tools must come from retrieved candidates,
   and a tool must also be authorized by a loaded Skill.
6. Compile the graph in the visible cell and call LangGraph's native
   `draw_mermaid()`. Match its 18 nodes to the viewer.
7. Start the first run. Follow case loading, freshness checks, sanctions screening,
   risk scoring, and remediation. For each tool, inspect the sandbox input,
   execution, and output envelope; verify empty environment, timeout, host match, and
   teardown.
8. The draft operation commits, then the injected fault raises before LangGraph
   checkpoints the node return. In the viewer, compare `next=draft_report` with the
   already committed ledger result.
9. Resume the same `thread_id`. Highlight `draft_report, reused=true`, then inspect the
   exact approval interrupt and argument hash.
10. Approve. Show one publication, independent verification, the checkpoint/OAM trace,
    and the captured recipe. It is only a promotion candidate after one success.
11. Run the same workflow family again. Show the recurrence/reliability checks, the
    generated `proven-supplier-compliance-review` Skill, its SHA and lineage, and why
    the lower-signal raw recipe leaves default recall.
12. Compare the default OpenAI-vector/model/E2B profile with the labelled saved
    hash/keyword/deterministic/local-process profile. Only the live E2B profile proves
    remote isolation.
13. Discuss the rejection branch and why model-authored approval text is irrelevant.

### Strong proof

Run the three-process acceptance check:

```bash
ADVANCED_SEMANTIC_BACKEND=hash .venv/bin/python part_1/advanced/scripts/workflow_restart_proof.py
```

Object reuse is not enough. This script creates new pools, savers, stores, and compiled
graphs in the crash, resume, and approval processes. Preserve its JSON as workshop
evidence if the environment is being certified.

### Questions to ask

- What happens if the process dies before the side effect commits?
- What happens if it dies after commit but before checkpoint?
- Which operation key fields make replay safe, and what business change would require
  a new key?
- Why are checkpoint history and episodic business audit separate?
- Why retrieve only the relevant tool contracts instead of placing every schema in the
  system prompt?
- Why load a full Skill only after the model selects its small manifest entry?
- Why require repeated, host-verified success before promoting a workflow to a Skill?

## Module 2 — MemoRizz-native parallel research

Open the research notebook and appbook on port 8011.

### Demonstration sequence

1. Define deep research and contrast it with one-shot search and a single retrieval-
   augmented answer.
2. Map each harness responsibility to MemoRizz: model loop, application mode, tool
   routing, completion policy, private memory, shared memory, orchestration, tracing,
   sandboxing, evidence curation, and teardown.
3. Ask for OpenAI, Tavily, E2B, and Oracle credentials through hidden prompts. Run a
   real OpenAI embedding probe and Oracle vector-schema preflight before research.
4. Inspect the complete inline implementation and prove that it imports neither a
   shared research module, LangGraph, nor an outer meta runtime.
5. Walk through the evidence ontology: question → assignment → query → evidence →
   claim → report → review. Ask which joins would be impossible with plain text.
6. Inspect the role map: root, market, technical, risk, buyer, and synthesis all use
   GPT-5.5. Show that each is persisted with its own private Oracle memory ID.
7. Explain least privilege: every specialist receives Tavily, but only the risk agent
   receives E2B's `execute_code` tool; sandbox internet access is disabled.
8. Type the explicit live-run phrase. Follow four deterministic `SubTask` assignments
   through MemoRizz's parallel orchestration and Oracle-backed shared blackboard.
9. Inspect each Tavily query, provider, duration, worker, stable evidence ID, canonical
   URL, and snippet. Explain why retrieval score and model confidence are not truth.
10. Inspect private delegate reports, shared hierarchy, synthesized report, semantic
    Oracle recall, and deterministic host checks before closing providers.

### Questions to ask

- Which responsibilities already live inside a MemAgent, and when would a separate
  outer governance layer still be useful?
- Why is application mode a runtime, tool, memory, and completion configuration rather
  than a prompt label?
- Which ontology fields let the host distinguish retrieved evidence from model
  inference?
- Why should code execution be available to one role instead of every role?
- How do private role memory and a shared blackboard solve different problems?
- What held-out evaluation and source-quality rubric would be required for an answer-
  accuracy claim?

## Module 3 — MemoRizz MetaHarness

Open the MetaHarness notebook and appbook on port 8012.

### Live Oracle walkthrough

1. Start with the notebook's detailed distinction between an inner harness and the
   outer MetaHarness. Ask which concerns should remain host-owned when providers change.
2. Prove `memorizz.__file__` is in `site-packages`, then resolve `MetaHarness`,
   `HarnessRouter`, `HarnessContextBuilder`, `AgentHarness`, and `HarnessTask` to their
   installed files and line numbers.
3. Read the selected methods in execution order: preparation, routing, context
   assembly, adapter execution, terminal-state selection, and evidence recording.
4. Connect to Oracle AI Database. Show `MH_RUNS`, `MH_EVENTS`,
   `MH_WORKSPACE_LEASES`, and `MH_APPROVALS`; explain the row locks used for concurrent
   updates and event sequence allocation.
5. Inspect `LiveModelHarness.probe()` and `.run()`. Emphasize that the adapter is small:
   it reports readiness, consumes a prepared context pack, calls one provider, emits
   normalized events, and returns an outcome.
6. Assemble the router and MetaHarness visibly in the notebook. Explain why the fixed,
   read-only provider route is pre-authorized by application policy and which expanded
   capabilities should pause for an Oracle-backed approval.
7. Index the installed MemoRizz class sources into live Oracle memory, then ask the
   learner to enter a question and choose `auto`, `openai-live`, or `anthropic-live`.
8. Inspect the chosen candidate, rejected candidates, source IDs, exact input sections,
   token usage, run row, and ordered events. Do not describe provider success as answer
   quality verification.
9. Open the appbook and repeat the query. Follow the animated execution map, clicking
   the outer boundary, router, Oracle context, both inner harnesses, Oracle evidence,
   and response nodes to inspect each view.
10. Close the pool and confirm durable Oracle state remains available to later runs.

### Questions to ask

- What changes between model adapters, and what remains owned by MemoRizz?
- Why is `auto` deterministic host routing rather than model self-selection?
- Why is a successful provider response insufficient as an answer-quality check?
- Which new authority would make this read-only path require a host decision?
- What should be retained, redacted, or deleted from Oracle in your production setting?

## Module 4 — Total Recall from the database upward

Open the Total Recall notebook and appbook on port 8013.

### Demonstration sequence

1. Start with `Agent = Model + Harness`. Ask learners to classify each later layer as
   model behavior or harness behavior.
2. Connect as the least-privilege Oracle user and prove the in-database ONNX embedder
   returns the expected 384-dimensional vector.
3. Build the SecureFile-LOB scratch filesystem and contrast an unsafe OS-file counter
   with Oracle's atomic update and transaction isolation.
4. Follow the retrieval ladder from keyword to Oracle vector search, hybrid/RRF, and
   optional cross-encoder reranking.
5. Use Oracle AI Agent Memory for semantic facts, episodic threads, context cards, and
   procedural workflow outcomes. Reconnect to prove continuity.
6. Build the searchable semantic catalog from schema metadata and refresh it through
   a stored procedure and scheduler boundary.
7. Build the Toolbox and Skillbox, retrieve small manifests by meaning, load a full
   `SKILL.md` only when selected, and promote a successful workflow.
8. Compile the five-node LangGraph with `OracleSaver`. Trace context assembly, model
   choice, tool dispatch, persistence, budgets, and finalization.
9. Measure context growth, then show how context cards and offloading keep the prompt
   flatter while preserving searchable detail in Oracle.
10. Finish with the fresh-session recall check and the end-to-end diagnostic cells.
11. Use the companion appbook separately when teaching the expanded ontology, graph,
    sandbox-evidence, and data-inspection extension.

### Questions to ask

- Why does short-term scratch storage need different promotion rules from durable facts?
- When does hybrid retrieval outperform keyword or vector search alone?
- Why retrieve a small Tool or Skill manifest before loading the full body?
- Which state belongs in the LangGraph checkpoint, Oracle Agent Memory, or a Skill?
- What measurements show that compaction and offloading help rather than silently lose
  important context?

## Module 5 — fair harness evaluation

Open `advanced_fair_harness_evaluation.ipynb`. It is intentionally separate from the
live MetaHarness appbook.

### Demonstration sequence

1. Show the 12-arm protocol fingerprint before any paid result exists.
2. Explain the four independent fintech task families and why repeats are not new
   samples.
3. Walk through the wrapper, coordination, routing, and provider estimands.
4. Verify the reverse blocks give each arm mean position 6.5, then discuss the time
   effects this does not remove.
5. Run the deterministic mechanics artifact and inspect context/workspace parity,
   normalized accounting, and host verification.
6. Explain why the cold first row can be slower without proving a pair is faster.
7. Optionally set `ADVANCED_EVALUATION_LIVE=1`, enter replacement provider keys with
   `getpass`, prepare two zero-call proposals, and approve the matched smoke pair.
8. End with the claim ladder and `winner_allowed=false`.

### Questions to ask

- Which pair estimates wrapper overhead, and what must be held fixed?
- Why is Oracle-versus-Filesystem meaningful only within the same strategy?
- When should an LLM judge scalar be invalidated?
- What task distribution would justify a bounded deployment recommendation?

## Appbook launch

Launch each in a separate terminal:

```bash
part_1/advanced/workflow/appbook/run.sh
part_1/advanced/deep_research/appbook/run.sh
part_1/advanced/metaharness/appbook/run.sh
part_1/advanced/total_recall/appbook/run.sh
```

The apps warm their runtime in the background. A red status card should show actionable
Oracle/key remediation instead of silently switching to fixtures.

## Failure recovery during class

- Oracle unavailable: defer the live MetaHarness run; it does not switch databases.
  Other modules may use their explicitly labelled acceptance profiles.
- Tavily unavailable: set `ADVANCED_NOTEBOOK_LIVE=0`, use the visibly labelled
  `example.test` fixture provider, and avoid live-web/model/Oracle claims.
- E2B unavailable: use the labelled deterministic test double for control mechanics,
  report `live_isolation_proven=false`, and defer every remote-isolation claim.
- Research embeddings unavailable: use the notebook's labelled hash-embedding/
  FilesystemProvider branch; workflow embeddings can independently use
  `ADVANCED_SEMANTIC_BACKEND=hash`.
- One frontier model unavailable: leave its proposal/run evidence failed; do not replace
  the requested model or infer a comparison from one arm.
- Accidental secret exposure: stop, revoke the credential, issue a replacement, and
  restart the kernel/process before continuing.

## End-of-session cleanup

MetaHarness memory, run rows, events, workspace leases, and approval rows remain in
Oracle after its notebook closes the connection pool. The final cell deliberately does
not delete that evidence. Retain or remove durable state according to the instructor
environment's data policy. Never distribute `.env` or notebook outputs that may
contain proprietary provider responses.
