# Harness Engineering for AI Agents

This repository is the technical companion to Richmond Alake's O'Reilly live
workshop, [Harness Engineering for AI Agents](https://www.oreilly.com/live-events/harness-engineering-for-ai-agents/0642572381264).
It turns the workshop's memory-first architecture into runnable code, narrated
notebooks, interactive appbooks, staged exercises, and a production-oriented
deployment path.

The example system is **ERPA**, a fictional retail-planning assistant built twice
against the same synthetic Kata dataset:

| Path | Approach | Best for |
|---|---|---|
| [MemoRizz build](part_1/harness_done_for_you/memorizz/assistant/) | A packaged harness with the major decisions made for you | Learning the anatomy of a complete harness |
| [Custom build](part_1/custom_harness/) | An explicit, modular LangGraph-style harness | Understanding how each layer is assembled |

Both paths demonstrate working, episodic, semantic, and procedural memory; trusted
tools and progressive capability disclosure; sandboxed execution; semantic caching;
and observable `recall -> decide -> write` traces.

## Quick start

Local workshop mode is deterministic, credential-free, and uses generated synthetic
data. It requires Python 3.11 or newer.

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install \
  -r part_1/harness_done_for_you/memorizz/assistant/appbook/requirements.txt \
  -r part_1/custom_harness/appbook/requirements.txt
python part_1/tests/smoke_test.py
```

Start either interactive appbook:

```bash
# Packaged MemoRizz harness: http://127.0.0.1:8000
cd part_1/harness_done_for_you/memorizz/assistant/appbook
./run.sh

# Or, from the repository root, run the custom harness on port 8001
cd part_1/custom_harness/appbook
PORT=8001 ./run.sh
```

For the narrated exercises, open
[`erpa_memorizz_complete.ipynb`](part_1/harness_done_for_you/memorizz/assistant/notebook/erpa_memorizz_complete.ipynb)
or [`erpa_custom_complete.ipynb`](part_1/custom_harness/notebook/erpa_custom_complete.ipynb)
in Jupyter.

## Repository guide

- [`part_1/README.md`](part_1/README.md) explains participant setup, the two builds,
  and the workshop architecture.
- [`part_1/custom_harness/stages/`](part_1/custom_harness/stages/) contains six small,
  independently runnable construction stages.
- [`part_1/_shared/`](part_1/_shared/) is the source of truth used by both builds for
  the synthetic dataset, fixtures, runtime contracts, and canonical demo.
- [`part_1/scripts/`](part_1/scripts/) contains the cache and cross-process persistence
  acceptance checks used during the workshop.
- [`part_1/INSTRUCTOR_RUNBOOK.md`](part_1/INSTRUCTOR_RUNBOOK.md) provides the live
  teaching sequence and preflight checklist.
- [`part_1/SPEC_COVERAGE.md`](part_1/SPEC_COVERAGE.md) maps the workshop requirements
  to implementation evidence.

## Optional live stack

The local profile needs no keys. The live paths add model providers, Oracle AI
Database, MemoRizz/OAMP memory, E2B, Notion MCP, Tavily, LangSmith, and durable
LangGraph checkpointing. Copy `.env.example` to `.env`, supply only the services you
intend to use, and never commit that file.

The complete custom stack can be launched with Docker Compose after setting
`ANTHROPIC_API_KEY`, `E2B_API_KEY`, `LANGSMITH_API_KEY`, `ORACLE_PASSWORD`, and
`ORA_AGENT_PWD`:

```bash
cd part_1/custom_harness/deploy
docker compose up --build
```

See the [deployment guide](part_1/custom_harness/deploy/README.md) for details.

## Safety and scope

All customer and commercial records are synthetic. The local sandbox exposes only
fixed workshop operations: it cannot execute arbitrary shell commands or make
unrestricted network requests. The examples do not execute payments, mutate the
historical business dataset, or autonomously approve commercial decisions.
