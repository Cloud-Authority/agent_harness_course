# Live MemoRizz MetaHarness appbook

This appbook sends real queries through a MemoRizz MetaHarness. The outer loop
retrieves scoped Oracle incident evidence, routes to an eligible OpenAI,
Anthropic, or DeepSeek harness,
normalizes events, and saves execution evidence. Oracle AI Database is used for
memory, runs, events, workspace leases, and approval state.

Set the Oracle values and `OPENAI_API_KEY` in the course `.env`. OpenAI supplies
live memory embeddings while Oracle remains the sole database and vector store.
Add `ANTHROPIC_API_KEY` and/or `DEEPSEEK_API_KEY` for the optional harnesses, then run:

```bash
cd part_1/advanced/metaharness/appbook
./run.sh
```

Open <http://127.0.0.1:8012>. A submitted query makes a real provider request
and may incur provider charges.

The interactive diagram shows the MetaHarness boundary with its three inner
harnesses. Node state is derived from the live Oracle event stream. Click a
node to inspect its task data, routing decision, bounded context, exact model
input sections, durable evidence, or response. Credentials and private model
reasoning are never returned to the browser.

Implementation map:

- `shared/metaharness_demo.py` — compact HTTP-facing facade
- `shared/live_model_harness.py` — live provider adapter
- `shared/oracle_harness_stores.py` — Oracle run and approval persistence
- `appbook/backend/main.py` — asynchronous execution and inspection endpoints
- `appbook/frontend/` — interactive execution map and context modal
