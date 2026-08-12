# MemoRizz ERPA appbook

This appbook is the focused browser companion to `erpa_memorizz_complete.ipynb`. Its
navigation is an appbook-specific sequence from 01 through 12; it does not mirror the
notebook's part numbers. It folds environment, Oracle, business-data, prompt-authority, and MemAgentBuilder context
into the sections where learners use those decisions. It covers Assistant-mode memory,
Toolbox and E2B, Skillbox, Notion MCP, context compaction, semantic cache,
delegation/shared memory, human approval, scenarios, scoped cleanup, and a complete
teaching ecommerce storefront.

The first section contains a clickable technical reference architecture. Hovering or
focusing a component explains its harness responsibility; selecting it opens the
matching chapter. The memory, tool execution, skill disclosure, context compaction,
cache, and orchestration chapters each provide a purpose-built interactive lab. A
collapsible database explorer stays at the bottom of the browser and shows every
appbook-owned table, recent reads and writes, and short-lived transaction highlights.
The storefront contains twelve products and ERPA retains the active product across
follow-up turns, so it can answer product detail, price, size, stock, paid-customer
demand, and the wider workshop scenario questions.

## Run the deterministic teaching profile

```bash
python -m pip install -r requirements.txt
./run.sh
```

Open `http://127.0.0.1:8000`. This profile is credential-free, persists only scoped
teaching state in `data/memorizz_local.db`, and returns the notebook's acceptance
anchors. It is clearly labelled in the UI and performs no external mutation. The
runtime uses Oracle-shaped `course_*` teaching tables so the data explorer can make
reads, writes, cache hits, tool logs, approvals, carts, and shared-memory events
visible without exposing a production schema.

The Tool + Execution lab can use a real E2B sandbox without enabling live Oracle or
model inference. Enter the key into the shell without writing it into source control,
then launch with the Python environment containing the MemoRizz sandbox extra:

```zsh
read -s "E2B_API_KEY?E2B API key: "
export E2B_API_KEY
ERPA_PYTHON=/path/to/python ./run.sh
```

When `E2B_API_KEY` is present, the lab executes remotely by default. Use
`ERPA_RUN_E2B=0` only when you deliberately want the non-executing teaching fallback.

## Enable live preflights and the MemoRizz factory

Install the same extras as the notebook:

```bash
python -m pip install -r requirements-live.txt
export ERPA_MODE=live
export ORACLE_DSN='127.0.0.1:1522/FREEPDB1'
export ORACLE_USER='MEMORIZZ_COURSE'
export ORACLE_PASSWORD='...'
export OPENAI_API_KEY='...'
export E2B_API_KEY='...'
ERPA_PYTHON=/path/to/your/course/python ./run.sh
```

`NOTION_MCP_TOKEN` is optional; without it the live factory selects OAuth. Set
`E2B_API_KEY` to make the tool lab create a remote E2B microVM; a configured key opts
into execution by default. Set `ERPA_RUN_E2B=0` to disable remote execution explicitly.
`ERPA_E2B_TEMPLATE` is optional and should only name a real custom E2B template; when
it is absent, MemoRizz uses E2B's default Code Interpreter. `ERPA_PYTHON` lets the
launcher use the environment where the live dependencies are installed. No endpoint
returns secret values.

The live composition is centralized in `backend/core/live_memorizz.py`: one
`MemAgentBuilder` assembles the Oracle provider, Assistant mode, the trusted business
functions in a native progressively disclosed Toolbox, Oracle Skillbox retrieval,
Notion MCP policy, semantic cache,
continual learning, loop bound, and MemoRizz-managed E2B provider. Routers and
frontend code do not duplicate that harness configuration. Tool demonstrations also
route sandbox work through MemoRizz's `SandboxManager`; the app does not call the E2B
SDK directly.

## Observe appbook runs in MemoRizz UI

When Oracle credentials are configured, every appbook POST action is mirrored into
MemoRizz's native Oracle stores under the stable agent `ERPA · Appbook`
(`erpa-appbook-observability`). Conversation activity and structured trace bundles go
to conversation memory; validated capability executions also go to `TOOL_LOG` with
agent, memory, thread, run, and tool-call correlation IDs. Inline chart artifacts and
credentials are omitted from telemetry.

Start the UI against the same environment and connect it to the same Oracle schema:

```bash
memorizz ui --host 127.0.0.1 --port 8765
```

Open `http://127.0.0.1:8765/traces?agent_id=erpa-appbook-observability`. The Traces
timeline expands MemoRizz trace bundles into lifecycle, tool-call, and tool-result
events and joins durable execution logs from `TOOL_LOG`. Set
`ERPA_MEMORIZZ_OBSERVABILITY=0` only when this local Oracle mirror is deliberately
disabled. The appbook remains fail-open if Oracle observability is unavailable: the
teaching interaction succeeds and its response reports that the trace was not recorded.

The seven original API routes remain as compatibility endpoints for the course's
zero-credential acceptance suite. The browser uses `/api/workshop/*` for the expanded
17-part material.
