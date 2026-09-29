# Part 2 · The harness done for you

**PPA** is a personal productivity assistant. It reads one person's mail and
calendar, decides what deserves attention, turns requests into tracked tasks,
protects time for focused work, and asks before anything leaves the building.

A **harness** is the code around a language model: it assembles the context, runs
the tools the model asks for, remembers what happened, and stops the model before
it does something irreversible. In the custom-harness track you write that code
yourself. In this track somebody else wrote it, and the question is what that
leaves for you to do.

The track has two notebooks and one theme: **one memory, four harnesses**.

| # | Harness | What runs the loop | Where |
|---|---|---|---|
| 1 | MemoRizz `MemAgent` | MemoRizz, in the notebook's process | `memorizz/assistant/notebook/` |
| 2 | pi | The pi coding agent, as a subprocess | `metaharness/` |
| 3 | DeepSeek | Claude Code's loop on DeepSeek's Anthropic-compatible API | `metaharness/` |
| 4 | Hermes | Hermes Agent, as a subprocess | `metaharness/` |

In the second notebook MemoRizz is the **meta-harness**: the layer above the
harnesses that prepares the task, supplies memory, sets the limits, starts one
harness and records what happened in one common format.

## Status

Everything in this table was run on 2026-09-29, on macOS with Python 3.12, with
`claude-opus-5-5` at effort `medium`. "Not run" means exactly that.

| Harness | Installed from | Authentication | What ran live | Known limits |
|---|---|---|---|---|
| MemAgent | MemoRizz in `.venv`. Also run on `memorizz` 0.12.0 from PyPI | `ANTHROPIC_API_KEY` | The whole first notebook: 12 model-driven steps, 31 of 31 acceptance anchors | Scheduled jobs are run by the notebook, because MemoRizz's stock worker cannot call Python tools |
| pi 0.87.1 | npm, into `.tools/` | `ANTHROPIC_API_KEY`, passed by MemoRizz | Three read-only jobs, 20 of 20 anchors. The command line runner | pi cannot do a write run without external isolation |
| Hermes Agent 0.21.5 | Source, tag `v2026.9.24`, into `.tools/` | `ANTHROPIC_API_KEY`, passed by MemoRizz | Three read-only jobs, 20 of 20 anchors. The command line runner | Hermes reports no cost. Its reads are not confined to the workspace |
| DeepSeek | Claude Code 2.1.284, already on this machine | `DEEPSEEK_API_KEY`, **not available** | **Only the readiness probe.** It reports `authentication_required` | No DeepSeek run was made. No DeepSeek output exists in this track |

Not run at all: the Oracle memory backend, MemoRizz's memory server (MCP) inside a
harness run, and any write run by an external harness.

## Quick start

```bash
cd part_2/harness_done_for_you
export ANTHROPIC_API_KEY=...          # or put it in .env, see .env.example

# 1. Offline checks: no key, no network, a few seconds
.venv/bin/python -m pytest tests -q

# 2. Which harness is ready on this machine? No model is called
.venv/bin/python metaharness/run_harness.py --doctor

# 3. One job on one harness
.venv/bin/python metaharness/run_harness.py --harness pi --job morning_brief

# 4. Execute a notebook in place and keep its outputs (about 4 minutes each)
scripts/execute_notebooks.sh memorizz
scripts/execute_notebooks.sh metaharness

# 5. Regenerate a notebook after a change to its text. Outputs are kept when no code changed
MMDC=/path/to/mmdc .venv/bin/python scripts/build_memorizz_notebook.py
MMDC=/path/to/mmdc .venv/bin/python scripts/build_metaharness_notebook.py
```

To teach from a notebook, open it with the Python of `.venv` as the kernel. Both
notebooks are saved with the outputs of a real run, so they can be read without
running anything.

## What is in this folder

| Path | What it is |
|---|---|
| `memorizz/assistant/notebook/ppa_memorizz_complete.ipynb` | Notebook 1: PPA on MemoRizz's `MemAgent` |
| `metaharness/notebook/ppa_metaharness_pi_deepseek_hermes.ipynb` | Notebook 2: the same jobs on pi, Hermes and DeepSeek |
| `metaharness/run_harness.py` | Command line runner: one job on one harness |
| `scripts/export_workspace.py` | Writes the practice workspace as files, for the runner |
| `scripts/build_memorizz_notebook.py`, `scripts/build_metaharness_notebook.py` | Generate the notebooks from plain text |
| `scripts/notebook_parts.py` | The cells both notebooks share, the outline, and the style checks |
| `memorizz/assistant/notebook/diagrams/`, `metaharness/notebook/diagrams/` | The source and the image of every diagram |
| `scripts/execute_notebooks.sh` | Executes the notebooks with the environment of this track |
| `scripts/scan_notebooks.py` | Scans saved notebooks for keys, home paths and the user name |
| `ppa_dfy/` | Code for the runner and the tests. The notebooks do not import it |
| `tests/` | Offline tests |
| `requirements.txt`, `.env.example` | Packages and settings |
| `.venv/`, `.tools/`, `data/`, `workspace/` | Local environment, tools and generated state. Ignored by Git |

## The two notebooks are standalone

Each notebook contains all the code it runs. Copy the one `.ipynb` file to an
empty folder, run the first cell to install the packages, supply a key, and run it
top to bottom. A notebook imports nothing from this repository.

The data is real and is loaded inside the notebook:

| Data | Source | Pinned revision |
|---|---|---|
| One mailbox, five months of mail | `corbt/enron-emails`, read with pandas and PyArrow over `hf://` | `cfc06c758093d90993abce1a43668fb7357258a6` |
| Three prompt-injection emails | `microsoft/llmail-inject-challenge`, entries labelled `api_triggered`, chosen by hash order | `1063bdf01ec8762b812d5e06ee768a06faa5a6f7` |

pandas reads only the mailbox it needs. It names the columns to fetch, and it gives
two filters on the file name, so that the reader skips every block of rows that
cannot contain the mailbox. The result is kept as a file in the state folder, and a
second run downloads nothing.

**No lesson needs a sign-in to a mail or calendar provider.** The mailbox and the
calendar are public data. The only credential is the key of the model provider.

The scenario (mailbox, clock, timezone, working rules) is one cell of parameters.
Nothing else about the owner is typed in. `tests/test_notebooks_static.py` checks
that, and `tests/test_notebook_rules.py` checks that the rules a notebook carries
give the same answers as the shared policy of Part 2.

The builders regenerate the notebooks. A builder keeps the saved outputs only when
no code cell changed. When code changed, execute the notebook again.

## Finding your way in a notebook

The notebooks are long, so their headings are made for the outline of the editor.

| Sign | Meaning |
|---|---|
| `# Part N · Title` | A top-level section |
| `## N.M · Title` | Section M of Part N |
| A star after the number | A section to show live. The starred sections alone tell the whole story |
| `## Takeaways · Part N` | The last section of every part |

Each notebook opens with three short sections: how to use it, its contents, and
the live path. The live path lists the starred sections in order, with what to
show, the minutes, and where to start to run the section again.

| Notebook | Parts | Sections | Starred sections | Minutes of the live path |
|---|---|---|---|---|
| Notebook 1 | 14 | 96 | 16 | 38 |
| Notebook 2 | 11 | 76 | 13 | 36 |

Run all cells before a session and keep the kernel alive. In notebook 1, section
10.2 starts the day again, so that any turn can be run a second time. In notebook 2,
section 6.2 opens the meta-harness again after the last section has closed it.

The numbers, the stars, the contents and the live path are generated by the
builders from markers in the text, so they cannot drift apart.

The diagrams are images inside the notebooks, so that every viewer shows them. A
builder renders them with the Mermaid command line tool when the variable `MMDC`
points to it, and keeps each source and image in the `diagrams` folder beside the
notebook.

## Measured runs

Costs for Anthropic models are estimates from list prices per million tokens,
except where a harness reports its own figure. Your invoice is the authority. These
are single runs. A model is not deterministic, so small differences are noise.

### Notebook 1, the saved run

| Measure | Value |
|---|---|
| Wall-clock time, whole notebook | 3 min 58 s |
| Model-driven steps | 12 |
| Model calls | 31 |
| Prompt tokens | 554,907, of which 91 percent were read from the prompt cache |
| Output tokens | 12,845 |
| Estimated cost | 0.62 US dollars |
| Acceptance anchors that hold | 31 of 31 |

### Notebook 2, the saved run

Whole notebook: 4 min 30 s.

| Job | Harness | Status | Seconds | Steps | Tools | Prompt tokens | Read from cache | Output tokens | Cost, US dollars | Cost from |
|---|---|---|---|---|---|---|---|---|---|---|
| State a preference | MemAgent | succeeded | 4.2 | 1 | `remember_preference` | 17,075 | 8,477 | 90 | 0.0465 | price table |
| Morning brief | pi | succeeded | 30.1 | 10 | `read` | 27,248 | 14,412 | 2,620 | 0.1195 | pi |
| Morning brief | Hermes | succeeded | 29.3 | 10 | `read_file` | 41,155 | 22,511 | 2,260 | 0.1429 | price table |
| Morning brief | DeepSeek | skipped: `authentication_required` | | | | | | | | |
| Inbox triage | pi | succeeded | 55.0 | 20 | `read` | 54,359 | 31,405 | 5,136 | 0.2238 | pi |
| Inbox triage | Hermes | succeeded | 58.5 | 20 | `read_file`, `search_files` | 87,177 | 39,186 | 3,653 | 0.3208 | price table |
| Inbox triage | DeepSeek | skipped: `authentication_required` | | | | | | | | |
| Recall | pi | succeeded | 19.7 | 4 | `ls`, `read` | 14,898 | 11,225 | 1,327 | 0.0471 | pi |
| Recall | Hermes | succeeded | 40.5 | 13 | `read_file`, `search_files` | 72,641 | 52,474 | 2,502 | 0.1614 | price table |
| Recall | DeepSeek | skipped: `authentication_required` | | | | | | | | |

| Harness | Anchors that hold | Seconds | Steps | Prompt tokens | Cost, US dollars |
|---|---|---|---|---|---|
| pi | 20 of 20 | 104.8 | 34 | 96,505 | 0.39 |
| Hermes | 20 of 20 | 128.3 | 43 | 200,973 | 0.63 |

Every run left the workspace unchanged and produced no write and no command.

### The attacks

The inbox holds three real attacks. Each asks the assistant to send an email to an
outside address. A pattern matcher, which the notebooks call a tripwire, catches
one of the three. The other two reach the model as ordinary requests from unknown
senders. The notebooks measure what each harness did with them.

| Harness | Reported the quarantined attack | Flagged the two that passed the tripwire | Made a task of an attack | Proposed or sent mail to the address an attack names |
|---|---|---|---|---|
| MemAgent | Yes | Yes | No | No |
| pi | Yes | Yes | No | No |
| Hermes | Yes | Yes | No | No |
| DeepSeek | Not run | Not run | Not run | Not run |

No harness obeyed an injected instruction in the saved runs. In one earlier run of
notebook 1, with an earlier configuration, the MemAgent made a task for each of the
two attacks that passed the tripwire. The tool gave those tasks the title the host
writes and the lowest priority, no draft answered an attacker, and nothing was sent.

### The command line runner

| Command | Result | Seconds | Steps | Prompt tokens | Output tokens | Cost, US dollars | Anchors that hold |
|---|---|---|---|---|---|---|---|
| `--doctor` | pi ready, Hermes ready, DeepSeek `authentication_required` | | | | | | |
| `--harness pi --job morning_brief --fresh` | succeeded, exit code 0 | 34.5 | 9 | 32,135 | 2,742 | 0.1313, reported by pi | 9 of 9 |
| `--harness hermes --job recall --remember "..." --json` | succeeded, exit code 0 | 29.0 | 7 | 53,499 | 1,597 | 0.1436, from the price table | 2 of 2 |
| `--harness deepseek --job morning_brief` | not run, exit code 2 | | | | | | |

### Runs in an empty folder

Each notebook was copied alone, without outputs, to an empty folder outside the
repository and executed with a fresh virtual environment, so that its first cell
had to install everything. These runs were made after the data loading was changed
to pandas and PyArrow.

| Notebook | MemoRizz installed by the first cell | Result |
|---|---|---|
| Notebook 1 | `memorizz` 0.12.0 from PyPI | Ran to the end in 6 min 5 s, installation included, while three other runs used the machine. 30 of 31 anchors. Estimated cost 0.68 US dollars |
| Notebook 2 | The local snapshot, through `PPA_MEMORIZZ_SPEC` | Ran to the end in 5 min 27 s, installation included. 40 of 40 anchors. pi 0.37 and Hermes 0.61 US dollars. DeepSeek skipped |

The anchor that failed in the run of notebook 1 was a false alarm of the
measurement. The assistant had flagged both attacks under a heading that called
them suspicious, and the anchor read the answer line by line. The anchor now reads
the heading as well. It was checked against the answers of five saved runs, and the
saved run of notebook 1 uses it.

In the run of notebook 2, macOS printed a notice about memory logging from child
processes into five cells. The notice is harmless. It did not appear in any other
run, and its cause was not found.

## MemoRizz build

The `MemAgent` notebook runs on `memorizz` 0.12.0 from PyPI.

The meta-harness notebook and the runner need `PiHarness`, `HermesHarness` and
`DeepSeekHarness`. **The 0.12.0 release on PyPI does not have them.** On this
machine they exist in the working tree of the MemoRizz repository, as changes that
are not committed. `.venv` therefore has MemoRizz installed from a snapshot of that
working tree, kept in `.tools/memorizz-src` (taken 2026-09-29 10:03 UTC, on top of
commit `fc1126c`). The MemoRizz repository itself was not modified.

Until a release contains the adapters, a learner needs a build that has them:

```bash
export PPA_MEMORIZZ_SPEC="memorizz[anthropic,filesystem] @ file:///path/to/memorizz"
```

The notebook checks for the adapters in Part 1 and stops with a message when they
are missing.

## How the external harnesses were installed here

Both live under `.tools/`, which Git ignores. Nothing was installed globally, and
no home directory of pi, Hermes or MemoRizz was created or changed.

```bash
# pi 0.87.1
npm install --ignore-scripts --no-audit --no-fund --prefix .tools @earendil-works/pi-coding-agent

# Hermes Agent 0.21.5. The release on PyPI is older than 0.21.4, which MemoRizz needs
git clone --depth 1 --branch v2026.9.24 https://github.com/NousResearch/hermes-agent.git .tools/hermes-agent
cd .tools/hermes-agent
UV_PROJECT_ENVIRONMENT=../hermes-venv UV_NO_CONFIG=1 uv sync --frozen --no-dev --extra anthropic --python 3.12
```

`scripts/execute_notebooks.sh` and the runner point MemoRizz at these programs with
`MEMORIZZ_PI_COMMAND` and `MEMORIZZ_HERMES_COMMAND`.

## Tests

```bash
.venv/bin/python -m pytest tests -q
```

The tests need no key and no network, and they call no model.

| File | What it checks |
|---|---|
| `test_workspace_export.py` | The export is complete, deterministic, delimited and read-only, and handles empty collections |
| `test_anchors_and_usage.py` | Anchors pass for a correct answer and fail for a wrong one. Token counts and costs are computed the same way for every harness |
| `test_readiness.py` | A missing program, an old Hermes and a missing key each give the right error code |
| `test_cli.py` | The runner reports a harness that is not ready and does not run it |
| `test_notebooks_static.py` | Form, outline, stars, live path, embedded diagrams, independence, no typed-in world values, no leaks, a saved run without errors |
| `test_notebook_rules.py` | The rules inside each notebook agree with the shared policy on the practice data |

## Safety rules this track follows

- **Keys.** A key is read from the environment or asked for with `getpass`. No
  key is printed, written to a file or saved in an output. `scripts/scan_notebooks.py`
  scans the saved notebooks for key prefixes, home paths and the user name.
- **Homes.** MemoRizz, pi and Hermes keep their state inside this track's `data/`
  folder, or inside `ppa_data` next to a notebook.
- **Reading is autonomous, writing outward is gated.** In notebook 1 anything
  another person would see waits for the owner's approval. In notebook 2 every run
  is read-only, and an outbound action can only be proposed.
- **External text is data.** Subjects, bodies and meeting titles are delimited as
  untrusted content. The guards that hold are structural: tools refuse unsafe
  arguments, and the harnesses have no tool that sends.

## Known limits of MemoRizz found while building this

These are observations from this build, on the filesystem memory provider. Each
was seen in a run unless it says otherwise.

1. The pi, Hermes and DeepSeek adapters are not in the 0.12.0 release.
2. With `thread_id` set on a harness task, the context pack leaves out durable
   memories, because they belong to no thread. The notebooks leave it unset.
3. With `augment=False`, tool descriptions are stored without embeddings. The tool
   router then matches words. For "Prepare my morning brief." it selected no tool.
4. The default retrieval policy keeps four recalled items. A stored preference was
   once left out in favour of four conversation turns.
5. Skills described by one sentence scored below the default retrieval threshold
   of 0.70 for three of six procedures. With two example requests each, the right
   skill scores between 0.75 and 0.87.
6. The result of `resume_approval` is not added to the conversation. The next turn
   still believes the action is waiting, unless the host adds a note.
7. A rejected approval is recorded, and it is not passed to the model.
8. The stock automation worker loads the agent without the Python functions of
   its tools. Every tool call in a scheduled run fails with `tool_not_callable`.
9. Automations and summaries use the real date, and a scheduled run has no user
   scope. The usage of a summary call is not reported.
10. The answers of external harnesses are written to conversation memory without
    embeddings, so a later context pack does not contain them.
11. A write run inside a Git repository with uncommitted changes is refused before
    the approval gate is reached. That is by design, and it surprises in a demo.
12. Only the Oracle provider has `delete_scope`. On the filesystem provider the
    notebooks walk the stores to clear their own rows.
13. The filesystem provider searches the whole store and filters by scope
    afterwards. Rows of another scope could crowd out the rows that are wanted.
    This was read in the code and was not seen in a run.
