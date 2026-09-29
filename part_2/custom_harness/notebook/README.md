# PPA custom-harness notebook

`ppa_custom_complete.ipynb` builds a personal productivity assistant on a
custom agent harness, one layer at a time. It stands alone: every line of code
it runs is in a cell you can read, and it imports nothing from this
repository.

## What you need

| Requirement | Why | Required |
|---|---|---|
| Python 3.11 or newer | The notebook's code | Yes |
| Docker | Runs Oracle AI Database 26ai Free. The notebook starts it for you | Yes |
| `ANTHROPIC_API_KEY` | Claude, and memory extraction | Yes |
| `ORACLE_ADMIN_PASSWORD` | The SYS password of the workshop database. Choose any strong password on the first run | Yes |
| `TYPESAFE_API_KEY` | The System One model, Jev. Without it the harness uses rules and vector search | No |
| `TAVILY_API_KEY`, `E2B_API_KEY`, `LANGSMITH_API_KEY` | Web search, a code sandbox, traces | No |

No sign-in to a mail or calendar provider is needed. The notebook works on a
practice workspace that it builds from public data.

Give Docker at least 6 GB of memory. One Oracle database uses about 4 GB.
Three do not fit in 8 GB.

## Run it

```bash
cd part_2/custom_harness/notebook
python -m venv .venv && source .venv/bin/activate
python -m pip install -r requirements.txt

export ANTHROPIC_API_KEY=...
export ORACLE_ADMIN_PASSWORD=...
export TYPESAFE_API_KEY=...        # optional

jupyter lab ppa_custom_complete.ipynb
```

In VS Code, open the notebook and choose the environment above as its kernel.
A key that is not in the environment is asked for with a masked prompt.

The first run downloads the database image and one mailbox from Hugging Face.
Later runs reuse both.

## How it is organised

| Marker | Meaning |
|---|---|
| **Part N** | One layer of the harness. Parts are the top level of the outline |
| **N.M** | A numbered section inside a part |
| ⭐ | A section worth showing live |
| **What to watch** | The one thing to look for in the output |
| **Takeaways** | The last section of every part |

The notebook opens with the reference architecture, the list of components,
a table of contents and the live path. The live path lists only the starred
sections, with a time for each and the cell to start from when you want to run
a section again in front of a room.

Run every cell once before a session and keep the kernel alive. Later cells
use what earlier cells define.

## Diagrams

Every diagram is embedded in the notebook as an image, so it displays in
JupyterLab, VS Code, Colab and on GitHub. The `diagrams` folder holds the
source of each one beside its image: Mermaid text for most, and an HTML page
for the two that were drawn by hand.

To change a diagram in a notebook that still contains Mermaid blocks, edit the
block and run `python part_2/tools/notebook_diagrams.py <notebook>`. The tool
needs Node.js, `@mermaid-js/mermaid-cli` and Chrome.

## What it leaves behind

| Item | Where | How to remove it |
|---|---|---|
| The database container and its volume | Docker, `ppa-custom-oracle-26ai` | `docker rm -f ppa-custom-oracle-26ai` and `docker volume rm ppa-custom-oracle-26ai-data` |
| The downloaded mailbox and the MCP server file | `ppa_workspace/` beside the notebook | Delete the folder |
| Scheduled jobs in the workshop schema | The database | Set `PPA_KEEP_DATA=0` before running the cleanup cell |

The notebook never drops the schema, the container or the volume on its own.
