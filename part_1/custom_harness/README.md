# Build B — custom ERPA harness

Every layer is explicit and swappable:

```text
boundary semantic cache
  └─ assemble_context (OAMP recall · compaction · skills · tools · semantic schema)
       └─ call_model
            └─ dispatch_tools (MCP · semantic SQL · Tavily · sandbox)
                 └─ persist (OAMP writes · checkpoint · trace)
```

`ERPA_MEMORY_BACKEND` changes the memory factory and `ERPA_CACHE_ENABLED` disables the
cache without touching graph code. Semantic layer, retriever, skills, registry and
sandbox each live in their own module.

```bash
python stages/stage_01_single_turn.py   # through stage_06_complete_harness.py
cd appbook && ./run.sh
python ../../scripts/cache_measurement.py
```

The appbook contains all nine requested interactive chapters. Local SQLite mirrors the
single-substrate Oracle anatomy for a no-credential class. Live mode is a real
single-substrate path: OAMP 26.6, `OracleSemanticCache`, `OracleSaver`, business SQL,
scheduled briefs and generated files all use Oracle AI Database 26ai.

```bash
cd deploy
ANTHROPIC_API_KEY=... E2B_API_KEY=... LANGSMITH_API_KEY=... \
  ORACLE_PASSWORD=... ORA_AGENT_PWD=... docker compose up --build
```

The Compose project pulls Oracle AI Database Free `latest-lite`, creates the application
user and schema idempotently, loads the shared fixtures, installs the DBMS_SCHEDULER job,
then starts the app at `http://127.0.0.1:8000`.
