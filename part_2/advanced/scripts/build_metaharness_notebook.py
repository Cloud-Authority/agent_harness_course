"""Build metaharness/notebook/advanced_metaharness_memorizz.ipynb.

    python part_2/advanced/scripts/build_metaharness_notebook.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from notebook_kit import build, code, lift, md, part  # noqa: E402

ADVANCED = Path(__file__).resolve().parents[1]
SHARED = ADVANCED / "shared"
OUT = ADVANCED / "metaharness" / "notebook" / "advanced_metaharness_memorizz.ipynb"
DIAGRAMS = ADVANCED / "metaharness" / "notebook" / "diagrams"

LEAD = """
A **harness** runs one model on one task: it assembles the context, runs the tools, keeps
the state and stops the model before it does harm. A **meta-harness** sits one level up.
It does not replace the vendor's agent loop; it puts a stable host contract around several
harnesses and normalises what goes in and what comes out: the task, the permissions, the
memory, the events, the result, the approval and the evidence. One control plane, many
agents.

MemoRizz implements one. This notebook reads that implementation, module by module, from
the MemoRizz source on this machine, and then runs it: one read-only task on Claude Code,
a three-stage plan in which **pi plans, Codex implements behind an approval, and Claude
Code reviews**, and a comparison that puts the same question to two harnesses at once.
Memory, the run ledger and the approval queue live in Oracle AI Database.

The use case follows Part 2. The trip-booking workflow's booking ledger has a defect: a
booking that was cancelled is replayed as if it were still confirmed. The maintainers
hand that fix to a meta-harness, and the meta-harness hands the work to three different
coding agents while keeping every decision, every event and every approval in one place.

| Concern | Where MemoRizz puts it | Read in |
|---|---|---|
| The contract a task must meet | `metaharness/models.py` | Part 2 |
| One adapter per harness, one event stream | `metaharness/base.py`, `adapters.py` | Part 3 |
| Workspace roots, child environment, redaction, routing | `security.py`, `router.py` | Part 4 |
| Memory into a bounded context pack | `context.py` | Part 5 |
| Durable runs, events and approvals | `store.py`, `approval.py`, and this notebook's Oracle stores | Part 6 |
| The run sequence and the approval gate | `service.py` | Parts 7 and 8 |
| Staged plans, handoffs and comparisons | `service.py`, `handoff.py`, `requests.py` | Part 9 |

**Which MemoRizz.** The notebook imports MemoRizz from the checkout named by
`MEMORIZZ_SRC` when that variable is set, and from the installed package otherwise. One
variable moves it from the development source to the published release.
"""

ARCHITECTURE = """
```mermaid
flowchart TB
  P[Maintainer] -->|task, plan| M[MemoRizz MetaHarness]
  M --> X[HarnessContextBuilder<br/>memory → context pack]
  M --> R[HarnessRouter<br/>which harness is ready]
  M --> S[security<br/>workspace roots · child env · redaction]
  M --> A{{Approval store<br/>edits wait for a person}}
  M --> C1[Claude Code]
  M --> C2[Codex]
  M --> C3[pi]
  M --> C4[Hermes]
  C1 & C2 & C3 & C4 --> E[Normalised events<br/>messages · tools · commands · files · usage]
  E --> V[Host verification<br/>python -m pytest -q]
  M --> O[(Oracle AI Database<br/>memory · runs · events · approvals · orchestrations)]
  E --> O
```
"""

SEQUENCE = """
```mermaid
sequenceDiagram
  participant H as Host (this notebook)
  participant M as MetaHarness
  participant O as Oracle AI Database
  participant A as Adapter (subprocess)
  H->>M: run(HarnessTask)
  M->>O: retrieve memory → context pack
  M->>M: route: which harness, is it ready
  M->>O: create run (queued)
  alt edits, network, secrets or governed writes
    M->>O: propose approval, run pending_approval
    H->>M: approve + resume
  end
  M->>A: build command, minimal child environment, workspace lease
  A-->>M: stream → normalised events
  M->>O: append every event
  M->>M: verification command on the host
  M->>O: result, diff, fingerprints, usage, cost
  M->>O: handoff to conversation memory
```
"""

PARTS = [
    part("Environment", """
The notebook needs Python 3.11 or newer, Oracle AI Database in Docker, an Anthropic key,
and at least one coding agent on the machine. Codex uses its own login; pi and Hermes are
installed by the done-for-you track under `part_2/harness_done_for_you/.tools`.
""",
         md("### Which MemoRizz\n\n`MEMORIZZ_SRC` names a checkout. When it is set, that source is imported; when it is not, the installed package is. The provenance line says which one is live."),
         code('''from __future__ import annotations

import inspect, json, logging, os, re, shutil, subprocess, sys, textwrap, time, uuid, warnings
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from getpass import getpass
from pathlib import Path
from typing import Any, Dict, Optional

import oracledb, requests
oracledb.defaults.fetch_lobs = False

MEMORIZZ_SRC = os.path.expanduser(os.getenv("MEMORIZZ_SRC", "~/Desktop/memorizz/src"))
if Path(MEMORIZZ_SRC, "memorizz").is_dir():
    sys.path.insert(0, MEMORIZZ_SRC)
logging.getLogger().setLevel(logging.ERROR)
warnings.filterwarnings("ignore")

import memorizz
from importlib.metadata import version as installed_version
source = Path(memorizz.__file__).resolve()
checkout = source.parents[2] if "site-packages" not in str(source) else None
commit = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=checkout, capture_output=True, text=True).stdout.strip() if checkout else ""
print("memorizz", getattr(memorizz, "__version__", installed_version("memorizz")), "from",
      str(source.parent).replace(str(Path.home()), "~"))
print("development checkout at commit", commit if commit else "— installed package")'''),
         md("### Keys and the coding agents\n\nOnly the Anthropic key is asked for. Codex is used with its own login. pi and Hermes are pointed at the done-for-you track's installs; a machine without them still runs the Claude Code parts."),
         code('''def secret(name: str, prompt: str) -> str:
    value = os.getenv(name, "").strip() or getpass(prompt).strip()
    if not value:
        raise RuntimeError(f"{name} is required for this notebook.")
    os.environ[name] = value
    return value

secret("ANTHROPIC_API_KEY", "Anthropic API key: ")
TOOLS = Path("../../../harness_done_for_you/.tools").resolve()
os.environ.setdefault("MEMORIZZ_PI_COMMAND", str(TOOLS / "node_modules" / ".bin" / "pi"))
os.environ.setdefault("MEMORIZZ_HERMES_COMMAND", str(TOOLS / "hermes-venv" / "bin" / "hermes"))
print({"pi": Path(os.environ["MEMORIZZ_PI_COMMAND"]).exists(), "hermes": Path(os.environ["MEMORIZZ_HERMES_COMMAND"]).exists()})'''),
         md("### Oracle AI Database\n\nThe same schema the other Part 2 advanced lessons use, created through the container's operating-system authentication when it is missing."),
         code(lift(SHARED / "oracle.py", "ALREADY_THERE", "GRANTS", "POOL", "OracleConfig", "ORA", "_pools")),
         code(lift(SHARED / "oracle.py", "reachable", "_container_running", "admin_sql")),
         code(lift(SHARED / "oracle.py", "ensure_schema", "pool", "_patient", "rows", "execute")),
         code('''print(ensure_schema(), "| reachable:", reachable())
print(rows("SELECT version_full AS v FROM product_component_version FETCH FIRST 1 ROW ONLY")[0]["v"])'''),
         md("### A helper that shows source\n\nThe rest of the notebook reads MemoRizz's code as it is on this machine. `show` prints a numbered excerpt of a function or class, from its first line, so what is read is what runs."),
         code('''def show(target, first: int = 1, count: int = 40, find: str | None = None) -> None:
    """Print `count` lines of `target`'s source, starting at line `first`, or at the first line that contains `find`."""
    lines, start = inspect.getsourcelines(target)
    if find is not None:
        first = next((n + 1 for n, line in enumerate(lines) if find in line), 1)
    name = getattr(target, "__qualname__", getattr(target, "__name__", str(target)))
    print(f"# {inspect.getsourcefile(target).split('memorizz/')[-1]} :: {name}  (lines {start + first - 1}–{start + min(first - 1 + count, len(lines)) - 1})")
    for n, line in enumerate(lines[first - 1:first - 1 + count], start=start + first - 1):
        print(f"{n:>5}  {line.rstrip()}")'''),
         ),
    part("The contract", """
Everything a harness receives and returns is a dataclass in `models.py`. A task names the
work, the workspace, the harness, the memory scope, the permissions, the budget and the
verification. A result carries the answer, the events' summary, the diff, the workspace
fingerprints before and after, usage, cost and the routing decision. Because every adapter
speaks these types, the host can compare harnesses and keep one ledger.
""",
         md("### HarnessTask, HarnessPermissions, VerificationSpec, HarnessBudget"),
         code('''from memorizz import HarnessPermissions, HarnessTask, VerificationSpec
from memorizz.metaharness.models import HarnessBudget, HarnessResult, HarnessStatus

show(HarnessTask, count=46)'''),
         code('''show(HarnessPermissions, count=32)'''),
         code('''show(VerificationSpec, count=18)
print()
show(HarnessBudget, count=20)'''),
         md("### The states a run can be in, and what a result carries"),
         code('''show(HarnessStatus, count=22)
print()
show(HarnessResult, count=26)'''),
         md("### One task, as the host writes it\n\nRead-only, no network, read-only MCP, a verification command that the host runs itself. The dictionary form is what the JSON API and the CLI send."),
         code('''WORKSPACE = Path("~/.ppa_workshop/metaharness-workspace").expanduser()
MEMORY = "tripbook-" + uuid.uuid4().hex[:6]      # one memory scope for this run of the notebook
task = HarnessTask(
    task="Read tripbook/ledger.py and the tests. Report likely defects in the idempotency rules, in three short bullets. Do not edit files.",
    workspace=str(WORKSPACE), harness="claude-code", memory_id=MEMORY, user_id="richmond", thread_id="ledger-review",
    permissions=HarnessPermissions(workspace_mode="read_only", network="none", mcp_access="read_only"),
    verification=VerificationSpec(command="python -m pytest -q"))
print(json.dumps(task.to_dict(), indent=1, default=str).replace(str(Path.home()), "~")[:1200])'''),
         ),
    part("Adapters and the event stream", """
An adapter wraps one vendor CLI. `AgentHarness` is the contract: `probe` says whether the
harness is ready, `run` executes a task and returns an outcome, `cancel` stops a run.
`SubprocessHarness` does the shared work: it builds the command, starts the child with a
minimal environment, reads its output stream and turns each vendor-specific line into a
normalised event. The adapters differ in `build_command` and in how they parse the stream.
""",
         code('''from memorizz.metaharness.base import AgentHarness, SubprocessHarness
show(AgentHarness, count=26)'''),
         md("### What every subprocess harness does"),
         code('''show(SubprocessHarness.run, count=60)'''),
         md("### Two adapters, two command lines\n\nClaude Code is run restricted: exactly the tools the policy allows, a private config directory, no OAuth fallback. Codex is run non-interactively with its own sandbox mode."),
         code('''from memorizz.metaharness.adapters import ClaudeCodeHarness, CodexHarness, PiHarness
show(ClaudeCodeHarness.build_command, count=70)'''),
         code('''show(CodexHarness.build_command, count=50)'''),
         md("### The normalised events\n\nWhatever a vendor prints, the host stores messages, tool calls and results, commands, file changes, usage and errors under one enumeration."),
         code('''from memorizz.metaharness.models import HarnessEvent, HarnessEventType
show(HarnessEventType, count=24)'''),
         md("### Which harnesses are ready here ⭐\n\n`probe` runs the vendor's own readiness check and reports a secret-free error contract when something is missing."),
         code('''from memorizz.metaharness import MetaHarness
doctor = MetaHarness.from_env(allowed_workspace_roots=[str(WORKSPACE.parent)])
for name in ["claude-code", "codex", "pi", "hermes", "deepseek", "openhands"]:
    found = doctor.probe(name)
    print(f"{name:<12} ready={found.get('ready')!s:<6} {str(found.get('error') or found.get('remediation') or '')[:80]}")'''),
         star=True),
    part("Security and routing", """
Before a child process starts, the host decides where it may work, what it may see and
which harness will run it. `resolve_workspace` refuses a path outside the allowed roots.
`build_child_environment` passes only what the adapter needs. `redact` keeps credential
values out of every event that is stored. `HarnessRouter` chooses a ready harness for
`auto` and fails closed when the named one is not ready.
""",
         code('''from memorizz.metaharness import security
show(security.resolve_workspace, count=28)'''),
         code('''show(security.build_child_environment, count=18)
print()
show(security.redact, count=18)'''),
         md("### The workspace fingerprint\n\nA snapshot of the tree before and after a run is how the host knows what a harness changed, and how an approval becomes invalid when the workspace changed underneath it."),
         code('''show(security.workspace_snapshot, count=40)'''),
         code('''from memorizz.metaharness.router import HarnessRouter
show(HarnessRouter, find="def route", count=44)'''),
         ),
    part("Memory into context", """
The meta-harness is memory-first. Before a harness starts, `HarnessContextBuilder` asks
the memory provider for what is known about this scope, ranks it, fits it into a bounded
pack, and fingerprints the pack, so two stages of one plan, or two harnesses in one
comparison, can be shown byte-identical evidence.
""",
         code('''from memorizz.metaharness.context import HarnessContextBuilder
show(HarnessContextBuilder.build, count=58)'''),
         md("""### The memory provider on Oracle AI Database

MemoRizz's `OracleProvider` keeps every memory type in Oracle with vectors made inside the
database. One patch is needed on the Free *lite* image: the provider reads existing
`VECTOR` column dimensions through `DBMS_METADATA`, which needs XDB, and the lite image
has no XDB. The data dictionary already has the answer in `USER_TAB_COLS.VECTOR_INFO`.
"""),
         code(lift(SHARED / "memorizz_oracle_patch.py", "vector_dimensions_from_dictionary", "patch_oracle_provider")),
         code('''patch_oracle_provider()
from memorizz.memory_provider.oracle import OracleConfig, OracleProvider
provider = OracleProvider(OracleConfig(user=ORA.user, password=ORA.password, dsn=ORA.dsn,
                                       in_database_embedding=True, pool_max=4))
print("vector columns seen:", len(provider.get_vector_schema_dimensions()))'''),
         ),
    part("Durable state in Oracle", """
MemoRizz ships its run ledger and its approval queue on SQLite, for one local worker. Both
are small protocols, so the host can keep the same records in the database it already
runs on. The run store holds runs, their events, workspace leases and orchestrations; the
approval store holds proposals with a single-use id, an argument hash and an expiry. Rows
carry the record as JSON beside the columns that are queried.
""",
         code('''from memorizz.metaharness.store import HarnessRunStore
show(HarnessRunStore, count=60)'''),
         code('''from memorizz.approval import (ApprovalMismatch, ApprovalNotFound, ApprovalProposal, ApprovalStateError,
                               ApprovalStatus, argument_hash, canonical_arguments)
from memorizz.metaharness.models import HarnessOrchestration, HarnessRun, utcnow_iso'''),
         code(lift(SHARED / "memorizz_oracle_stores.py", "_dump", "_now", "_iso", "_when", "OracleTables")),
         md("### Runs\n\nCreate, read, list and update. An update is a read-modify-write under a row lock, so two hosts cannot erase each other's change."),
         code(lift(SHARED / "memorizz_oracle_stores.py", "OracleRuns")),
         md("### Events and workspace leases\n\nEvents are numbered per run as they are appended. A lease is one row per workspace, so two runs cannot edit the same tree at once."),
         code(lift(SHARED / "memorizz_oracle_stores.py", "OracleEvents", "OracleLeases")),
         md("### Orchestrations, recovery, and the store itself\n\nA plan or a comparison is a record with steps. A host that starts marks what its last life left running as interrupted."),
         code(lift(SHARED / "memorizz_oracle_stores.py", "OracleOrchestrations", "OracleHarnessRunStore")),
         md("### The approval queue\n\nA proposal is pending, approved, rejected, expired or consumed. Approving and consuming happen under a row lock; consuming checks the tool name and the argument hash."),
         code(lift(SHARED / "memorizz_oracle_stores.py", "OracleProposals")),
         code(lift(SHARED / "memorizz_oracle_stores.py", "OracleDecisions", "OracleApprovalStore")),
         md("### Assemble the meta-harness ⭐\n\n`from_env` registers the adapters it can find. The stores and the provider are passed in, and the workspace root is the only place a harness may work."),
         code('''RUNS = OracleHarnessRunStore(pool("mh", max=4), prefix="MH")
APPROVALS = OracleApprovalStore(pool("mh", max=4), prefix="MH")
meta = MetaHarness.from_env(memory_provider=provider, run_store=RUNS, approval_store=APPROVALS,
                            allowed_workspace_roots=[str(WORKSPACE.parent)])
print("adapters:", sorted(meta.adapters), "| interrupted runs recovered at start:", meta.recovered_runs)
print("tables:", [t["table_name"] for t in rows("SELECT table_name FROM user_tables WHERE REGEXP_LIKE(table_name, '^MH_') ORDER BY 1")])'''),
         star=True),
    part("One run, end to end", """
`MetaHarness.run` is the sequence the whole lesson is about: scope the task, retrieve
memory, route, apply policy, pause for approval when the task needs authority, execute
through the adapter, verify on the host, record everything. Read it first, then run it.
""",
         code('''show(MetaHarness.run, count=70)'''),
         md("### The workspace\n\nA small project written into a scratch folder, as a git repository, so a harness's edits can be diffed and nothing in the course is touched. The defect is planted in `book()`."),
         code(lift(ADVANCED / "scripts" / "metaharness_workspace.py", "LEDGER_SOURCE", "TEST_SOURCE")),
         code(lift(ADVANCED / "scripts" / "metaharness_workspace.py", "FILES", "write_workspace")),
         code('''write_workspace(WORKSPACE)
print(subprocess.run([sys.executable, "-m", "pytest", "-q"], cwd=WORKSPACE, capture_output=True, text=True).stdout.strip().splitlines()[-1])
print((WORKSPACE / "tripbook" / "ledger.py").read_text().split("def book")[1][:420])'''),
         md("### Run it on Claude Code ⭐"),
         code('''started = time.perf_counter()
result = meta.run(task)
print(f"{time.perf_counter() - started:.0f} s | {result.harness} | status {result.status.value} | ok {result.ok} | "
      f"verified {result.verified} | cost {result.cost_usd} USD | routing {result.routing.get('reason', '')[:60]}")
print()
print(result.final_response[:1500])'''),
         md("### What was recorded\n\nThe run row, its events, the verification and the context pack that was shown to the harness, all from Oracle."),
         code('''run = RUNS.get(result.run_id)
events = RUNS.events(result.run_id)
kinds = {}
for event in events:
    kinds[event.type.value] = kinds.get(event.type.value, 0) + 1
print("run:", run.status.value, "| events:", len(events), kinds)
print("verification:", json.dumps(result.verification, default=str).replace(str(Path.home()), "~")[:240])
print("context pack:", {"records": len(result.context_pack.records) if result.context_pack else 0,
                        "fingerprint": (result.context_pack.fingerprint if result.context_pack else "")[:16]})
print(rows("SELECT run_id, status, harness, created_at FROM mh_runs ORDER BY created_at DESC FETCH FIRST 3 ROWS ONLY"))'''),
         star=True),
    part("The approval gate", """
A task that can change the workspace, use the network, see a secret or write through a
governed MCP capability does not start. The host records a proposal that binds the tool
name, the complete arguments, the workspace fingerprint, the permissions, the budgets and
the verification to a single-use id with an expiry, and the run waits as
`pending_approval`. Approval executes the original checkpoint; the model is never asked
to reconstruct approved arguments, and a workspace that changed in the meantime makes
the approval invalid.
""",
         code('''show(MetaHarness.approve, count=44)'''),
         code('''show(MetaHarness.resume_approval, count=14)
print()
show(APPROVALS.consume, count=30)'''),
         ),
    part("A staged plan across three harnesses", """
`start_plan` runs stages in order, each on its own harness, and returns at once with a
durable record. A background driver in the host process starts each run and keeps the
record current. When a stage finishes, its events are reduced to a **handoff**: the answer,
the changed files, the recent commands, the verification result. The next stage receives
every earlier handoff, fitted to a budget, so the first plan is never silently dropped.
The memory scope is the one this notebook created, so the plan also sees the read-only
review from Part 7 and nothing from earlier runs.
A stage that needs approval waits for the host; the plan stops at the first stage that
does not succeed.

```mermaid
flowchart LR
  T[task + memory] --> P[Plan · pi<br/>read-only]
  P -->|handoff| I[Implement · Codex<br/>direct edit · approval · pytest]
  I -->|handoff| R[Review · Claude Code<br/>read-only]
  P & I & R --> O[(runs · events · approvals · conversation memory)]
```
""",
         code('''show(MetaHarness._drive_plan, count=62)'''),
         code('''from memorizz.metaharness import handoff
show(handoff.stage_handoff, count=50)'''),
         md("### Start the plan ⭐\n\nThe fix from the use case: three stages, one edit stage with a verification command."),
         code('''write_workspace(WORKSPACE)
FIX = ("In tripbook/ledger.py, a booking that was cancelled is replayed by book() as if it were still confirmed. "
       "Booking the same offer again after a cancel must create a new confirmed booking. Keep the change minimal, "
       "keep the public API, and keep python -m pytest -q green.")
plan = meta.start_plan(
    {"task": FIX, "workspace": str(WORKSPACE), "memory_id": MEMORY, "user_id": "richmond", "thread_id": "ledger-fix"},
    [{"name": "Plan", "harness": "pi", "instruction": "Write a short plan for the fix and the test to add. Do not edit files."},
     {"name": "Implement", "harness": "codex", "workspace_mode": "direct", "verification": {"command": "python -m pytest -q"}},
     {"name": "Review", "harness": "claude-code",
      "instruction": f"Review the change made in this workspace against this task: {FIX} Do not edit files. "
                     "Say whether the change is correct and minimal."}])
ORCHESTRATION = plan["orchestration_id"]
print(ORCHESTRATION, plan["status"], [s["name"] + ":" + s["harness"] for s in plan["steps"]])'''),
         md("### Watch it, and approve the edit ⭐\n\nThe host polls the record. When the Codex stage proposes its edit, the host approves it and resumes the run. Nothing else is decided by a person."),
         code('''started, approved = time.perf_counter(), set()
while True:
    time.sleep(5)
    record = meta.get_orchestration(ORCHESTRATION)
    for proposal in APPROVALS.list(status="pending"):
        if proposal.proposal_id not in approved:
            approved.add(proposal.proposal_id)
            print(f"[{time.perf_counter() - started:4.0f} s] approval needed: {proposal.tool_name} — {proposal.policy_reason[:90]}")
            meta.approve(proposal.proposal_id, approver_id="richmond@workshop")
            meta.resume_approval_start(proposal.proposal_id)
    stages = " | ".join(f"{s['name']}: {RUNS.get(s['run_id']).status.value if s.get('run_id') else '-'}" for s in record["steps"])
    print(f"[{time.perf_counter() - started:4.0f} s] {record['status']:<16} {stages}")
    if record["status"] in {"succeeded", "failed", "canceled", "interrupted"} or time.perf_counter() - started > 900:
        break'''),
         md("### What each stage said, and what changed"),
         code('''for step in record["steps"]:
    run = RUNS.get(step["run_id"])
    result = run.result or {}
    print(f"== {step['name']} on {run.harness}: {run.status.value} | verified {result.get('verified')} | "
          f"cost {result.get('cost_usd')} USD | {result.get('latency_ms')} ms")
    print(textwrap.indent((result.get("final_response") or "")[:600], "   "))
    print()
implemented = RUNS.get(record["steps"][1]["run_id"]).result or {}
print((implemented.get("workspace_diff") or "no diff recorded")[:1600])'''),
         md("### The handoffs in conversation memory\n\nEach stage's handoff was written to the memory scope, so later runs in the same scope receive it in their context pack."),
         code('''print(rows("SELECT COUNT(*) AS turns FROM conversation_memory WHERE memory_id = :m", {"m": MEMORY}))
for turn in rows("SELECT SUBSTR(content, 1, 160) AS c FROM conversation_memory WHERE memory_id = :m "
                 "ORDER BY timestamp DESC FETCH FIRST 3 ROWS ONLY", {"m": MEMORY}):
    print("-", turn["c"].replace("\\n", " "))
print(rows("SELECT orchestration_id, kind, status FROM mh_orchestrations ORDER BY created_at DESC FETCH FIRST 3 ROWS ONLY"))
print(rows("SELECT tool_name, status, approver_id FROM mh_approvals ORDER BY created_at DESC FETCH FIRST 3 ROWS ONLY"))'''),
         star=True),
    part("The same question to two harnesses", """
A comparison runs one read-only task on several harnesses at the same time, with the same
context pack, and finishes `failed` when any of them fails. It is the simplest fair
experiment a meta-harness makes possible: same task, same evidence, different agent.
""",
         code('''show(MetaHarness._drive_compare, count=40)'''),
         code('''compare = meta.start_compare(
    {"task": "Where can tripbook/ledger.py lose or double a booking? Answer in three bullets, no edits.",
     "workspace": str(WORKSPACE), "memory_id": MEMORY, "user_id": "richmond", "thread_id": "ledger-compare"},
    ["pi", "claude-code"])
COMPARE = compare["orchestration_id"]
started = time.perf_counter()
while True:
    time.sleep(5)
    record = meta.get_orchestration(COMPARE)
    if record["status"] in {"succeeded", "failed", "canceled", "interrupted"} or time.perf_counter() - started > 600:
        break
print(f"{time.perf_counter() - started:.0f} s | {record['status']}")
for step in record["steps"]:
    run = RUNS.get(step["run_id"])
    result = run.result or {}
    print(f"\\n== {run.harness}: {run.status.value} | cost {result.get('cost_usd')} USD | {result.get('latency_ms')} ms")
    print(textwrap.indent((result.get("final_response") or "")[:500], "   "))'''),
         ),
    part("What the ledger holds", """
Every run, event, approval and orchestration of this notebook is in Oracle AI Database.
This part reads them back the way an operations console would.
""",
         code('''print(rows("SELECT harness, status, COUNT(*) AS runs FROM mh_runs GROUP BY harness, status ORDER BY harness, status"))
print(rows("SELECT event_type, COUNT(*) AS n FROM mh_events GROUP BY event_type ORDER BY n DESC"))
for run in RUNS.list(limit=6):
    result = run.result or {}
    print(f"{run.run_id[:8]}  {run.harness:<12} {run.status.value:<16} cost {result.get('cost_usd')}  "
          f"usage {json.dumps(result.get('usage') or {})[:60]}")'''),
         md("### Close\n\nThe pools are closed. The tables stay, so the next run of the notebook starts by recovering nothing and reading everything."),
         code('''provider.close() if hasattr(provider, "close") else None
for name, found in list(_pools.items()):
    found.close(force=True); _pools.pop(name, None)
print("closed")'''),
         ),
]

CLOSING = [
    md("""
## Key takeaways

1. **A meta-harness normalises, it does not replace.** Each vendor keeps its own loop; the
   host owns the task contract, the permissions, the memory, the events, the approval and
   the evidence, and every harness speaks the same types.
2. **Readiness is a probe, not a hope.** `probe` runs the vendor's own check and reports a
   secret-free error contract, so a missing login is a structured failure, not a stack trace.
3. **Security happens before the child starts.** Workspace roots, a minimal child
   environment, redaction of every stored event, and a fingerprint of the tree before and
   after.
4. **Approval binds the exact call.** The proposal holds the arguments and the workspace
   fingerprint; approval executes that checkpoint and nothing else, once.
5. **Memory is the shared evidence.** One ranked, bounded context pack per task, reused
   byte-identical across the stages of a plan and the harnesses of a comparison.
6. **Handoffs are structured, not pasted.** A stage passes its answer, changed files,
   commands and verification result to the next, fitted to a budget, and into memory.
7. **Durable state can live where the rest of the application lives.** The run ledger and
   the approval queue are small protocols; this notebook keeps them in Oracle AI Database.

## From the checkout to the package

Unset `MEMORIZZ_SRC`, or point it at an empty path, and the notebook imports the installed
`memorizz`. Everything above reads its source through `inspect`, so the excerpts always
show the code that is running.
"""),
]

if __name__ == "__main__":
    out = build("Understanding a meta-harness: MemoRizz, read and run", LEAD + ARCHITECTURE +
                "\n**One run through the meta-harness**\n" + SEQUENCE, PARTS, OUT, DIAGRAMS, CLOSING)
    print("wrote", out)
