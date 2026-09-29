# One memory, four harnesses

A **harness** is the loop around a model: it sends the prompt, runs the tools the
model asks for, and returns an answer. A **meta-harness** sits one level above. It
prepares the task, supplies memory, sets the limits, starts one harness, and
records what happened in one common format.

This folder runs the same personal productivity assistant (PPA) jobs on four
harnesses, with MemoRizz's `MetaHarness` as the outer layer:

| # | Harness | What runs the loop |
|---|---|---|
| 1 | MemoRizz `MemAgent` | MemoRizz itself, in the notebook's process |
| 2 | pi | The pi coding agent, as a subprocess |
| 3 | Hermes | Hermes Agent, as a subprocess |
| 4 | DeepSeek | Claude Code's loop on DeepSeek's Anthropic-compatible API |

| Path | What it is |
|---|---|
| `notebook/ppa_metaharness_pi_deepseek_hermes.ipynb` | The notebook, saved with the outputs of a real run |
| `run_harness.py` | A command line runner: one job on one harness, with result, usage and anchors |

## Status

| Harness | Status in the saved run | Authentication | Cost figure |
|---|---|---|---|
| MemAgent | Ran live | `ANTHROPIC_API_KEY` | Estimated from list prices |
| pi 0.87.1 | Ran live, three jobs | `ANTHROPIC_API_KEY`, passed by MemoRizz | Reported by pi |
| Hermes Agent 0.21.5 | Ran live, three jobs | `ANTHROPIC_API_KEY`, passed by MemoRizz | Estimated from list prices. Hermes reports none |
| DeepSeek (Claude Code 2.1.284) | **Not run.** The readiness probe reports `authentication_required` | `DEEPSEEK_API_KEY`, which this machine does not have | Estimated by MemoRizz when it runs |

The DeepSeek path is built and its readiness probe was run. No DeepSeek run was
made, and no DeepSeek output appears anywhere in this track. With a key in
`DEEPSEEK_API_KEY` the same notebook cells and the same runner run it.

## What the external harnesses may do

Every run is read-only: no shell, no network tools, no writes. An action that
another person would see can only be proposed in the answer.

| Harness | Tools enabled for a read-only run | Never enabled |
|---|---|---|
| pi | `read`, `grep`, `find`, `ls` | `bash`, `edit`, `write` |
| Hermes | The `file` toolset, with writes pointed at an empty folder | Terminal, code execution, browser, delegation, its own memory and skills |
| DeepSeek | `Read`, `Glob`, `Grep` | `Bash`, web tools, edits |

Two limits are worth knowing. Hermes can read files outside the workspace: MemoRizz
confines its writes, and documents that its reads are not confined. pi cannot do a
write run at all without external isolation.

## The notebook

The notebook is standalone. It loads the mail from Hugging Face, writes the
workspace folder itself, and imports nothing from this repository.

```bash
export ANTHROPIC_API_KEY=...
export MEMORIZZ_PI_COMMAND=/path/to/pi            # when pi is not on PATH
export MEMORIZZ_HERMES_COMMAND=/path/to/hermes    # when hermes is not on PATH
jupyter lab notebook/ppa_metaharness_pi_deepseek_hermes.ipynb
```

It needs a MemoRizz build that has the pi, Hermes and DeepSeek adapters. They are
newer than the 0.12.0 release on PyPI. The notebook checks for them in Part 1 and
stops with a message if they are missing. Set `PPA_MEMORIZZ_SPEC` to install a
build that has them, for example
`memorizz[anthropic,filesystem] @ file:///path/to/memorizz`.

| Part | Subject |
|---|---|
| 1 | Environment: packages, folders, keys, provider and model of each harness |
| 2 | The world, from real data |
| 3 | Governed definitions, checked before any model runs |
| 4 | Write the workspace: governed JSON, delimited text, lock and hash |
| 5 | One memory: the native MemAgent stores the owner's preference |
| 6 | The meta-harness and the readiness of each harness |
| 7 | The task envelope, the context pack and the jobs |
| 8 | Run the jobs on every harness |
| 9 | Acceptance anchors, computed from the data |
| 10 | The comparison: tools, steps, tokens, cost, latency, steering |
| 11 | Evidence: traces, the two gates before a write, memory, the run ledger |

Sections are numbered `N.M`, and 13 of them carry a star: they are the ones to show
live, and together they take about 36 minutes. The notebook opens with its contents
and with the live path, which says for every starred section what to show and where
to start to run it again.

Run all cells before a session and keep the kernel alive. The last section closes
the meta-harness. To run a section of Parts 6 to 11 again, run section 6.2 first: it
opens a new meta-harness over the same memory and ledger. A job that is run a second
time replaces its row in the comparison.

No lesson needs a sign-in to a mail or calendar provider. The mailbox is public
data that pandas reads from Hugging Face, and a copy is kept in the state folder.

| Variable | Default | Meaning |
|---|---|---|
| `PPA_HOME` | `ppa_data`, next to the notebook | State: memory, run ledger, approvals, the mailbox copy, the homes of MemoRizz and pi |
| `PPA_WORKSPACE` | `ppa_workspace`, next to the notebook | The folder the harnesses read |
| `PPA_META_MEMORY_ID` | `ppa-one-memory` | The memory workspace. A rerun clears only this scope |
| `MEMORIZZ_PI_PROVIDER`, `MEMORIZZ_PI_MODEL` | `anthropic`, `PPA_MODEL` | Provider and model of pi |
| `MEMORIZZ_HERMES_PROVIDER`, `MEMORIZZ_HERMES_MODEL` | `anthropic`, `PPA_MODEL` | Provider and model of Hermes |
| `MEMORIZZ_DEEPSEEK_MODEL` | `deepseek-flash` | Model of the DeepSeek harness |

## The runner

```bash
python metaharness/run_harness.py --doctor
python metaharness/run_harness.py --harness pi --job morning_brief
python metaharness/run_harness.py --harness hermes --job inbox_triage --json
python metaharness/run_harness.py --harness pi --job recall \
    --remember "Keep Friday afternoons free of meetings."
```

The runner uses the shared practice workspace of Part 2, so it needs no download.
It exports the workspace to `workspace/cli`, keeps its state in `data/cli`, runs one
job and prints the status, the latency, the steps, the tools, the tokens, the cost,
the acceptance anchors and the answer.

| Option | Meaning |
|---|---|
| `--harness` | `pi`, `hermes` or `deepseek` |
| `--job` | `morning_brief`, `inbox_triage`, `meeting_prep` or `recall` |
| `--remember TEXT` | Store a preference in memory before the run |
| `--question TEXT` | The question of the `recall` job |
| `--fresh` | Delete the runner's memory scope before the run |
| `--doctor` | Print the readiness of every harness and exit |
| `--json` | Print one JSON document instead of text |

Exit codes: `0` the run succeeded, `1` the run failed, `2` the harness is not
ready. A harness that is not ready is reported with its reason and is not run.
