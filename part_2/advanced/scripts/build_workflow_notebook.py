"""Build workflow/notebook/advanced_trip_booking_workflow.ipynb from the harness modules.

    python part_2/advanced/scripts/build_workflow_notebook.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from notebook_kit import build, code, lift, md, part  # noqa: E402

ADVANCED = Path(__file__).resolve().parents[1]
H = ADVANCED / "workflow" / "appbook" / "backend" / "harness"
SHARED = ADVANCED / "shared" / "oracle.py"
OUT = ADVANCED / "workflow" / "notebook" / "advanced_trip_booking_workflow.ipynb"
DIAGRAMS = ADVANCED / "workflow" / "notebook" / "diagrams"

LEAD = """
A **workflow** is the agentic application mode where the steps are known before the run
starts. The model still reads, judges and writes, but it does so inside a shape the
harness owns: which step comes next, what runs in parallel, where a person must decide,
what happens when a step fails, and how a run that died is picked up again.

The use case is a trip. A traveller writes one sentence, and the harness searches the
real web for flights, hotels and cars, composes an itinerary from what it found, asks the
traveller to approve it, books the three parts one after another, and keeps every step
in Oracle AI Database so that nothing is lost when the process stops.

| Concern | What this notebook builds |
|---|---|
| Durable state | LangGraph checkpoints in Oracle through `OracleSaver`, one thread per trip |
| Real evidence | Tavily web search; every page read is kept, and every offer names its page |
| Typed model answers | Claude with a JSON schema on every call, so the harness never parses prose |
| Memory | Oracle Agent Memory holds what the traveller prefers, across trips |
| Parallel work | The three searches run at the same time and join before planning |
| Approval | `interrupt()` pauses the run; the traveller's decision resumes the same run |
| Compensation | A provider failure cancels earlier bookings and falls back to the next offer |
| Idempotency | A booking made twice returns the first confirmation |
| Recovery | The process is killed between two bookings and continues in a new process |

**Honesty about prices.** The searches are real and the pages are real, but a price on
a search page is indicative, not a fare held for this traveller. The harness labels
every offer with how confident it is and books against a system of record that stands
in for a provider. The lesson is the harness, not the fare.
"""

ARCHITECTURE = """
```mermaid
flowchart TB
  T[Traveller] -->|one sentence| H[Trip harness · LangGraph]
  H --> M[(Oracle Agent Memory<br/>traveller preferences)]
  H --> S[Tavily web search]
  S --> E[(TRIP_EVIDENCE<br/>every page read)]
  H --> C[Claude Opus 5.5<br/>typed answers only]
  H --> R{{Traveller review<br/>interrupt}}
  R --> B[Booking saga<br/>flight → hotel → car]
  B --> K[(TRIP_BOOKINGS<br/>system of record)]
  H --> P[(OracleSaver checkpoints<br/>one thread per trip)]
  H --> L[(TRIP_LEDGER<br/>audit trail)]
```
"""

REQUEST_PATH = """
```mermaid
sequenceDiagram
  participant Tr as Traveller
  participant G as Graph
  participant O as Oracle AI Database
  participant W as Web (Tavily)
  participant C as Claude
  Tr->>G: "Book me London to Lisbon, 12 to 15 October, flight hotel car, £900"
  G->>O: recall preferences (Oracle Agent Memory)
  G->>C: understand the request (JSON schema)
  par three searches
    G->>W: flights
    G->>W: hotels
    G->>W: cars
  end
  G->>O: keep every page as evidence
  G->>C: extract typed offers from each result set
  G->>C: compose one itinerary within budget
  G->>O: checkpoint, then interrupt()
  G-->>Tr: itinerary to approve
  Tr->>G: approve
  G->>O: book flight, hotel, car (idempotency keys)
  G->>O: remember the trip
```
"""

PARTS = [
    part("Environment", """
The notebook needs Python 3.11 or newer, Docker for Oracle AI Database, an Anthropic key
and a Tavily key. Keys are read from the environment or asked for with a hidden prompt;
they are never written into the notebook.
""",
         md("### Install the packages"),
         code('''%pip install -q "anthropic>=1.9" "langgraph>=1.2,<2" "langgraph-oracledb==1.0.1" \\
  "oracleagentmemory==26.8.0" "oracledb>=4.0.2" "tavily-python>=0.8" "requests>=2.32"'''),
         md("### Imports\n\nEverything the notebook uses, in one place."),
         code('''from __future__ import annotations

import hashlib, json, os, re, subprocess, sys, time, uuid, warnings
from dataclasses import dataclass
from datetime import date, datetime, timezone
from getpass import getpass
from operator import add
from pathlib import Path
from typing import Annotated, Any, TypedDict

import oracledb, requests
from anthropic import Anthropic
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, interrupt
from langgraph_oracledb.checkpoint.oracle import OracleSaver
from oracleagentmemory.core import (MemoryExtractionConfig, MemoryExtractionMode, OracleAgentMemory,
                                    OracleDBMemoryStore, SchemaPolicy, SearchIndexSyncMode, SearchStrategy)
from oracleagentmemory.core.embedders import OracleDBEmbedder
from oracleagentmemory.core.llms import Llm
from tavily import TavilyClient

oracledb.defaults.fetch_lobs = False
warnings.filterwarnings("ignore", message="You are calling an asynchronous method")   # Oracle Agent Memory inside Jupyter'''),
         md("### Keys\n\nA key that is already in the environment is used as it is. A missing key is asked for with a hidden prompt."),
         code('''def secret(name: str, prompt: str) -> str:
    value = os.getenv(name, "").strip() or getpass(prompt).strip()
    if not value:
        raise RuntimeError(f"{name} is required for this notebook.")
    os.environ[name] = value
    return value

secret("ANTHROPIC_API_KEY", "Anthropic API key: ")
secret("TAVILY_API_KEY", "Tavily API key: ")
print("keys present")'''),
         md("""### Oracle AI Database

The database runs in Docker. The notebook talks to it on the host port and to the
container itself for the one thing that needs an administrator: creating the schema.
Inside the container, operating-system authentication lets `sqlplus / as sysdba` run
without a password, so no SYS password is written anywhere. Off Docker,
`ORACLE_ADMIN_PASSWORD` is used instead.
"""),
         code(lift(SHARED, "ONNX_URL", "GRANTS", "ALREADY_THERE", "POOL", "OracleConfig", "ORA", "_pools")),
         code(lift(SHARED, "reachable", "_container_running", "admin_sql")),
         md("### Start the database if it is not running\n\nThe image is Oracle AI Database Free. The first start takes a few minutes."),
         code('''if not reachable():
    port = ORA.dsn.split(":")[1].split("/")[0]
    if subprocess.run(["docker", "start", ORA.container], capture_output=True).returncode:
        subprocess.run(["docker", "run", "-d", "--name", ORA.container, "-p", f"127.0.0.1:{port}:1521",
                        "-e", "ORACLE_PWD=" + os.getenv("ORACLE_ADMIN_PASSWORD", "ChangeMe_2026!"),
                        "-v", f"{ORA.container}-data:/opt/oracle/oradata",
                        "container-registry.oracle.com/database/free:latest-lite"], check=True, capture_output=True)
    deadline = time.monotonic() + 600
    while not _container_running() or admin_sql(["BEGIN NULL; END;"]) and time.monotonic() < deadline:
        time.sleep(5)
print("database reachable:", reachable())'''),
         md("### The schema, a pool and three helpers\n\n`ensure_schema` is idempotent: the tablespace, the user and the grants are created once."),
         code(lift(SHARED, "ensure_schema")),
         code(lift(SHARED, "pool", "_patient", "rows", "execute", "ddl")),
         code('''print(ensure_schema())
print("Oracle AI Database", rows("SELECT version_full AS v FROM product_component_version FETCH FIRST 1 ROW ONLY")[0]["v"])'''),
         md("""### An embedding model inside the database

Oracle Agent Memory searches by meaning, so the schema needs an embedding model. The
model is loaded into the database once with `DBMS_VECTOR.LOAD_ONNX_MODEL`, and from
then on `VECTOR_EMBEDDING(...)` runs inside SQL. No embedding service is called.
"""),
         code(lift(SHARED, "ensure_embedding_model", "EMBED", "embedding")),
         code('''print(ensure_embedding_model())
print(len(embedding("a trip to Lisbon")), "dimensions, computed inside the database")'''),
         ),
    part("The system of record and the ledger", """
Before any model is called, the harness decides what it must never lose. Four things:
the request, the evidence it reads, the bookings it makes, and an audit trail. Each is a
table. LangGraph's checkpoints hold the run's control flow, but the bookings are the
outside world's truth and get a table of their own.

| Table | Holds | Why it is separate |
|---|---|---|
| `TRIP_REQUESTS` | one row per trip | status a person can query |
| `TRIP_EVIDENCE` | every page read | an offer must be traceable to a page |
| `TRIP_OFFERS` | every typed offer | what the planner chose from |
| `TRIP_BOOKINGS` | the system of record | a crash must not lose or double a booking |
| `TRIP_PROVIDER_FAULTS` | failures a lesson injects | to show compensation |
| `TRIP_LEDGER` | every step of every run | what the traveller could be shown |
""",
         code(lift(H / "tables.py", "TRIP_TABLES", "create_trip_tables")),
         code(lift(H / "tables.py", "new_id", "now_iso", "ledger", "trip_ledger", "reset_trip_tables")),
         code('''create_trip_tables()
reset_trip_tables()
print({t: rows(f"SELECT COUNT(*) AS n FROM {t}")[0]["n"] for t in TRIP_TABLES})'''),
         ),
    part("Traveller memory", """
A trip harness that forgets the traveller between trips asks the same questions every
time. Oracle Agent Memory keeps what the traveller prefers, scoped to the traveller and
to this agent, searchable by meaning through the embedding model in the database.

The harness writes memories itself and turns background extraction off: a booking
workflow should store what it decided to store, not what a model inferred from a
conversation it never had.
""",
         code(lift(H / "config.py", "TripConfig", "CFG", "_clients", "claude", "tavily")),
         code(lift(H / "memory.py", "_memory", "agent_memory", "ensure_traveller")),
         code(lift(H / "memory.py", "memory_key", "remember", "recall", "forget_traveller")),
         md("### Seed what this traveller is known to prefer ⭐\n\nThree statements, stored once each. Storing one again is a no-op."),
         code('''TRAVELLER = "richmond"
for statement in ["Prefers a direct flight and a morning departure.",
                  "Likes to stay near the old town or city centre.",
                  "Only needs a small automatic car."]:
    print(remember(TRAVELLER, statement))
print(recall(TRAVELLER, "a trip to Lisbon with a flight, a hotel and a car"))'''),
         star=True),
    part("Typed answers from the model", """
Every model call in this harness has the same shape: instructions, a request, and a JSON
schema the answer must fit. The Claude API enforces the schema, so the harness receives
an object, never a paragraph to parse. The instructions also say that web text is data:
a page that contains "ignore your instructions" is a page, not a command.
""",
         code(lift(H / "llm.py", "USAGE", "strict", "ask_typed")),
         code('''answer = ask_typed("Answer in the schema.", "What is the capital of Portugal, and its airport code?",
                   "fact", {"type": "object", "properties": {"city": {"type": "string"}, "airport": {"type": "string"}},
                            "required": ["city", "airport"]})
print(answer, USAGE)'''),
         ),
    part("Real search evidence", """
The harness searches the web with Tavily, keeps every result as evidence, and asks the
model to turn the numbered results into typed offers. An offer that does not name its
result is dropped, and a price is carried with its currency, its unit (total, per night,
per day) and a confidence: `high` when the page states a price for these dates,
`medium` for a price without dates, `low` for a "from" teaser.

```mermaid
flowchart LR
  Q[query] --> T[Tavily search] --> R[numbered results]
  R --> E[(TRIP_EVIDENCE)]
  R --> C[Claude · offers schema] --> O[offers, each naming a result]
  O --> F[(TRIP_OFFERS)]
```
""",
         code(lift(H / "search.py", "SEARCH_INSTRUCTIONS", "OFFER_SCHEMA", "QUERIES", "WIDER")),
         code(lift(H / "search.py", "search_web", "keep_evidence")),
         code(lift(H / "search.py", "extract_offers", "find_offers")),
         md("### One real search ⭐\n\nA flight search for the trip in this notebook. The offers are sorted by what they cost for the whole trip."),
         code('''SAMPLE = {"origin": "London", "destination": "Lisbon", "depart": "2026-10-12", "back": "2026-10-15",
          "month": "October", "year": "2026", "nights": 3, "hotel_area": "city centre"}
flights = find_offers("TRIP-sample", "flight", SAMPLE)
for offer in flights[:5]:
    print(f"{offer['total_gbp']:>8.2f} GBP  {offer['confidence']:<6} {offer['provider'][:28]:<28} {offer['summary'][:70]}")
print(len(flights), "offers from", len({o["evidence_id"] for o in flights}), "pages")'''),
         star=True),
    part("Understanding and planning", """
Two more typed calls. The first turns the traveller's sentence and their stored
preferences into a structured request, and asks a question only when a search would be
pointless without the answer. The second composes one itinerary from the offers found,
names the alternatives to fall back to, and leaves the arithmetic to the harness: the
harness adds up the totals and checks the budget, so the number the traveller sees is
computed, not generated.
""",
         code(lift(H / "planning.py", "REQUEST_SCHEMA", "UNDERSTAND", "understand_request")),
         code(lift(H / "planning.py", "ITINERARY_SCHEMA", "PLAN", "plan_itinerary")),
         code('''request = understand_request("Book me a trip from London to Lisbon, out on 12 October 2026 and back on "
                             "15 October 2026. I need a flight, a hotel and a car. Budget £900.",
                             recall(TRAVELLER, "trip"), date.today().isoformat())
print(json.dumps(request, indent=1))'''),
         ),
    part("The booking system of record", """
No real provider is called. A booking is a row that stands for a provider's
confirmation, and that is enough to teach three things that are real:

1. **Idempotency.** The key `trip:component:offer:attempt` makes the same booking request
   return the first confirmation. A process that dies after the provider answered, but
   before the harness saved its progress, cannot book twice.
2. **Failure.** A provider can answer `sold_out`. A lesson injects that on purpose.
3. **Compensation.** When one component fails, what was already booked is cancelled
   before the harness plans again.
""",
         code(lift(H / "bookings.py", "ProviderError", "add_fault", "take_fault", "idempotency_key")),
         code(lift(H / "bookings.py", "book", "cancel", "confirmed_bookings", "all_bookings")),
         md("### The same booking twice is one booking"),
         code('''offer = flights[0]
first = book("TRIP-sample", "flight", offer, attempt=0)
again = book("TRIP-sample", "flight", offer, attempt=0)
print(first["confirmation"], again["confirmation"], "replayed:", again["replayed"])
print(all_bookings("TRIP-sample"))'''),
         ),
    part("The durable graph", """
Now the shape. The graph is a `StateGraph` whose state is a typed dictionary. Two
fields have reducers: `offers` merges what the parallel searches return, and
`bookings` and `log` append. Every node is a plain function that returns the fields it
changed. LangGraph writes a checkpoint to Oracle after every step, so the run can be
paused, resumed, and continued from wherever it stopped.

```mermaid
flowchart TB
  S([start]) --> R[recall_preferences] --> U[understand]
  U -->|questions| A[ask_traveller] --> E1([end])
  U --> SF[search_flight]
  U --> SH[search_hotel]
  U --> SC[search_car]
  SF --> J[join_offers]
  SH --> J
  SC --> J
  J -->|nothing found| E1
  J --> P[plan] --> V{{review · interrupt}}
  V -->|change| RP[replan] --> P
  V -->|reject| X[close] --> E2([end])
  V -->|approve| BF[book_flight] --> BH[book_hotel] --> BC[book_car]
  BC -->|a provider failed| CO[compensate]
  CO -->|fallback found| V
  CO -->|no fallback| X
  BC --> CF[confirm] --> E2
```
""",
         code(lift(H / "graph.py", "COMPONENTS", "merge_offers", "TripState", "note_step", "Crashed", "maybe_crash")),
         md("### Recall, understand, and search in parallel\n\n`after_understand` returns a list of node names, and LangGraph runs them in the same step. `join_offers` waits for all three."),
         code(lift(H / "graph.py", "recall_preferences", "understand", "after_understand", "ask_traveller")),
         code(lift(H / "graph.py", "searcher", "join_offers", "after_join")),
         md("### Plan, pause, decide\n\n`review` calls `interrupt()`. The run stops with its state in Oracle. Whatever resumes it is the traveller's decision."),
         code(lift(H / "graph.py", "plan", "review", "after_review", "replan")),
         md("### The saga\n\nThree booking steps in a fixed order. Each is safe to run twice. A failure sends the run to `compensate`, which cancels what was booked and swaps in the next offer for the failed component, for the traveller to approve again."),
         code(lift(H / "graph.py", "booker", "after_booking")),
         code(lift(H / "graph.py", "compensate", "after_compensate", "confirm", "close")),
         md("### Wire it ⭐"),
         code(lift(H / "graph.py", "build_graph")),
         code(lift(H / "graph.py", "_runtime", "durable_graph", "config_for", "outcome")),
         code(lift(H / "graph.py", "start_trip", "resume_trip", "continue_trip")),
         code('''graph = durable_graph()
print(len(graph.get_graph().nodes), "nodes; checkpoints in Oracle:",
      [t["table_name"] for t in rows("SELECT table_name FROM user_tables WHERE table_name LIKE 'CHECKPOINT%' ORDER BY 1")])'''),
         star=True),
    part("A trip, up to the approval gate", """
One sentence in. The harness recalls the traveller, understands the request, runs the
three searches at the same time, plans, and stops at `review` with the itinerary
saved. Nothing has been booked.
""",
         md("### Start the run ⭐"),
         code('''TRIP = "TRIP-" + uuid.uuid4().hex[:6]
TEXT = ("Book me a trip from London to Lisbon, out on 12 October 2026 and back on 15 October 2026. "
        "I need a flight, a hotel and a car. Budget £900.")
started = time.perf_counter()
out = start_trip(TEXT, TRAVELLER, trip_id=TRIP)
print(f"{time.perf_counter() - started:.0f} s | status {out['status']} | next {out['next']} | "
      f"offers {out['offers']} | checkpoints {out['checkpoints']}")'''),
         md("### What the traveller is asked to approve"),
         code('''itinerary = out["itinerary"]
print(f"total {itinerary['total_gbp']} {itinerary['currency']} | within budget: {itinerary['within_budget']}\\n")
for choice in itinerary["choices"]:
    offer = choice["offer"]
    print(f"{choice['component']:<7} {offer['total_gbp']:>8.2f} GBP  {offer['confidence']:<6} "
          f"{offer['provider'][:26]:<26} {offer['summary'][:60]}")
    print(f"        why: {choice['why'][:120]}")
    print(f"        fallbacks: {len(choice['alternatives'])}")
print("\\n" + itinerary["summary"])
for caveat in itinerary["caveats"]:
    print("-", caveat)'''),
         star=True),
    part("Change, failure, compensation", """
The traveller asks for a change, then approves. Before the approval, a lesson makes the
hotel provider answer `sold_out` once. The saga books the flight, fails on the hotel,
cancels the flight, swaps in the next hotel, and asks the traveller again. The second
approval books all three.
""",
         md("### Ask for a change ⭐\n\nThe note travels into `plan` as the traveller's note on the previous plan. The run is the same run; its checkpoint count grows."),
         code('''out = resume_trip(TRIP, "change", "Choose a flight with a stated fare for my exact dates, even if it costs more.")
print("status", out["status"], "| checkpoints", out["checkpoints"])
for choice in out["itinerary"]["choices"]:
    print(f"{choice['component']:<7} {choice['offer']['total_gbp']:>8.2f} GBP  {choice['offer']['confidence']:<6} {choice['offer']['provider'][:40]}")'''),
         md("### Make the hotel fail once, then approve"),
         code('''hotel = next(c for c in out["itinerary"]["choices"] if c["component"] == "hotel")
add_fault("hotel", hotel["offer"]["provider"], "sold_out", times=1)
out = resume_trip(TRIP, "approve")
print("status", out["status"], "| next", out["next"])
for booking in out["bookings"]:
    print(f"  {booking['component']:<7} {booking['status']:<10} {booking['provider'][:30]:<30} {booking['reason'] or ''}")
print("caveat added:", out["itinerary"]["caveats"][-1])'''),
         md("### Approve the fallback ⭐\n\nA new attempt number means new idempotency keys: the flight is booked again, the fallback hotel and the car follow, and the trip is remembered."),
         code('''out = resume_trip(TRIP, "approve")
print("status", out["status"])
for booking in out["bookings"]:
    print(f"  {booking['component']:<7} {booking['status']:<10} {booking['confirmation'] or '':<14} {booking['price_gbp']}")
print(recall(TRAVELLER, "Lisbon"))'''),
         star=True),
    part("Crash and resume", """
The strongest claim a durable workflow makes is that a dead process is not a lost run.
This part cuts a run off on purpose, inside `book_flight`, after the booking is
committed but before LangGraph has saved that step. Then it continues the run from its
last checkpoint: `book_flight` runs again, the idempotency key returns the first
confirmation, and the hotel and car follow.

In this notebook the cut is an exception raised by `maybe_crash`, because a real
`os._exit` would kill the kernel. LangGraph sees exactly what it would see after a
crash: the step never finished, so nothing of it was saved. The repository has the
two-process version, which kills a child process for real and continues in another:

    python part_2/advanced/scripts/trip_crash_and_resume.py

```mermaid
sequenceDiagram
  participant P1 as Run, first attempt
  participant O as Oracle AI Database
  participant P2 as Run, continued
  P1->>O: checkpoint after review
  P1->>O: book flight (row committed)
  Note over P1: cut off before the checkpoint
  P2->>O: read the last checkpoint
  P2->>O: book flight again → same key → replayed
  P2->>O: book hotel, book car, checkpoint
```
""",
         md("### A second trip, cut off inside book_flight ⭐\n\n`CFG` is rebound with `crash_after` set, so `maybe_crash` fires once the flight is booked."),
         code('''CRASH_TRIP = "TRIP-crash-" + uuid.uuid4().hex[:4]
out = start_trip(TEXT, TRAVELLER, trip_id=CRASH_TRIP)
print("planned; waiting for the traveller:", out["waiting_for_traveller"])
CFG = TripConfig(crash_after="book_flight")
try:
    resume_trip(CRASH_TRIP, "approve")
except Crashed as cut:
    print("cut off:", cut)
finally:
    CFG = TripConfig()
print("bookings committed before the cut:", [(b["component"], b["status"]) for b in all_bookings(CRASH_TRIP)])'''),
         md("### Continue from the last checkpoint ⭐"),
         code('''before = outcome(CRASH_TRIP)
print("found:", before["status"], "| resume from", before["resume_from"], "| checkpoints", before["checkpoints"])
after = continue_trip(CRASH_TRIP)
replayed = [e for e in after["log"] if e["node"] == "book_flight" and e["kind"] == "booked"]
print("now:", after["status"], "| flight replayed:", replayed[-1]["detail"].get("replayed") if replayed else None)
for booking in after["bookings"]:
    print(f"  {booking['component']:<7} {booking['status']:<10} {booking['confirmation']}")'''),
         star=True),
    part("What the database holds", """
Everything the lesson claimed can be checked in the tables: the ledger of every step,
the checkpoints LangGraph wrote, the evidence behind each offer, the bookings and their
states, and the memory the traveller now has.
""",
         code('''for entry in trip_ledger(TRIP):
    print(f"{entry['node']:<20} {entry['kind']:<15} {str(entry['detail'])[:90]}")'''),
         code('''print(rows("""SELECT thread_id, COUNT(*) AS checkpoints FROM checkpoints
                  WHERE thread_id IN (:a, :b) GROUP BY thread_id""", {"a": TRIP, "b": CRASH_TRIP}))
print(rows("SELECT component, COUNT(*) AS pages FROM trip_evidence WHERE trip_id = :t GROUP BY component", {"t": TRIP}))
print(rows("SELECT status, COUNT(*) AS n FROM trip_bookings WHERE trip_id = :t GROUP BY status", {"t": TRIP}))
print("model calls in this notebook:", USAGE)'''),
         md("### Clean up\n\nThe pools are closed. The tables and the memories stay, so the appbook can show them."),
         code('''def close_pools():
    for name, found in list(_pools.items()):
        found.close(force=True); _pools.pop(name, None)
close_pools()
print("closed")'''),
         ),
]

CLOSING = [
    md("""
## Key takeaways

1. **A workflow owns its shape.** The model reads, judges and writes; the graph decides
   what comes next, what runs at once, and where a person must decide.
2. **Checkpoints are not the system of record.** LangGraph's checkpoints hold the run's
   control flow. The bookings live in a table of their own, because they are what the
   outside world would hold.
3. **Idempotency keys make retries safe.** The same booking request returns the first
   confirmation, so a crash between "the provider answered" and "the harness saved it"
   is a replay, not a double booking.
4. **Compensation is a path in the graph, not an exception handler.** A failed component
   cancels earlier bookings, swaps in the next offer, and goes back to the traveller.
5. **Real evidence carries a confidence.** A search page is a page, not a quote. The
   harness labels every offer and the itinerary says so.
6. **Typed answers keep the harness in charge.** Every model call has a schema, the
   harness recomputes the totals, and web text is data.
7. **Memory is written on purpose.** The harness stores what it decided to store about
   the traveller, once, and recalls it by meaning next time.

## What the appbook adds

`part_2/advanced/workflow/appbook` runs this harness as an application: a form for the
traveller, the itinerary card with approve, change and reject, the live trace of every
node, the booking saga with a fault switch, a crash-and-resume button, and a data
explorer over the tables above.
"""),
]

if __name__ == "__main__":
    out = build("Book a trip: a durable, branching workflow harness", LEAD + ARCHITECTURE +
                "\n**One request through the harness**\n" + REQUEST_PATH, PARTS, OUT, DIAGRAMS, CLOSING)
    print("wrote", out)
