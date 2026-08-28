# MemoRizz-native deep-research notebook

Open `advanced_deep_research.ipynb` with the repository `.venv` kernel. It is a
live-only implementation built directly from MemoRizz's
`DeepResearchOrchestrator`, six `ApplicationMode.DEEP_RESEARCH` MemAgents,
`TavilyProvider`, `OracleProvider`, OpenAI embeddings, and an E2B code sandbox. Each
agent has a private Oracle memory scope and participates in an Oracle-backed shared
research session. The complete implementation is visible in notebook cells.

```bash
.venv/bin/python -m jupyter lab part_1/advanced/deep_research/notebook
```

The notebook requests OpenAI, Tavily, E2B, and Oracle credentials through hidden
`getpass` prompts. All six agents use `gpt-5.5`; semantic memory uses real
`text-embedding-3-small` vectors shortened to the Oracle schema's 256 dimensions.
Market, technical, risk, and buyer specialists search live evidence in parallel. The
risk specialist also has the least-privilege `execute_code` tool, backed by E2B with
internet access disabled.

There is no offline research path and no substitute evidence. Type
`RUN LIVE DEEP RESEARCH` only after reviewing the expected external calls. For
non-interactive execution, supply credentials in the environment and run:

```bash
ADVANCED_RESEARCH_CONFIRMATION='RUN LIVE DEEP RESEARCH' \
  .venv/bin/python part_1/advanced/scripts/execute_notebooks.py \
  --profile live-deep-research \
  --notebook advanced_deep_research.ipynb \
  --timeout 1200
```

The default offline acceptance command compiles every cell in this notebook but does
not mislabel a static check as a successful provider run.
