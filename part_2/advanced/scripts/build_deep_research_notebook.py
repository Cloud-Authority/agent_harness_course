"""Build deep_research/notebook/advanced_survey_paper_harness.ipynb from the harness modules.

    python part_2/advanced/scripts/build_deep_research_notebook.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from notebook_kit import build, code, lift, md, part  # noqa: E402

ADVANCED = Path(__file__).resolve().parents[1]
H = ADVANCED / "deep_research" / "appbook" / "backend" / "harness"
SHARED = ADVANCED / "shared" / "oracle.py"
OUT = ADVANCED / "deep_research" / "notebook" / "advanced_survey_paper_harness.ipynb"
DIAGRAMS = ADVANCED / "deep_research" / "notebook" / "diagrams"

LEAD = """
**Deep research** is the agentic application mode where the steps are not known before
the run starts. The harness has a goal, a budget and a set of quality rules, and it
decides as it goes what to search for, what to read, what to write and whether the
result is good enough. The model does the reading and the writing. The harness owns
the loop, the evidence, the rules and the two moments where a person must decide.

The use case is a survey paper. Give the harness a subject, and it produces a
survey-like paper on that subject: an introduction that states its lens, background
and definitions, an organising framework, thematic sections that compare works rather
than list them, an evaluation section, an outlook, a conclusion, and a numbered
reference list in which every entry is a page the harness read. The shape follows a
published survey on agent harness design, and the subject in this notebook is
**agent harness engineering** itself.

| Concern | What this notebook builds |
|---|---|
| Evidence | Tavily search on scholarly venues; every page read is stored, with its text |
| A library by meaning | Sources embedded inside Oracle AI Database; a writer can ask for the nearest sources |
| Typed reading | The model reads sources into notes with a fixed shape: contribution, method, evidence, claims |
| An organising framework | Categories, a comparison table and open questions built from the notes |
| Parallel work | Sections are gathered in parallel, and written in parallel, with `Send` |
| Quality rules | Word and citation minimums the harness checks; a referee pass by the model |
| A bounded loop | A revision may gather more evidence once; the round count is in the state |
| Two approvals | The outline before anything is read; the paper before it is published |
| Durability | Checkpoints in Oracle through `OracleSaver`; a run picks up where it stopped |

**Honesty about the output.** The paper is written by a model from pages found on the
web today. It is a survey-like paper: well-shaped, cited, and traceable, but not
peer-reviewed. The last section of every paper it makes says how it was made.
"""

ARCHITECTURE = """
```mermaid
flowchart TB
  P[Person] -->|subject| H[Survey harness · LangGraph]
  H --> C[Claude Opus 5.5<br/>typed answers only]
  H --> T[Tavily search and extract]
  T --> S[(SURVEY_SOURCES<br/>page text + VECTOR embedding)]
  S --> N[(SURVEY_NOTES<br/>typed reading)]
  N --> X[(taxonomy, comparison table)]
  X --> D[(SURVEY_SECTIONS<br/>drafts)]
  D --> R[Referee pass + harness rules]
  R -->|gaps| T
  R --> A[Assemble: numbered citations, references]
  H --> G1{{Outline review}}
  H --> G2{{Publication review}}
  H --> K[(OracleSaver checkpoints)]
```
"""

REQUEST_PATH = """
```mermaid
sequenceDiagram
  participant P as Person
  participant G as Graph
  participant C as Claude
  participant W as Web (Tavily)
  participant O as Oracle AI Database
  P->>G: "agent harness engineering"
  G->>C: scope: questions, criteria, outline with queries
  G-->>P: outline to approve (interrupt)
  P->>G: approve
  par one gather per section
    G->>W: search scholarly venues, read the best pages
    G->>O: store each page with an embedding
  end
  G->>C: read sources into typed notes (batches, in parallel)
  G->>C: organise: framework, comparison table, open questions
  par one write per section
    G->>O: evidence pack: own sources + nearest by meaning
    G->>C: write the section, citing only [S-id]s it was given
  end
  G->>C: referee pass
  G->>G: harness rules: words, citations, every citation resolves
  G->>C: abstract
  G-->>P: paper to approve (interrupt)
  P->>G: approve → files written
```
"""

PARTS = [
    part("Environment", """
Python 3.11 or newer, Docker for Oracle AI Database, an Anthropic key and a Tavily key.
Keys are read from the environment or asked for with a hidden prompt.
""",
         md("### Install the packages"),
         code('''%pip install -q "anthropic>=1.9" "langgraph>=1.2,<2" "langgraph-oracledb==1.0.1" \\
  "oracledb>=4.0.2" "tavily-python>=0.8" "requests>=2.32"'''),
         md("### Imports"),
         code('''from __future__ import annotations

import html as html_lib
import json, os, re, subprocess, sys, time, uuid, warnings
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime, timezone
from getpass import getpass
from operator import add
from pathlib import Path
from typing import Annotated, Any, TypedDict

import oracledb, requests
from anthropic import Anthropic
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, Send, interrupt
from langgraph_oracledb.checkpoint.oracle import OracleSaver
from tavily import TavilyClient

oracledb.defaults.fetch_lobs = False'''),
         md("### Keys"),
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

The same arrangement as the workflow notebook: the schema is created through the
container's operating-system authentication, so no SYS password is needed, and the
embedding model is loaded into the database once.
"""),
         code(lift(SHARED, "ONNX_URL", "GRANTS", "ALREADY_THERE", "POOL", "OracleConfig", "ORA", "_pools")),
         code(lift(SHARED, "reachable", "_container_running", "admin_sql")),
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
         code(lift(SHARED, "ensure_schema")),
         code(lift(SHARED, "pool", "_patient", "rows", "execute", "ddl")),
         code(lift(SHARED, "ensure_embedding_model", "EMBED", "embedding")),
         code('''print(ensure_schema())
print(ensure_embedding_model())
print("Oracle AI Database", rows("SELECT version_full AS v FROM product_component_version FETCH FIRST 1 ROW ONLY")[0]["v"],
      "|", len(embedding("agent harness")), "dimensions inside the database")'''),
         ),
    part("The evidence library", """
A survey is only as good as what it read. Every page the harness reads becomes a row
in `SURVEY_SOURCES` with the page text and an embedding made inside the database as the
row is stored. The library can then be asked by meaning: a writer working on one
section can pull the nearest sources that were gathered for other sections, and every
citation in the paper resolves to a row that holds the page it came from.

| Table | Holds |
|---|---|
| `SURVEY_PAPERS` | one row per paper: subject, outline, taxonomy, the assembled text |
| `SURVEY_SOURCES` | every page read: url, title, text, `VECTOR(384)` embedding |
| `SURVEY_NOTES` | the typed reading of each source |
| `SURVEY_SECTIONS` | the current draft of each section, with its word and citation counts |
| `SURVEY_REVIEWS` | each referee pass |
| `SURVEY_LEDGER` | every step of every run |
""",
         code(lift(H / "tables.py", "SURVEY_TABLES", "create_survey_tables")),
         code(lift(H / "tables.py", "new_id", "now_iso", "ledger", "paper_ledger", "reset_survey_tables")),
         code('''create_survey_tables()
print({t: rows(f"SELECT COUNT(*) AS n FROM {t}")[0]["n"] for t in SURVEY_TABLES})'''),
         md("### Settings and clients"),
         code(lift(H / "config.py", "SurveyConfig", "CFG", "_clients", "claude", "tavily")),
         md("### Typed answers\n\nEvery model call is constrained to a JSON schema. The harness receives objects, never prose to parse, and the instructions say that source text is data."),
         code(lift(H / "llm.py", "USAGE", "strict", "ask_typed")),
         md("### Search, read, store, and ask by meaning ⭐"),
         code(lift(H / "evidence.py", "canonical", "clean_title", "search_web", "read_pages", "known_urls", "keep_source")),
         code(lift(H / "evidence.py", "gather_for_section", "sources_for", "similar_sources", "source_text")),
         md("### One real gather\n\nA scoped search on scholarly venues for one section, six pages read in full and stored with their embeddings, then a question to the library by meaning."),
         code('''SAMPLE_PAPER = "PAPER-sample-" + uuid.uuid4().hex[:4]
execute("INSERT INTO survey_papers (paper_id, subject, status) VALUES (:1, :2, 'SAMPLE')",
        [SAMPLE_PAPER, "agent harness engineering"])
kept = gather_for_section(SAMPLE_PAPER, {"key": "context", "title": "Context engineering and memory"},
                          ["context engineering for LLM agents survey", "agent memory management long-horizon tasks"])
for source in kept:
    print(f"{source['chars']:>7} chars  {source['title'][:70]}")
print()
for hit in similar_sources(SAMPLE_PAPER, "how agents compress and manage their context window", limit=3):
    print(f"distance {hit['distance']:.3f}  {hit['title'][:70]}")'''),
         star=True),
    part("Reading into notes", """
Reading is a typed call too. The model reads a batch of sources and returns one note
per source in a fixed shape: kind, year, venue, contribution, method, evidence, up to
five claims a survey could cite it for, and a relevance grade. The harness stores
notes as they are made, so a run that stops mid-way keeps what it read.
""",
         code(lift(H / "reading.py", "READ", "NOTE_SCHEMA", "read_sources")),
         code(lift(H / "reading.py", "read_all_unread", "notes_for")),
         md("### Read the sample sources"),
         code('''done = read_all_unread(SAMPLE_PAPER, "agent harness engineering")
for note in notes_for(SAMPLE_PAPER)[:4]:
    print(f"[{note['source_id']}] {note['title'][:60]} ({note['year'] or 'n.d.'}, {note['kind']}, {note['relevance']})")
    print("   ", note["contribution"][:160])
    print("    claims:", len(note["claims"]))
print(done, "notes;", USAGE)'''),
         ),
    part("Organising, writing, reviewing, assembling", """
Four more typed calls, and the rules around them.

- **Scope** plans the paper: research questions, inclusion criteria, and an outline
  where each section has a purpose and its own search queries.
- **Organise** builds the framework from the notes: categories with definitions, the
  assignment of sources to categories, a comparison table, and open questions.
- **Write** produces one section from an evidence pack: the section's own sources plus
  the nearest sources from the library. A citation is `[S-id]`, and only ids in the
  pack are allowed; the harness strips any other.
- **Review** is a referee pass. Beside it, the harness applies its own rules: a minimum
  of words and citations per section, and every citation must resolve.
- **Assemble** numbers citations in order of first use, builds the reference list from
  the library, asks for an abstract, and appends how the paper was made.
""",
         code(lift(H / "writing.py", "SCOPE", "SCOPE_SCHEMA", "scope_paper")),
         code(lift(H / "writing.py", "TAXONOMY", "TAXONOMY_SCHEMA", "build_taxonomy")),
         code(lift(H / "writing.py", "WRITE", "WRITE_SCHEMA", "evidence_pack", "write_section")),
         code(lift(H / "writing.py", "drafts", "check_drafts", "REVIEW", "REVIEW_SCHEMA", "review_paper")),
         code(lift(H / "writing.py", "ABSTRACT_SCHEMA", "assemble_paper")),
         code(lift(H / "writing.py", "to_html")),
         md("### The plan for this subject ⭐\n\nOne call. The outline is what a person will be asked to approve before any source is read."),
         code('''plan = scope_paper("agent harness engineering", "researchers and engineers building agent systems")
print(plan["title"])
for question in plan["research_questions"]:
    print("-", question)
for section in plan["sections"]:
    print(f"{section['kind']:<12} {section['title']}")'''),
         star=True),
    part("The research graph", """
The graph has two shapes in one. The first is fixed: scope, ask, gather, read,
organise, write, review, assemble, ask, publish. The second is decided as it runs:
how many `gather` and `write` tasks there are (one per section, made with `Send`), and
whether the review sends the run back to gather more. Every task writes to the
database as it works, so a run that stops keeps everything it has done.

```mermaid
flowchart TB
  S([start]) --> SC[scope] --> OR{{outline_review · interrupt}}
  OR -->|revise| RS[rescope] --> SC
  OR -->|reject| CL[close] --> E1([end])
  OR -->|approve · Send per section| G[gather ×N]
  G --> RD[read] --> OG[organise]
  OG -->|Send per section| W[write ×N]
  W --> RV[review]
  RV -->|gaps and rounds left| G
  RV --> AS[assemble] --> PR{{publication_review · interrupt}}
  PR -->|approve| PB[publish] --> E2([end])
  PR -->|reject| CL
```
""",
         code(lift(H / "graph.py", "OUTPUT_DIR", "EVIDENCE_KINDS", "PaperState", "note_step", "maybe_crash", "set_status")),
         md("### Scope and the first gate"),
         code(lift(H / "graph.py", "scope", "outline_review", "after_outline_review", "rescope")),
         md("### Gather, read, organise\n\n`gather` receives a task made by `Send`, not the whole state; `read` reads unread sources four at a time on a small thread pool."),
         code(lift(H / "graph.py", "gather", "read", "organise")),
         md("### Write, review, and the bounded loop"),
         code(lift(H / "graph.py", "fan_out_write", "write", "review", "after_review")),
         md("### Assemble, the second gate, publish"),
         code(lift(H / "graph.py", "assemble", "publication_review", "after_publication_review", "publish", "close")),
         md("### Wire it ⭐"),
         code(lift(H / "graph.py", "build_graph")),
         code(lift(H / "graph.py", "_runtime", "durable_graph", "config_for", "outcome")),
         code(lift(H / "graph.py", "start_paper", "resume_paper", "continue_paper")),
         code('''graph = durable_graph()
print(len(graph.get_graph().nodes), "nodes; concurrency capped at", config_for("x")["max_concurrency"], "parallel tasks")'''),
         star=True),
    part("Write the paper", """
The whole run, with both gates. Scoping takes half a minute. After the outline is
approved, gathering, reading, organising and writing take about ten minutes and a few
dozen model calls, and the run stops again with the paper assembled.
""",
         md("### Scope, and stop at the outline ⭐"),
         code('''PAPER = "PAPER-" + uuid.uuid4().hex[:6]
started = time.perf_counter()
out = start_paper("agent harness engineering", paper_id=PAPER)
print(f"{time.perf_counter() - started:.0f} s | status {out['status']} | next {out['next']} | checkpoints {out['checkpoints']}")
print(out["title"])
for section in out["outline"]:
    print(f"{section['position']:>2}. {section['kind']:<12} {section['title']}")'''),
         md("### Approve the outline and let it run ⭐\n\nThis is the long cell. The ledger below it shows what happened, in order."),
         code('''started = time.perf_counter()
out = resume_paper(PAPER, "approve")
print(f"{time.perf_counter() - started:.0f} s | status {out['status']} | sources {out['sources']} | "
      f"model calls {out['usage']['calls']} | checkpoints {out['checkpoints']}")
for section in out["sections"]:
    print(f"{section['title'][:50]:<50} {section['words']:>5} words {section['citations']:>3} citations  round {section['round']}")'''),
         md("### What the referee said, and what the rules found"),
         code('''review = out["review"]
print("verdict:", review["verdict"], "| harness rules:", out["problems"] or "all met")
print(review["summary"][:600])
for section in review["sections"]:
    if section["unsupported_claims"] or section["missing"]:
        print(f"- {section['key']}: {len(section['unsupported_claims'])} unsupported, missing: {'; '.join(section['missing'])[:120]}")'''),
         star=True),
    part("Publish, and read the evidence", """
The second gate. Approving it writes the Markdown and HTML files. Then the tables
say what the paper is made of.
""",
         md("### Approve the paper ⭐"),
         code('''counts = out["paper"]["counts"]
print(f"{counts['sections']} sections, {counts['words']} words, {counts['sources_read']} sources read, "
      f"{counts['sources_cited']} cited")
print(out["paper"]["abstract"][:700])
out = resume_paper(PAPER, "approve")
print("\\nstatus:", out["status"])
print("files:", out["paper"]["markdown"], out["paper"]["html"])'''),
         md("### The paper's first lines, and its references"),
         code('''text = Path(out["paper"]["markdown"]).read_text()
print(text[:1200])
print("...")
print("\\n".join(out["paper"]["references"][:8]))'''),
         md("### The library behind it"),
         code('''print(rows("""SELECT section_key, COUNT(*) AS sources, ROUND(AVG(content_chars)) AS avg_chars
                 FROM survey_sources WHERE paper_id = :p GROUP BY section_key ORDER BY 1""", {"p": PAPER}))
print(rows("SELECT relevance, COUNT(*) AS n FROM survey_notes WHERE paper_id = :p GROUP BY relevance", {"p": PAPER}))
for entry in paper_ledger(PAPER):
    print(f"{entry['node']:<20} {entry['kind']:<10} {str(entry['detail'])[:80]}")'''),
         code('''print("checkpoints:", rows("SELECT COUNT(*) AS n FROM checkpoints WHERE thread_id = :p", {"p": PAPER})[0]["n"])
print("model calls:", USAGE)
def close_pools():
    for name, found in list(_pools.items()):
        found.close(force=True); _pools.pop(name, None)
close_pools()'''),
         star=True),
]

CLOSING = [
    md("""
## Key takeaways

1. **Deep research is a loop the harness owns.** The model reads and writes; the
   harness decides what to search, when to stop, and what counts as good enough.
2. **Evidence is a library, not a prompt.** Pages are stored with their text and an
   embedding inside the database, so a writer can ask for more by meaning and every
   citation resolves to a page.
3. **Reading is typed.** Notes with a fixed shape are what the framework and the
   sections are built from, so the writer never sees raw pages it could be steered by.
4. **Parallel where the work is independent.** Sections are gathered and written with
   one `Send` each; concurrency is capped so a small database is not flooded.
5. **Two kinds of quality gate.** The harness checks what it can count (words,
   citations, resolution); the model judges what it cannot; a person decides twice.
6. **Bounded loops.** The round is in the state, so a revision can gather more
   evidence once and not forever.
7. **A run that stops keeps its work.** Every task writes to the database; LangGraph
   keeps the writes of tasks that finished, and a continued run redoes only what did not.

## What the appbook adds

`part_2/advanced/deep_research/appbook` runs this harness as an application: a form for
the subject, the outline to approve, live progress by section, the evidence library
searchable by meaning, the referee's findings, the paper itself, and the data explorer.
"""),
]

if __name__ == "__main__":
    out = build("Write a survey paper: a deep-research harness", LEAD + ARCHITECTURE +
                "\n**One paper through the harness**\n" + REQUEST_PATH, PARTS, OUT, DIAGRAMS, CLOSING)
    print("wrote", out)
