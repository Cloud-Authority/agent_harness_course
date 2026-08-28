# MemoRizz MetaHarness notebooks

`advanced_metaharness.ipynb` is a live, Oracle-only lesson. It explains why an
application may need an outer harness, traces the installed MemoRizz modules,
assembles the MetaHarness in visible cells, turns live Oracle run/event rows into
scoped incident evidence, and sends a learner-authored triage query to a real
OpenAI, Anthropic, or DeepSeek harness.

Configure Oracle AI Database and `OPENAI_API_KEY` in the course `.env` for live
memory embeddings. That key also enables the OpenAI harness; add
`ANTHROPIC_API_KEY` and/or `DEEPSEEK_API_KEY` for the optional harnesses. Then start
Jupyter:

```bash
.venv/bin/python -m jupyter lab part_1/advanced/metaharness/notebook
```

The query cell incurs the normal provider charge. Durable memory, run state,
events, workspace leases, and approval state remain in Oracle after the
notebook closes its connection pool. Before the provider call, the notebook
prints the minimized incident evidence and requires explicit acknowledgement
that it may enter external provider context; original user text and thread/memory
identifiers are excluded.

For a non-interactive, output-preserving run of both live harnesses, use the
restricted profile. Credentials missing from `.env` are requested with hidden
terminal prompts and remain in process memory:

```bash
.venv/bin/python part_1/advanced/scripts/execute_notebooks.py \
  --profile live-metaharness \
  --notebook advanced_metaharness.ipynb \
  --harness both \
  --confirm-live-metaharness \
  --timeout 600
```

`advanced_fair_harness_evaluation.ipynb` is a separate evaluation-methodology
lesson and is not required for the live MetaHarness walkthrough.
