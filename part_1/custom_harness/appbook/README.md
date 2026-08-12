# ERPA custom-harness appbook

This appbook is the interactive form of the complete custom-harness notebook. It
keeps the notebook's teaching sequence, adds a tenth commerce chapter, and exposes the complete runtime through
FastAPI status, interaction, trace and lifecycle endpoints.

Run the zero-credential teaching mirror:

```bash
./run.sh
```

Then open `http://127.0.0.1:8000`. There is no npm or frontend build. Local mode is
deliberately deterministic and calls itself a teaching mirror in every status view;
it never claims that SQLite is Oracle or that generated Python ran in E2B.

## Complete live architecture

The live path (`ERPA_MODE=live`) implements the notebook's complete substrate:

- Oracle AI Database Free in Docker owns business tables, 384-dimensional vectors,
  the living semantic catalog, OAMP memory, semantic cache, SecureFile scratch
  files, promotion queues, scheduled jobs, chat history and LangGraph checkpoints.
- `ChatAnthropic` uses `claude-opus-4-8` with
  `thinking={"type": "adaptive"}`. Anthropic is the only chat-model provider.
- Oracle's `ALL_MINILM_L12_V2` ONNX model creates embeddings inside the database for
  OAMP, `OracleSemanticCache`, `OracleVS`, skill retrieval, tool discovery and the
  semantic catalog. No external embedding API is used.
- OAMP 26.6 owns thread messages, context cards, background extraction, durable
  facts/preferences/guidelines, TTLs and exact tenant/user/agent filtering.
- SecureFile `ScratchFS` stores `/plans`, `/notes`, `/tool_out` and `/inbox` per
  logical session. An Oracle row trigger stages only opted-in files when a session
  changes from `ACTIVE` to `ENDED`; the Python consumer promotes those chunks into
  OAMP because PL/SQL does not run client Python.
- The `CustomToolbox` retrieves compact tool metadata by meaning, discloses only the
  selected schemas, validates arguments with LangChain tools and invokes only a
  closed allowlist of trusted functions. It offers no arbitrary SQL or shell tool.
- Model-generated Python has exactly one execution route: E2B Code Interpreter.
  Live mode fails closed when E2B is unavailable; large outputs are compacted to a
  ScratchFS pointer.
- LangGraph loops through selective context, Claude and bounded tool calls, then
  persists the turn. `OracleSaver` uses a dedicated database connection and stores
  each super-step under `configurable.thread_id`.
- `OracleSemanticCache` is outside the graph. A hit bypasses OAMP assembly, skill
  and tool retrieval, Claude, E2B and checkpoint writes. Its namespace includes the
  model, adaptive-thinking policy, prompt version, tenant, user and a business-data
  fingerprint.
- LangSmith records the graph, model, retrieval, memory and tool spans. Oracle
  `DBMS_SCHEDULER` queues the weekday brief and refreshes the living semantic layer;
  the queue worker sends scheduled input through the same graph as interactive chat.
- A persistent footer data explorer reflects the active application schema, columns,
  primary keys and paginated rows. An SSE activity channel marks allowlisted reads
  and transactional writes as active, committed or rolled back. It is application
  telemetry for teaching—not a replacement for Oracle Unified Auditing.
- The Kata Store reads products, variants and stock from that same substrate. Its
  checkout atomically records `ERPA_STORE_ORDERS` / `ERPA_STORE_ORDER_LINES` and
  decrements the allocated inventory row. The historical Kata order fixtures remain
  immutable, so restart assertions and live shopper transactions can coexist.

Prompt caching is intentionally not enabled. The future seam is documented: stable
role, safety, tool-contract and skill-authority content belongs in a cacheable prefix;
volatile OAMP context, semantic results, scratch notes, tool output and the current
message belong after it. This is distinct from the implemented semantic answer cache.

## Chapters

1. Reference Architecture — an end-to-end data-flow diagram plus the full
   built/partial/missing component ledger for the final Kata Store.
2. Memory & ScratchFS — a LangGraph conversation beside live OAMP writes,
   SecureFile working notes and explicit session-end promotion.
3. Living Semantic Layer — the same question rendered side by side with literal
   schema matching and with governed views, comments, hints, relationships and
   `V$SQL` workload meaning.
4. Retrieval — the real query “What should Alex do about the Berlin thermal jacket
   shortage?” feeds Okapi BM25, OracleVS cosine retrieval, weighted reciprocal-rank
   fusion and a query-aware authority reranker. Each panel sends only its independently
   ranked top-five passages to Claude Opus 4.8 for a direct, source-cited answer, then
   displays those retrieved sources and the complete context in a 2×2 comparison.
5. Skills — eleven ACTIVE skill manifests, three runnable examples and visible
   manifest retrieval followed by one-body progressive disclosure.
6. Trusted Tools — CustomToolbox authority, validation and E2B boundary.
7. LangGraph Loop — Claude adaptive thinking, bounded calls and OracleSaver.
8. Semantic Cache — side-by-side full-graph and `langchain-oracledb` semantic-hit
   conversations with answer, wall time, tokens and trace shape.
9. Mission Control — complete turns, traces, artifacts and scheduled execution.
10. Kata Store — a 60-style catalog, inventory-backed product detail pages,
    transactional cart and checkout, plus a floating ERPA chat surface for catalog
    and product questions.

The expandable data explorer is available below every chapter. It defaults to the
inventory table and can browse every application-owned business and harness table.
The explorer is read-only; mutations happen only through governed application flows
such as memory lifecycle actions and storefront checkout. When expanded, its top
edge can be dragged to set the working height; the chosen height persists locally.

The component map labels the known gaps rather than implying features: MCP,
multi-agent orchestration and source self-modification are missing; internet access,
human approval, context telemetry, entity memory, summaries, continual learning and
tool-result compaction are intentionally partial.

## Live setup

Production dependencies are separate in `requirements-live.txt`. The Oracle
integrations use their current PyPI releases—not a GitHub commit:

```text
langchain-oracledb==1.5.0
langgraph-oracledb==1.0.1
oracleagentmemory==26.6.0
e2b-code-interpreter==2.9.0
e2b==2.37.1
```

Provide secrets through the repository `.env` or an external secret manager; never
place them in source, Docker images or browser code:

```dotenv
ANTHROPIC_API_KEY=...
E2B_API_KEY=...
LANGSMITH_API_KEY=...
ORA_AGENT_PWD=...
```

From `part_1/custom_harness/deploy`:

```bash
docker compose up --build
```

Compose pulls `container-registry.oracle.com/database/free:latest-lite`, preserves
database state in `erpa-oracle-data`, loads the ONNX embedding model, applies the
schema and living semantic layer, installs both scheduler jobs, then starts the
appbook on port 8000.

Useful checks:

```bash
curl http://127.0.0.1:8000/api/foundation/status
curl http://127.0.0.1:8000/api/semantic_layer/status
curl http://127.0.0.1:8000/api/tools_and_mcp/status
curl http://127.0.0.1:8000/api/the_loop/status
curl http://127.0.0.1:8000/api/cache/status
curl http://127.0.0.1:8000/api/data_explorer/tables
curl http://127.0.0.1:8000/api/storefront/catalog
```

`docker compose down` keeps Oracle state. Removing the named volume deletes the
workshop database and is intentionally left as a manual destructive operation.
