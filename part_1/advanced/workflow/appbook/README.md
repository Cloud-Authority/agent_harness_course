# Durable workflow appbook

This control room is the operational companion to
[`advanced_durable_workflow.ipynb`](../notebook/advanced_durable_workflow.ipynb).
It displays the notebook's 17-node teaching graph and its three expected outcomes:
Northstar's parallel full review, Bluebird's short review, and Contoso's safe
missing-evidence stop.

The live control surface executes Northstar's high-risk outcome as an 18-node
operational extension. It adds Oracle Agent Memory recall, model planning,
operation-ledger recovery, recipe capture, and Skill promotion around the notebook
policy. It is not a node-for-node copy; the UI labels that distinction instead of
presenting the two graphs as identical.

All persisted AppBook state uses Oracle AI Database: `OracleSaver`, Oracle Agent
Memory with `OracleDBMemoryStore`, `OracleStore`, and the typed semantic Toolbox,
Skillbox, and workflow-recipe catalogs. The production AppBook has no in-memory
persistence profile.

The canonical demo intentionally fails after the draft operation has committed,
resumes the same Oracle-checkpointed thread, pauses at a LangGraph `interrupt()`, and
publishes once after a host decision. A second comparable verified run demonstrates
promotion of a repeated workflow into a SHA-versioned Skill.

From the repository root, install the published dependencies once:

```bash
python3.12 -m venv .venv
.venv/bin/python -m pip install -r part_1/advanced/requirements.txt
```

Configure the existing `ORA_DSN`, `ORA_AGENT_USER`, and `ORA_AGENT_PWD` values in the
root `.env`, then run:

```bash
cd part_1/advanced/workflow/appbook
./run.sh
```

Open <http://127.0.0.1:8010>. `run.sh` forces `ADVANCED_BACKEND=oracle`.
OpenAI vector/model behavior and E2B are used when valid keys are available. To run
the same Oracle-persisted AppBook without OpenAI or remote sandbox calls, use:

```bash
ADVANCED_SEMANTIC_BACKEND=hash \
ADVANCED_AGENT_MEMORY_SEARCH_STRATEGY=keyword \
ADVANCED_USE_MODEL_SYNTHESIS=false \
OPENAI_API_KEY= E2B_API_KEY= ./run.sh
```

Those settings alter embedding, drafting, and sandbox providers only; checkpoints,
Agent Memory, catalogs, recipes, and the operation ledger remain in Oracle. Every
provider choice is named in the status panel.
