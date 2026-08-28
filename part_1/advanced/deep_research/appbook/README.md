# Live MemoRizz deep-research appbook

This FastAPI/UI app is the delivery surface for the same direct architecture as
`advanced_deep_research.ipynb`. It uses the published MemoRizz package—without a
MetaHarness adapter or an offline fixture path—to run:

- one GPT-5.5 root MemAgent whose model generates the task decomposition;
- market, technical, risk, and buyer GPT-5.5 specialist MemAgents;
- one GPT-5.5 synthesis MemAgent;
- Tavily live retrieval with an append-only in-process audit view;
- an E2B sandbox available only to the risk specialist; and
- OpenAI `text-embedding-3-small` with MemoRizz Oracle private/shared memory.

The execution endpoint returns immediately and the browser consumes a Server-Sent
Events stream. Node status changes are visible while the planner, specialists,
tools, shared memory, synthesis, and host review run. Click any agent node to inspect
its instruction, generated assignment, private Oracle conversation memory, tool logs,
shared-blackboard view, live events, and context-budget telemetry. The inspector does
not expose private chain-of-thought or credentials.

## Start it

Put the live credentials in the ignored repository `.env` (or export them), then:

```bash
cd part_1/advanced/deep_research/appbook
./run.sh
```

Open <http://127.0.0.1:8011>. Required values are `OPENAI_API_KEY`,
`TAVILY_API_KEY`, `E2B_API_KEY`, and the Oracle user/password/DSN fields. The default
DSN is `127.0.0.1:1523/FREEPDB1`.

Oracle HNSW indexes require a nonzero vector pool. For this local database, the fixed
setting is 256 MB. Confirm it from a SYSDBA session with:

```sql
SHOW PARAMETER vector_memory_size;
SELECT pool, alloc_bytes, used_bytes FROM v$vector_memory_pool;
```

The shared Harness Inspector remains read-only. Its Data Explorer exposes only the
MemoRizz Oracle memory tables selected by the app plus safe runtime snapshots; secrets
and sensitive columns are redacted.
