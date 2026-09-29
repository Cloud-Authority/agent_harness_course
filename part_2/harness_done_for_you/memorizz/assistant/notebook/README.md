# `ppa_memorizz_complete.ipynb`

A personal productivity assistant (PPA) built on MemoRizz's native agent,
`MemAgent`, in one standalone notebook. It is saved with the outputs of a real run.

## Run it

The notebook needs nothing from this repository. Copy the one file to an empty
folder and run it top to bottom.

```bash
python -m venv .venv && . .venv/bin/activate
pip install ipykernel nbconvert jupyterlab
export ANTHROPIC_API_KEY=...            # or let the notebook ask for it with getpass
ollama pull nomic-embed-text            # optional: about 270 MB, enables semantic recall
jupyter lab ppa_memorizz_complete.ipynb
```

The first code cell installs `memorizz[anthropic,filesystem]`, `pandas`, `pyarrow`
and `huggingface_hub` with `%pip`. The notebook then loads one public mailbox from
the Enron corpus and three real prompt-injection emails from Microsoft's
LLMail-Inject challenge, both pinned by dataset revision. pandas reads the mailbox
straight from Hugging Face and keeps a copy in the state folder, so a second run
downloads nothing.

No lesson needs a sign-in to a mail or calendar provider. The only credential is
the key of the model provider.

To execute it from a shell and keep the outputs:

```bash
jupyter nbconvert --to notebook --execute --inplace ppa_memorizz_complete.ipynb
```

## Settings

All settings are environment variables. None is required except the key.

| Variable | Default | Meaning |
|---|---|---|
| `ANTHROPIC_API_KEY` | asked with `getpass` | The model key. It is never printed |
| `PPA_MODEL` | `claude-opus-5-5` | The model. `claude-sonnet-5-5` and `claude-haiku-4-5` are in the price table |
| `PPA_EFFORT` | `medium` | How hard the model is asked to think |
| `PPA_HOME` | `ppa_data`, next to the notebook | Where memory, the agent and the state file are kept |
| `PPA_MEMORY_ID` | `ppa-workshop` | The memory workspace. A rerun clears only this scope |
| `PPA_EMBEDDING_MODEL` | `nomic-embed-text` | The Ollama embedding model |
| `OLLAMA_HOST` | `http://127.0.0.1:11434` | Where Ollama listens |
| `PPA_MEMORY_BACKEND` | `filesystem` | `oracle` uses Oracle AI Database. Not run for this notebook |
| `PPA_POMODORO_SECONDS` | `5` | The workshop length of a focus session |

`MEMORIZZ_HOME` and `MEMORIZZ_MEMORY_ROOT` are set by the notebook to folders inside
`PPA_HOME`, before MemoRizz is imported. A MemoRizz home in your home directory is
not read or written.

## What it shows

| Part | Subject |
|---|---|
| 1 | Environment: packages, state folder, key, model |
| 2 | The world, from real data: mailbox, owner, threads, attacks, inbox |
| 3 | Governed definitions: contacts, VIPs, calendar, tripwire, triage, free slots, time blocks |
| 4 | Harness-owned state: tasks, drafts, focus log, audit. It starts empty |
| 5 | Memory: provider, embeddings, scope |
| 6 | Trusted tools in three effect tiers, with guards |
| 7 | Instruction, persona and skills |
| 8 | Assembling the harness, and three context decisions |
| 9 | The host side of an approval, and measurement |
| 10 | Five turns of one working day, with acceptance anchors |
| 11 | Proactive behaviour: schedules and event triggers |
| 12 | Safety and control: the attacks, a declined approval, the action log |
| 13 | Forgetting and decay |
| 14 | What the day cost, every anchor, and the component map with evidence |

Every part closes with its takeaways. Sections are numbered `N.M`, and 16 of them
carry a star: they are the ones to show live, and together they take about 38
minutes. The notebook opens with its contents and with the live path, which says for
every starred section what to show and where to start to run it again.

Run all cells before a session and keep the kernel alive. Section 10.2 starts the
day again: run it, then the turns in order, to show any turn a second time.

## The saved run

Measured on 2026-09-29 with `claude-opus-5-5`, effort `medium`, the filesystem
memory provider and `nomic-embed-text` embeddings. Costs are estimates from list
prices per million tokens. Your invoice is the authority.

| Measure | Value |
|---|---|
| Wall-clock time for the whole notebook | 3 min 58 s |
| Model-driven steps | 12 |
| Model calls | 31 |
| Prompt tokens | 554,907, of which 91 percent were read from the prompt cache |
| Output tokens | 12,845 |
| Estimated cost | 0.62 US dollars |
| Acceptance anchors that hold | 31 of 31 |

| Step | Seconds | Model calls | Tool calls | Estimated cost, US dollars |
|---|---|---|---|---|
| 1 Morning brief | 14.9 | 2 | 3 | 0.0518 |
| 2 Triage and tasks | 39.1 | 4 | 21 | 0.1925 |
| 3 Time-blocking, approved | 16.2 | 4 | 3 | 0.0466 |
| 4 Focus and preference | 14.2 | 3 | 3 | 0.0373 |
| 5 Recall in a new session | 13.8 | 2 | 3 | 0.0419 |
| Scheduled job: focus session ends | 3.5 | 2 | 1 | 0.0176 |
| Scheduled job: weekly review | 11.9 | 3 | 2 | 0.0374 |
| Event trigger: meeting prep | 11.8 | 3 | 4 | 0.0617 |
| Declined approval: the request | 6.1 | 2 | 1 | 0.0289 |
| Declined approval: the model adapts | 11.5 | 1 | 0 | 0.0351 |
| Forget a preference | 17.5 | 3 | 2 | 0.0289 |
| Recall after forgetting | 17.3 | 2 | 3 | 0.0380 |

One model call is outside this table: the summary in Part 13 is made by MemoRizz
outside a turn, and its usage is not reported to the notebook.

A model is not deterministic. A second run gives different wording, slightly
different numbers, and sometimes a different decision. With its final configuration
the notebook was run six times in full. All 31 anchors held in five of the runs. In
the sixth run one anchor failed, and the fault was in the measurement: the
assistant had flagged both attacks under a heading that called them suspicious, and
the anchor read the answer line by line. The anchor now reads the heading as well,
and the saved run uses it.

In one earlier run, with an earlier configuration, the assistant made a task for
each of the two attack emails that the tripwire missed. The tasks had the title
the host writes and the lowest priority, no draft answered an attacker, and nothing
was sent.

The notebook was also copied alone to an empty folder and executed with a fresh
virtual environment and `memorizz` 0.12.0 from PyPI. It ran to the end in 6 min
5 s, installation included, while three other runs used the machine.

## What to know before teaching from it

- **The attacks.** The tripwire catches one of the three real attacks. The other
  two reach the model as ordinary requests from unknown senders. In every run the
  assistant reported them as suspicious, sent nothing and drafted nothing to the
  address the attacks name.
- **Tool disclosure is off.** MemoRizz can offer the model only the tools that match
  a request. With `augment=False` on the filesystem provider the tool descriptions
  are stored without embeddings, so the router matches words. For the first request
  of the day it found no tool. The notebook offers every tool on every call and
  shows the router's preview as evidence.
- **Recall budget.** The default retrieval policy keeps four recalled items. In one
  rehearsal all four were conversation turns and the stored preference was not among
  them. The notebook keeps every candidate (`max_items=10`).
- **Scheduled jobs run in the notebook.** MemoRizz's stock worker loads the agent
  from storage without the Python functions of the tools, so every tool call in a
  scheduled run fails with `tool_not_callable`. The notebook claims the due jobs
  from MemoRizz's store and runs them with the live agent.
- **Schedules use the real clock.** The scenario is pinned to a morning in 2001.
  The next run of a routine is computed from today's date.
- **The summary knows the real date.** The summary in Part 13 is written by a model
  call that does not receive the assistant's instruction, so it may mention today's
  date instead of the scenario's.
