# Total Recall appbook

This appbook presents the harness as ten connected, interactive layers:
foundation and in-database models, the durable scratch substrate, encoding and
retrieval, Oracle AI Agent Memory, the semantic catalog, Toolbox and Skillbox,
the agent loop, context engineering, ontology-grounded GraphRAG, and mission
control.

The backend uses Oracle AI Database for embeddings, vector/relational state,
memory, registries, workflow recipes, materialized views, and scheduled jobs.
All reasoning and function calling uses the OpenAI Python client with `gpt-5.5`
through the Responses API. The ontology endpoints, context-window inspector, and
read-only data explorer remain available alongside the layered experience.

## Run

From the repository root, configure `ORA_DSN`, `ORA_AGENT_USER`,
`ORA_AGENT_PWD`, and `OPENAI_API_KEY` in `.env`, then run:

```bash
part_1/advanced/total_recall/appbook/run.sh
```

Open <http://127.0.0.1:8013>. API documentation is available at
<http://127.0.0.1:8013/docs>.

The Oracle application schema requires the same schema-local privileges and the
384-dimensional `ALL_MINILM_L12_V2` mining model listed in the notebook README.
Agent runs send the selected synthetic retail context to OpenAI; use a valid API
key and an approved data-handling policy.

Semantic retrieval uses exact Oracle cosine distance by default. Set
`TR_ENABLE_HNSW=1` only after allocating enough Oracle vector-memory capacity;
startup preserves an existing index and never drops one.

## Important boundaries

- Tool callables remain in Python; their descriptions and JSON contracts live in
  the semantic Toolbox.
- Skills are `SKILL.md` documents stored with SHA-256 versions and retrieved in
  two stages.
- The context inspector shows assembled input sections, never private reasoning.
- The data explorer is read-only and redacts sensitive columns.
- A provider response proves execution, not business-answer correctness; domain
  checks and human approval remain necessary for consequential actions.
