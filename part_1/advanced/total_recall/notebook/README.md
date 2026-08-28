# Total Recall ontology notebook

`advanced_total_recall_ontology.ipynb` builds a complete retail-analytics agent
harness in visible cells. It covers the Oracle foundation, database-backed scratch
storage, encoding and retrieval, Oracle AI Agent Memory, the semantic layer,
semantic Toolbox and Skillbox, scheduled automations, a durable LangGraph loop,
context compaction, cross-session continuity, workflow-to-Skill promotion, and an
end-to-end business run.

The reasoning boundary is the official OpenAI Python client and Responses API with
the exact model ID `gpt-5.5`. Oracle AI Database remains the memory, embedding,
vector, checkpoint, semantic-registry, artifact, and scheduling substrate.

The notebook is self-contained: it imports no local harness implementation. Set
`ORA_DSN`, `ORA_AGENT_USER`, `ORA_AGENT_PWD`, and `OPENAI_API_KEY` in `.env` or
provide them through hidden prompts. Then execute all cells from top to bottom.

The Oracle application schema needs `CREATE SESSION`, `CREATE TABLE`, `CREATE
PROCEDURE`, `CREATE JOB`, and `CREATE MATERIALIZED VIEW`. The database
administrator must also load `ALL_MINILM_L12_V2` as a 384-dimensional mining
model in that schema. `CREATE DOMAIN` and read access to `SYS.V_$SQL` enrich the
semantic catalog but are optional because those two scans fail closed to the
documented fallback.

Live execution sends the synthetic retail prompts and any retrieved rows selected
for model context to OpenAI. Use an account and data-handling policy approved for
that transfer.

The live validation profile is:

```bash
.venv/bin/python part_1/advanced/scripts/execute_notebooks.py \
  --profile live-oracle-total-recall \
  --notebook advanced_total_recall_ontology.ipynb \
  --timeout 600
```
