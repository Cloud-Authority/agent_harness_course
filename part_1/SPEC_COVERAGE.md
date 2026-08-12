# ERPA specification coverage audit

Legend: **verified** is exercised locally by the smoke suite; **implemented / preflight**
requires the instructor's external account or cloud substrate and has an explicit check
in the runbook. No document claims that unavailable credentials were tested.

## Deliverables and fixtures

| Requirement | Status | Evidence |
|---|---|---|
| Two builds × notebook + appbook | verified | both directories; 7 + 9 interactive chapters |
| Shared fixtures never forked | verified | both import `_shared`; one generator and demo script |
| Narration between every notebook cell | verified | notebook builder asserts no adjacent code cells |
| Notebook output populated | verified | every code cell has saved stdout |
| FastAPI, same-origin dependency-free SPA, SSE | verified | both `main.py`, `frontend/`, stream endpoints |
| Background warm and idempotent initialise | verified | additive `initialize()` plus startup thread |
| ~60 products / 800–1,200 variants | verified | 60 / 1,029 |
| 5,000 customers / 40,000 orders / 90,000 lines | verified | generator validation |
| 18-month seasonality and six planted conditions | verified | deterministic weighting + assertions |
| Synthetic, pseudonymous customers | verified | generated IDs only; no names/contact/payment fields |
| 10–14 Notion pages with 3–4 reviews | verified | 12 complete pages, four review documents |
| Seeded semantic/episodic/procedural memory | verified | one JSON fixture; includes last three briefs |
| One canonical five-turn script | verified | `_shared/demo_script.md` |

## Build A — MemoRizz

| Requirement | Status | Evidence |
|---|---|---|
| Current MemoRizz builder + Mongo provider | implemented / preflight | `core/live_memorizz.py`; upstream API verified 2026-08-11 |
| MongoDB collections + vector indexes | implemented / preflight | `verify_atlas()` fails on pending index |
| OpenAI chat + embeddings | implemented / preflight | shared `.env`; live builder config |
| Direct tools; no MCP | verified | `DirectToolbox`; direct Notion/Tavily/Calendar adapters |
| Read-only enterprise Oracle/local mirror | verified | shared read-only facade; optional Mongo mirror loader |
| Persona + provider + toolbox in MemAgent | verified | MemAgent chapter / live builder |
| Recall → decide → write every turn | verified | common trace response and UI tabs |
| Berlin suppressed in turn 1 | verified | test asserts PO and three alerts |
| Turn 4 preference survives real restart | verified | two-process script |
| Under three minutes, no intervention | verified locally | smoke/demo completes in seconds |
| Seven interactive appbook chapters | verified | endpoint and UI checks |

Build A chart choice is resolved as **no sandbox**: it returns grounded regional/size
rows, while Build B visualisation is the differentiator requested by the open-item note.

## Build B — custom stack

| Requirement | Status | Evidence |
|---|---|---|
| Four graph nodes | verified | local `ERPAStateGraph`; production `compile_live_graph()` uses the actual LangGraph `StateGraph` API |
| OAMP memory with discrete LangSmith reads/writes | verified locally / preflight live | OAMP 26.6 is active in live `memory_provider`; `@traceable` and named spans wrap reads/writes |
| Current OAMP reference features | implemented / preflight | background extraction, custom instructions, context cards, metadata boundaries, exact scope, typed/chunked memory, TTL/update/delete, vector or in-DB hybrid search |
| Oracle single substrate and thin mode | implemented / preflight | Oracle 26ai Compose service, schema/fixture bootstrap; live business SQL, files, briefs, OAMP, cache and checkpoints share its pool |
| LangChain OracleVS / cache / history and Oracle checkpointer | implemented / preflight | live boundary calls `OracleSemanticCache.lookup/update`; actual `StateGraph` compiles with setup `OracleSaver` |
| Proper semantic layer | verified | schema catalog, relationships, glossary, canonical margin, guardrails, provenance |
| Keyword/vector/hybrid/rerank | verified | Retrieval chapter shows four rankings |
| Progressive skill disclosure | verified | metadata/match/token comparison |
| Meaning-retrieved tools | verified | registry returns subset; no schema dump |
| Notion + Calendar over MCP | verified adapter / preflight server | Streamable-HTTP client and per-page/scope checks |
| Tavily external signal | verified fallback / preflight live | labelled fixture or live API |
| Sandbox chart + DB file pointer | verified | constrained SVG renderer and `custom_file_storage` |
| Large-result offload | verified | `dbfs://` pointer and asset endpoint |
| Cache before `assemble_context` | verified | boundary lookup is first span |
| Warm cache has no model span | verified | measurement assertion |
| Scheduler invokes same graph | verified local / preflight DBMS job | `BriefScheduler`; queue SQL; in-app persistence |
| Six independently runnable stages | verified | `stages/stage_01…06` |
| Nine interactive appbook chapters | verified | endpoint and UI checks |
| Docker portability | implemented / Compose validated | Oracle AI Database Free `latest-lite` + app image, health gate, volume and idempotent bootstrap |
| Next.js on Vercel | implemented / preflight deploy | `deploy/frontend`, one env swap |
| Local → production config swap | implemented | one settings object and `.env` |

The local substrate is deliberately SQLite so attendees need no database. It mirrors
the single-database anatomy and executes every behavioral acceptance. In live mode the
Oracle classes are part of the executed request path, while the Docker image installs
them ahead of runtime, respecting “nothing installs or authenticates live.”

## Cross-cutting and resolved open items

| Item | Resolution |
|---|---|
| Identical fixtures / traces | shared data and `TurnTrace` contract |
| Model configuration | Build A uses `OPENAI_MODEL`; Build B uses `ANTHROPIC_MODEL` |
| Sandbox choice | fixed-operation in-process SVG renderer: no shell/network/user code |
| Chart path | sandbox → SVG → DB file pointer → inline appbook/notebook |
| Appbook scope | all 16 chapters shipped interactive |
| Morning brief delivery | in-app only |
| “Kata” naming | explicitly fictional in materials; perform final legal/brand check before publication |
| Failure fallback | populated notebooks + local adapters + instructor runbook |
| Dedicated accounts / OAuth morning check | external preflight, not automatable from the repository |
| OCI/Vercel deployment-time target | lightweight artifacts shipped; time must be rehearsed in the instructor account |

## Automated command

```bash
python part_1/tests/smoke_test.py
```

The suite validates volumes, planted conditions, both five-turn outcomes, restart-safe
memory, chapter routes, semantic guardrails, sandbox output, scheduled execution and
the cache's missing model span.
