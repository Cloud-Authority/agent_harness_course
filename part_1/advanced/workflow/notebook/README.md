# Durable workflow notebook

Open `advanced_durable_workflow.ipynb` with the repository `.venv` kernel. The notebook
defines its tool functions, JSON contracts, database registration functions, Skillbox,
sandbox boundary, graph nodes, reducers, routes, and promotion rule directly in cells;
it does not import `WorkflowHarness`.

The compiled 17-node LangGraph demonstrates three expected trajectories: missing
evidence stops safely, a standard supplier follows a short policy path, and a high-risk
supplier fans out into parallel freshness, sanctions, and audit checks before joining
for risk scoring, remediation, an interrupt, named approval, publication, and
verification. LangGraph's native Mermaid renderer shows the executable topology.

```bash
.venv/bin/python -m jupyter lab part_1/advanced/workflow/notebook
```

Oracle is the notebook's only persistence profile. `OracleSaver`, Oracle Agent Memory,
the Toolbox, Skillbox, and workflow-recipe rows all use Oracle AI Database. OpenAI
semantic retrieval and model drafting plus E2B execution are used when their valid
credentials are supplied. Hash embeddings, deterministic drafting, and the isolated
subprocess may be selected for an offline provider profile, but their data still
persists in Oracle.

Every selected tool crosses the notebook-defined sandbox function automatically. Set
`ADVANCED_SANDBOX_LIVE=1` before launching Jupyter to use a fresh egress-blocked E2B
sandbox per tool; the notebook collects the key with `getpass` if needed. The local
profile proves envelope mechanics and host recomputation only and reports that remote
isolation was not proven.
