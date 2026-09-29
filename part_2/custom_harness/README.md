# Part 2 · Custom harness

PPA built explicitly, one layer at a time.

```text
people and time      owner · scheduled routines · event triggers · focus timers
control loop         assemble_context → call_model → dispatch_tools
                       → draft_effects → human_review → apply_effects → persist
models               System One decides · System Two reasons · embeddings in the database
database             state · governed meaning · memory · registries · time · evidence
connectors           three MCP servers behind an allowlist
systems of record    the practice workspace, or your own accounts
```

| Folder | What it is |
|---|---|
| [`notebook/`](notebook/) | The narrated build. It stands alone, on Oracle AI Database 26ai |
| [`appbook/`](appbook/) | The running assistant, with a chapter for each building block |

## Notebook

```bash
cd notebook
python -m pip install -r requirements.txt
export ANTHROPIC_API_KEY=... ORACLE_ADMIN_PASSWORD=...
jupyter lab ppa_custom_complete.ipynb
```

The notebook starts the database in Docker, builds the practice workspace from
public data, and runs a working week end to end. See
[`notebook/README.md`](notebook/README.md).

## Appbook

```bash
cd appbook
./run.sh          # http://127.0.0.1:8020
```

With no key the appbook answers from a scripted responder and nothing leaves
the machine. With `ANTHROPIC_API_KEY` it answers with Claude, and with
`TYPESAFE_API_KEY` System One screens mail and chooses evidence. It keeps its
state in Oracle AI Database when the database is running. See
[`appbook/README.md`](appbook/README.md).

## What differs between the two

| | Notebook | Appbook |
|---|---|---|
| Purpose | Read and run every line | Use the assistant, then open up its parts |
| Database | Oracle AI Database 26ai | Oracle AI Database 26ai when it answers, a local store when it does not |
| Memory | Oracle Agent Memory 26.8 | The appbook's own provider, with recall by keyword |
| System One | Four decisions, all in the loop | Two decisions in the loop, two measured in a lab |
| Workspace | Practice workspace only | Practice workspace, or your own accounts |
| Needs Docker | Yes | No |
