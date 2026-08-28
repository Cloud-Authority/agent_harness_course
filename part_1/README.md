# Part 1 — ERPA, memory-first assistant mode

The same Kata merchandising assistant is built twice. Build A optimises for recognition;
Build B optimises for construction. They import the same fixtures and emit the same
`recall → decide → write` instrumentation contract.

After those foundations, [`advanced/`](advanced/) adds the Advanced Harness Engineering
track: a crash-resumable LangGraph workflow on local Oracle AI Database, a parallel
Tavily research harness with cross-session evidence learning, and a PyPI-only MemoRizz
MetaHarness lab with GPT-5.5, Claude Opus 5, and E2B behind durable approvals, followed
by a fair harness-evaluation capstone.

| | Build A · MemoRizz | Build B · custom |
|---|---|---|
| Memory substrate | MongoDB Atlas | OAMP 26.6 on Oracle AI Database 26ai |
| Enterprise data | read-only Oracle/local mirror | Oracle, co-located with memory |
| Tool transport | direct Python/API calls | Notion/Calendar MCP + Tavily + sandbox |
| Loop | MemAgent abstraction | four explicit graph nodes |
| Cache | not taught | before `assemble_context` |
| Time | ~15 minutes | ~30 minutes |

## Prerequisites

Local mode requires Python 3.11+ and the small appbook requirements provisioned in
advance. `run.sh` performs no installation or authentication. No Node build is used by
either appbook. Jupyter is optional.

The provisioned live environment additionally requires:

- an OpenAI API key for the MemoRizz build and an Anthropic API key for the custom build
- MongoDB Atlas URI with ready vector search indexes
- Oracle AI Database 26ai credentials (`python-oracledb` thin mode)
- dedicated Notion workspace and Google Calendar demo account
- **Tavily API key and LangSmith API key** (both are required even though they were not
  on the published attendee prerequisite list)
- read/create Calendar OAuth and read-only, per-page-shared Notion access

Copy `.env.example` at the repository root to `.env`. Never commit credentials,
`credentials.json`, `token.json`, a wallet or generated customer data.

## Local workshop

```bash
python part_1/_shared/seed/generate_seed_data.py --validate-only

cd part_1/harness_done_for_you/memorizz/assistant/appbook
./run.sh                         # http://127.0.0.1:8000

cd ../../../custom_harness/appbook
PORT=8001 ./run.sh               # http://127.0.0.1:8001
```

Every endpoint warms idempotently in a background thread. The frontend appears
immediately and reports readiness. Both apps serve the SPA and API from one origin.

For the complete live custom stack, Docker Desktop must be running and an OpenAI key
must be exported. Compose pulls Oracle AI Database Free, persists its data in a named
volume, creates the `AGENT` user, loads fixtures, starts OAMP and compiles LangGraph
with `OracleSaver`:

```bash
cd part_1/custom_harness/deploy
ANTHROPIC_API_KEY=... E2B_API_KEY=... LANGSMITH_API_KEY=... \
  ORACLE_PASSWORD=... ORA_AGENT_PWD=... docker compose up --build
```

## Teaching artifacts

- [`guides/`](guides/) contains the foundation and advanced Harness Engineering for
  AI Agents presentation guides.
- Both complete notebooks have saved output after every code cell and narrative between
  every step: what it is, why it matters, what to watch.
- `custom_harness/stages/` contains six independently runnable stage scripts.
- `_shared/demo_script.md` is the canonical five turns; never edit one build's copy.
- `scripts/cache_measurement.py` proves a warm hit has no model span.
- `scripts/restart_proof.py` uses two actual Python processes.
- `custom_harness/deploy/` contains the Docker/OCI, DBMS_SCHEDULER and Vercel path.
- `advanced/` contains five narrated notebooks, four appbooks, an instructor runbook,
  E2B and fair-evaluation labs, offline acceptance tests, and a three-process Oracle
  recovery proof.

## Safety and course scope

All customer records are synthetic and pseudonymous. ERPA cannot execute payments,
write business data, delete Calendar events, write Notion pages or autonomously approve
commercial decisions. The fixed-operation sandbox renders a known chart; it cannot run
arbitrary user code, shell commands or network requests.
