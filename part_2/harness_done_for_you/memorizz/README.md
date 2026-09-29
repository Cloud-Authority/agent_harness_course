# PPA on MemoRizz

PPA is a personal productivity assistant: it reads one person's mail and calendar,
decides what deserves attention, turns requests into tracked tasks, protects time
for focused work, and asks before anything leaves the building.

A **harness** is the code around a language model: it assembles the context, runs
the tools the model asks for, remembers what happened, and stops the model before
it does something irreversible. This folder builds PPA on **MemoRizz**, a harness
that somebody else built, using its native agent, `MemAgent`.

| Path | What it is |
|---|---|
| `assistant/notebook/ppa_memorizz_complete.ipynb` | The notebook, saved with the outputs of a real run |
| `assistant/notebook/README.md` | How to run it, what it costs and what it shows |
| `assistant/notebook/requirements.txt` | The packages it needs |

The notebook is standalone. It contains all the code it runs, loads its data from
Hugging Face, and imports nothing from this repository.

## What MemoRizz gives you, and what it does not

The notebook marks every building block of the assistant as built, partial or
missing, and repeats the table at the end with the evidence of the run.

| Building block | MemoRizz component | Status |
|---|---|---|
| Agent loop | `MemAgent` | Built |
| Long-term memory | Knowledge base in a memory provider | Built. The write tool is yours |
| Episodic memory | Conversation memory, recalled across threads | Built |
| Forgetting and decay | Scoped delete, summaries, a dry-run forgetting plan | Partial |
| Trusted tools | `Toolbox`, `governed_tool` | Built. The tools are yours |
| Tool disclosure | A router that matches tools to a request | Partial. It matched words, not meaning, on the filesystem provider |
| Governed definitions | none | Missing. Plain functions in the notebook |
| Skills | `Skillbox`, retrieved for each turn | Built. The procedures are yours |
| Approval gate | Durable single-use proposals | Built |
| Declined approval | `reject()` records it | Partial. The host tells the model |
| Action log | Tool outcomes and traces | Partial. The audit table is yours |
| Schedules | Automations with cron and one-shot jobs | Partial. The stock worker cannot run Python tools |
| Event triggers | none | Missing. A few lines of host code |
| Task list, focus log | none | Missing. A dictionary in the notebook |
| Untrusted content | Tool results are data by default | Partial. Delimiters and guards are yours |
