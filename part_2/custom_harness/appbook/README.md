# PPA custom-harness appbook

PPA is a personal productivity assistant. This appbook is its interactive form:
one working assistant over mail, calendar, notes and tasks, and fourteen
chapters that open up the building blocks it is made of. The chapters are the
teaching view of the same running system, not separate demonstrations.

**No lesson needs an account.** Every chapter and the whole assistant run on
the practice workspace, which is the default and needs no sign-in. Connecting
your own mail, calendar or notes is optional and is not part of any lesson.

The appbook is a FastAPI backend that serves a no-build, vanilla-JavaScript
page from the same origin. There is no npm and no frontend build. Every diagram
is drawn in the page as HTML and inline SVG, so none of them depends on a
diagram service or on the viewer.

## Run it

```bash
cd part_2/custom_harness/appbook
./run.sh
```

Open `http://127.0.0.1:8020`. `run.sh` uses `../.venv/bin/python` when that
environment exists, otherwise `python3`. To install the dependencies yourself:

```bash
python -m pip install -r requirements.txt
```

On start the appbook launches the workspace gateway
(`part_2/_shared/mcp/workspace_mcp_server.py`) as a subprocess on port 8941,
waits for `/health`, connects to its three MCP servers, and stops it again on
shutdown. If a healthy gateway with the same token already holds the port, the
appbook reuses it and leaves it running.

### With no credentials

Nothing to configure. The assistant works on the practice workspace, a public
mailbox with its clock pinned to one morning, and answers come from the
**scripted responder**: a deterministic stand-in that sits where the model
sits, routes a fixed set of requests to the same trusted tools and writes its
answers from their results. No model is called.

### With Claude

```bash
export ANTHROPIC_API_KEY=...      # or put it in the repository .env
./run.sh
```

Answers then come from `claude-opus-5-5` with adaptive thinking and automatic
tool choice. The header and every answer say which responder produced them:
"Claude claude-opus-5-5" or "scripted responder". Set `PPA_RESPONDER=scripted`
to keep the scripted responder even when a key is present.

A conversation that began on the scripted responder is not left there. Once a
key is present, Claude answers the next message of that conversation and reads
what was said before. The scripted responder leaves no thinking blocks behind,
so nothing earlier has to be rewritten.

### With your own accounts (optional, advanced)

No lesson asks for this. A provider can refuse or delay a connection: Google
asks an application to pass OAuth verification, and an administrator can
switch app passwords off. If a connection fails, nothing is stored and the
practice workspace stays in use.

Open the **Connections** chapter. It explains what is read, what can be
written, where credentials stay and what leaves the machine before any field
is shown. The connectors are folded away under "Optional, advanced".
Connecting any system moves the whole workspace to the real clock. Safe mode is
on by default: an approved message to anyone but you is held as a draft, and
an approved event is created without other attendees. Credentials go straight
to the gateway, which stores them in `data/ppa_home/connections.json`, readable
only by your user account. The appbook does not keep, log or return them.

### What leaves this machine

| Destination | When | What |
|---|---|---|
| Anthropic | Claude is the responder | The text the assistant reads, including mail it opens |
| Typesafe | `TYPESAFE_API_KEY` is set, so System One is on | The text being judged: the subject and body of each inbox message, the request, the candidate threads |
| Tavily | `TAVILY_API_KEY` is set and the model searches the web | The search words |
| LangSmith | The environment sets `LANGSMITH_TRACING=true` and a key | Every graph step, model call and tool result, mail text included |
| Google Fonts | The page is opened online | A request for two font families. Offline, system fonts are used |

The window on Oracle AI Database reads a database on this machine. Nothing it
reads leaves the machine.

LangChain and LangGraph do the tracing by themselves when the environment asks
for it; the appbook has no code that starts or stops it. The header shows a
"Tracing" chip while it is on, and the Connections chapter says so. The
appbook reads the repository `.env`, so a tracing switch set there for another
part of the course applies here too. Set `LANGSMITH_TRACING=false` before you
connect a real mailbox if you do not want its text traced.

## What is in it

| View | What it shows |
|---|---|
| Assistant | Chat with a live trace, inline approval cards, today's agenda, the governed task list, inbox triage, quick capture, the day plan, the running focus timer and armed jobs |
| 1. Architecture | Every component in eight lanes, each with a live status. Select one to read what it is, why the harness needs it, its technology and version, its tables, endpoints, tools and files. Trace one of four requests step by step. The ledger of what is built, partial and missing |
| 2. Connections | No sign-in needed. The practice workspace, what leaves the machine, safe mode, and the optional connectors |
| 3. Systems of record and MCP | Every tool the three servers offer beside the harness allowlist; a live read; tools that are never exposed |
| 4. Memory and the workday scratch pad | Long-term and episodic memory, quick capture, the day plan, end-of-day promotion with content-hash dedupe, forgetting |
| 5. Governed meaning | One question read naively and by definition: urgent, free, VIP, over-booked |
| 6. Inbox triage and task extraction | Governed signals and categories, tasks with a source link, duplicate suppression, quarantine |
| 7. Calendar intelligence | The two layers of the practice calendar, free slots, load, broken meeting rules, time-blocking, meeting prep |
| 8. Focus sessions | A Pomodoro runtime: start, stop, live countdown, parked distractions, session log |
| 9. Skills | Seven skills with progressive disclosure and the token comparison |
| 10. Approval gates and action log | Effect tiers, draft then approve or reject then execute, recipient risk, the untrusted-content wrapper, undo |
| 11. The loop | The LangGraph graph, the same conversation with its trace open, the assembled context, recent runs |
| 12. Timers and scheduled work | Every timer and scheduled job with a live countdown and its notification; schedules, event triggers, run now, simulate a working week |
| 13. Weekly review | Planned against done, where time went, what keeps slipping, what to drop |
| 14. System One | A second model that decides: attack screening, evidence, procedures and tools, each beside the rule it replaces, and what the decisions cost |

### The architecture view

`backend/core/architecture.py` holds one structure: lanes, components, edges,
request paths and the ledger. The diagram, the side panel and the stepper are
drawn from it, and a test checks that every component has a description, a
lane and a status check, and that every edge and path step names a component
that exists. The lanes, their names and their colours are those of the
notebook's reference architecture
(`part_2/custom_harness/notebook/diagrams/reference-architecture.html`), so
both show one picture. The components are what the appbook really runs. The
store is named as it is: Oracle AI Database when the appbook runs on it, the
local store when it does not. Recall is keyword overlap and says so.

`GET /api/architecture` returns the structure with a status on every
component. `GET /api/architecture/status` returns statuses only. A status is
the result of a check made for that request:

| Status | Meaning |
|---|---|
| Connected | Checked just now and working |
| Configured | Set up. It is exercised on its next use |
| Fallback | A stand-in is doing this job |
| Off | Switched off, or not in use at the moment |
| Not configured | Needs a key or a connection |
| Failing | The last check failed |

Keys are reported only as configured or not. No value is returned.

### The practice calendar

The practice calendar has two layers, and each event names its own in
`source`, shown as a small badge wherever events are listed.

- `invitation`: derived from an invitation that arrived by mail.
- `generated`: a working session placed by rule. For each week, the threads
  the owner wrote on most in the fortnight before get one session each, in a
  fixed weekly pattern. The owner is the only attendee, and a session that
  overlaps an invitation is dropped.

The rule lives in `part_2/_shared/workspace/generated.py`. The appbook turns
the generated layer on by setting `PPA_GENERATED_CALENDAR=1` for the gateway
it launches. Set `PPA_GENERATED_CALENDAR=0` to see invitations only. Events
are read through MCP and are not harness state, so the data explorer has no
table of events.

What the assistant writes to the practice workspace (drafts, sent mail, events,
answers to invitations, pages) is kept in `practice_state.json` under
`PPA_DATA_DIR`, with the ledger of effects beside it. An approved event is
therefore still on the calendar after the appbook is started again. A reset
empties both files.

The **data explorer** is docked under every chapter. It lists every table the
harness owns, grouped by the part of the harness it belongs to, and it is
read-only: a fixed allowlist of tables, bound parameters, no query text from
the browser, at most 100 rows a page. Long text, JSON and binary cells are cut
short in the grid; selecting a row shows every value in full, and LangGraph
checkpoint blobs are decoded for reading. A table that the assistant writes to
is marked, counts its new writes and refreshes in place, so state can be
watched appearing in tables that started empty.

### The window on Oracle AI Database

The data explorer has two sources. **Appbook store** shows the appbook's own
tables, wherever they live. **Oracle AI Database** opens a read-only window on
the schema the custom-harness notebook runs on, so a learner who has run the
notebook can see what its harness left there:

- the harness tables and the governed views;
- the LangGraph checkpoint tables that `OracleSaver` writes;
- the Oracle Agent Memory tables, found by their store prefix;
- the scheduler jobs, from `USER_SCHEDULER_JOBS`;
- the embedding model inside the database, from `USER_MINING_MODELS`;
- the tables the database maintains for its text index, vector index and model.

What exists is discovered from the data dictionary and never assumed. Each
object shows its row count, its columns with their types, and its newest 50
rows. A `VECTOR` shows its dimension and first numbers. A large object shows
its length and first 200 characters and is never fetched whole.

The window cannot write. Every connection opens a read-only transaction, every
statement is a `SELECT`, identifiers are built only from names the data
dictionary returned, and values are bound. Each answer has a fixed time to
spend, so a busy database gives a plain "try again" and never a hanging page.

When the database cannot be reached, the window says so in one sentence and
says how to get it: run the custom-harness notebook, which starts the
database. The appbook's own store is a separate matter, described under
"Where the state lives".

## The loop

```text
assemble_context -> call_model -> dispatch_tools -> call_model ... -> persist
                                      |
                                      +-> draft_effects -> human_review -> apply_effects -> call_model
```

- Automatic tools run inside `dispatch_tools`. A gated tool is drafted, and
  `human_review` pauses the run with `interrupt()`. The decision resumes the
  same run with `Command(resume=...)` from its checkpoint, also after a restart.
- A rejected action returns to the model as a tool result that says the owner
  declined, so it adapts instead of retrying.
- The context is append-only. The system prompt and the tool list are fixed
  for the life of a conversation. Clock, memory, governed definitions and skill
  manifests travel in the first user message of each turn.
- The responder is fixed for the life of a conversation too, with one
  exception: Claude takes over a conversation that began on the scripted
  responder.
- Scheduled routines and event triggers enter through `agent.run`, the same
  boundary as a typed request. The Pomodoro end-of-session summary always uses
  the scripted responder, so a timer reports on time.

## What is built, partial and missing

### Where the state lives

The appbook keeps its state in **Oracle AI Database** when the database
answers, and in a **local store** when it does not. Either way the tables are
the same: the `ppa_*` tables, a promotion queue, an automation queue, the
decision log and LangGraph's checkpoints.

| Substrate | When | Where |
|---|---|---|
| Oracle AI Database | The database at `PPA_APPBOOK_ORA_DSN` answers | One schema for each owner, `PPA_APP_<owner>`, beside the notebook's schema and never inside it. Checkpoints use LangGraph's `AsyncOracleSaver` |
| Local store | No database answers, or `PPA_SUBSTRATE=local` | One file for each owner under `PPA_DATA_DIR` |

`PPA_SUBSTRATE` chooses: `oracle`, `local` or `auto`, which is the default and
takes Oracle when it is reachable. The label shown in every chapter comes from
one place, `store.SUBSTRATE`, and it names what is really in use.

The first start on Oracle creates the owner's schema, which needs the database
administrator's password once, in `ORACLE_ADMIN_PASSWORD`. Later starts do not
need it. The easiest way to get the database is to run the custom-harness
notebook, which starts it.

Every module writes one small dialect of SQL. `backend/core/oracle_store.py`
runs that dialect on Oracle: it creates the tables, rewrites the few statements
Oracle spells differently (an upsert, `LIMIT`, the order of insertion), and
returns rows the callers expect. Oracle stores an empty string as `NULL`, so a
text column that was declared `NOT NULL` reads back as an empty string.

Long-term memory is still the appbook's own provider, with recall by keyword
overlap. Oracle Agent Memory is used in the notebook.
`backend/core/memory.py` holds the provider interface; another provider plugs
in through `build_provider`.

### System One

Chapter 14 adds a second model. Claude reasons. **System One**, which is Jev
from Typesafe, decides: it answers a closed question with a probability, in
about a third of a second, and it takes no action.

| Decision | In the running assistant | Without `TYPESAFE_API_KEY` |
|---|---|---|
| Is this email an attack? | Yes. Inbox triage uses it beside the tripwire | The pattern tripwire alone |
| Which evidence is worth reading? | Yes. Meeting preparation keeps at most three threads, or none | The first three in the order of the search |
| Which procedure applies? | Lab only | Keyword overlap |
| Which tools does the request need? | Lab only | Every tool is offered |

The assistant still offers every tool on every turn. A tool list that never
changes keeps the prompt prefix stable, so the prefix stays cached and earlier
reasoning stays valid. The notebook shows the other choice.

Every call is written to `ppa_decision_log` with its time and its tokens. The
key is read from the environment and no endpoint returns it.

### What is built

| Status | Components |
|---|---|
| Built | Oracle AI Database as the store, with LangGraph's `AsyncOracleSaver` for checkpoints; System One for attack screening and evidence (needs a key); a read-only window on the notebook's Oracle AI Database; LangGraph loop; scripted responder; Claude adapter (needs a key); append-only context; MCP reads and writes through the gateway; allowlist and effect tiers; approval interrupt and resume; action log with approval and delivery kept apart; untrusted-content wrapper; recipient risk; tasks; calendar intelligence; focus runtime; persistent scheduler; schedules and event triggers; scratch pad and promotion; forgetting; web search through Tavily (needs a key); prompt caching (needs a key); data explorer; interactive architecture |
| Partial | Long-term memory recalls by keyword overlap, not by vector search, and there is no embedding model. Skills are ranked by keyword overlap. Episodes are computed summaries of the day, not model-written. The injection tripwire has low recall and is shown as such. Trace steps stream while a turn runs; the answer text arrives whole. Traces are exported only by the libraries, when the environment asks |
| Missing | Oracle Agent Memory as the memory provider. Multi-agent orchestration; a code sandbox; accounts and sign-in |
| Left out by design | A semantic answer cache. Mail, calendar and tasks change outside the database, so a cached answer would be stale |

Harness-owned state starts empty. Tasks appear when triage extracts them, focus
sessions when timers run, memories when the owner states a preference. Nothing
is seeded. State is kept for each workspace owner, in a schema or a file of
its own, so a practice run never mixes with a real account.

## Environment variables

| Variable | Default | Purpose |
|---|---|---|
| `ANTHROPIC_API_KEY` | none | Enables Claude as the responder |
| `ANTHROPIC_MODEL` | `claude-opus-5-5` | Model name |
| `PPA_EFFORT` | `medium` | Effort level passed to the model |
| `PPA_RESPONDER` | `auto` | `scripted` forces the scripted responder |
| `TAVILY_API_KEY` | none | Enables the `web_search` tool. Without it the tool answers "not configured" |
| `LANGSMITH_TRACING`, `LANGSMITH_API_KEY` | none | Read by LangChain, not by the appbook. When set, traces are sent to LangSmith |
| `PPA_GENERATED_CALENDAR` | `1` | The generated layer of the practice calendar. `0` shows invitations only |
| `TYPESAFE_API_KEY` | none | Switches System One on |
| `PPA_SYSTEM_ONE` | `on` | `off` keeps System One off even when a key is set |
| `PPA_SYSTEM_ONE_MODEL` | `jev-1.13.0` | The System One model |
| `PPA_SUBSTRATE` | `auto` | `oracle`, `local`, or `auto`: Oracle when it is reachable |
| `PPA_APPBOOK_ORA_DSN` | `127.0.0.1:1524/FREEPDB1` | The database that holds the appbook's own tables |
| `PPA_APPBOOK_ORA_USER` | `PPA_APP` | The prefix of the appbook's schemas |
| `PPA_APPBOOK_ORA_PWD` | a workshop default | The password of those schemas |
| `ORACLE_ADMIN_PASSWORD` | none | Needed once, to create a schema that does not exist yet |
| `PPA_ORA_DSN` | `127.0.0.1:1524/FREEPDB1` | The notebook's Oracle AI Database, for the read-only window |
| `PPA_ORA_USER` | `PPA_AGENT` | The notebook's database user |
| `PPA_ORA_PWD` | the notebook's workshop default | Its password. No endpoint returns it |
| `PPA_MCP_TOKEN` | `workshop-token` | Bearer token shared with the gateway |
| `PPA_MCP_PORT` | `8941` | Gateway port |
| `PPA_DATA_DIR` | `./data` | The local store's files, the gateway log, the gateway home and what was written to the practice workspace |
| `PPA_PRACTICE_STATE` | `<data>/practice_state.json` | Where the gateway keeps what was written to the practice workspace |
| `PPA_HOME` | `<data>/ppa_home` | Where the gateway keeps its connection store |
| `PPA_PRACTICE_NOW` | set by the practice data | Practice clock at start, read by the gateway |
| `PPA_SAFE_MODE` | `1` | Safe mode at start, read by the gateway |
| `PPA_GRAPH_MAX_ITERATIONS` | `12` | Model calls allowed in one turn |
| `PPA_MODEL_TIMEOUT_SECONDS` | `240` | Timeout for one model call |
| `PPA_TRIGGER_POLL_SECONDS` | `60` | How often event triggers are checked |
| `PPA_SCHEDULER_POLL_SECONDS` | `0.5` | How often the scheduler looks for due jobs |
| `PPA_TRIAGE_WINDOW` | `25` | Newest inbox threads read for triage, at most 50 |
| `HOST`, `PORT` | `127.0.0.1`, `8020` | Where `run.sh` listens |

Keys are read from the process environment, then from the repository `.env`,
then from `appbook/.env`. Both files are ignored by git.

## Ports

| Port | Used by |
|---|---|
| 8020 | The appbook |
| 8941 | The workspace gateway: `/mail/mcp`, `/calendar/mcp`, `/notes/mcp`, `/health`, `/admin/*` |
| 1524 | Oracle AI Database. The appbook does not start it. When it is there, the appbook keeps its state in it and opens the read-only window on the notebook's schema |

## The clock

The practice workspace pins the clock, and the gateway replays the mailbox
against it: moving the clock forward makes mail arrive and meetings get
announced. Set it from the header. Scheduled routines fire when the clock
reaches their time; one missed by more than 30 minutes is skipped, not
replayed. With a real account connected nothing is pinned and the real clock
applies. Focus timers always use the real clock, because a real job has to
fire.

## Tests

```bash
# from the repository root, offline, on the local store, about 40 seconds
part_2/custom_harness/.venv/bin/python -m pytest part_2/custom_harness/appbook/tests -q

# the same suite on Oracle AI Database, about 3 minutes
PPA_TEST_SUBSTRATE=oracle part_2/custom_harness/.venv/bin/python -m pytest part_2/custom_harness/appbook/tests -q
```

On Oracle the suite uses schemas of its own, `PPA_TEST_<owner>`, and empties
them. It never touches the schema the appbook runs on. No test calls System
One: a stand-in answers, so that the rules around the answer are what is
tested.

The tests use the scripted responder, FastAPI's `TestClient` and a gateway
subprocess on a free port, with all state in a temporary folder and tracing
switched off. The practice workspace is a real mailbox, so no test names a
thread, a person or an event: each states a rule and checks it against
whatever the workspace holds.

`tests/live_check.py` is not collected by pytest. It runs the five canonical
turns against a running appbook, prints latency and token counts, and checks
the same anchors. With a key on the server it calls Claude and costs tokens.

```bash
./run.sh                                   # in one terminal
../.venv/bin/python tests/live_check.py --reset --focus-seconds 5
```

## Troubleshooting

| Symptom | Cause and fix |
|---|---|
| The header stays on "Warming harness" | The gateway did not start. Read `data/gateway.log`. The practice data file `part_2/_shared/data/practice_slice.json.gz` must exist |
| "A gateway is running on this port with a different token" | Another gateway holds port 8941. Stop it, or set `PPA_MCP_PORT` and `PPA_MCP_TOKEN` to match it |
| `Address already in use` on 8020 | Run `PORT=8021 ./run.sh` |
| Answers come from the scripted responder | `ANTHROPIC_API_KEY` is not set in the shell that ran `run.sh` or in `.env`, or `PPA_RESPONDER=scripted` is set. The Architecture chapter shows which. The key is read at start, so start the appbook again after you set it |
| A chapter shows "Not Found" after an update | The page is newer than the running backend. Stop the appbook and run `./run.sh` again |
| The page looks older than the code | The pages are served with `Cache-Control: no-cache`, so a reload is enough. A copy a browser kept from before that change needs one hard reload |
| A conversation answers "waiting for a decision" | A drafted action is pending. Decide it in the chat or in chapter 10, or start a new conversation |
| A scheduled routine did not fire | On the practice clock, routines fire when you move the clock to their time. Chapter 12 has "Run now" and the clock presets |
| No browser notification | Allow notifications for the page in chapter 12. The in-page toast appears either way |
| The calendar shows only one or two meetings | `PPA_GENERATED_CALENDAR=0` is set, or an older gateway holds the port. Stop it and start the appbook again |
| The Oracle source says "not reachable" | The notebook's database is not running. Run the custom-harness notebook, which starts it, then press "Try again" |
| The Oracle source says the database is busy | The notebook is using it. Each answer has nine seconds to spend; press "Try again" |
| Start again from empty | `curl -X POST localhost:8020/api/reset -H 'Content-Type: application/json' -d '{"confirm":"reset"}'`. It empties the harness tables, the checkpoints and what was written to the practice workspace. On the local store, stopping the appbook and deleting `data/` does the same |
