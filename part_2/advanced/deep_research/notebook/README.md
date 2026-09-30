# Write a survey paper: a deep-research harness

`advanced_survey_paper_harness.ipynb` builds a research harness that plans a survey on a
subject, asks a person to approve the outline, gathers scholarly sources into an evidence
library inside Oracle AI Database, reads them into typed notes, organises a framework,
writes every section from its evidence, reviews the draft, assembles the paper with
numbered references, and asks a person before it publishes.

Needs Docker (Oracle AI Database Free), `ANTHROPIC_API_KEY` and `TAVILY_API_KEY`. Ten to
fifteen minutes and about forty model calls to run; the paper is written to `output/`.
The paper the harness wrote for the course is in `../samples/`.

| Part | What it builds | Live |
|---|---|---|
| 1 | Environment | |
| 2 | The evidence library: search, read, store with an embedding, ask by meaning | ⭐ |
| 3 | Reading into notes | |
| 4 | Organising, writing, reviewing, assembling | ⭐ |
| 5 | The research graph | ⭐ |
| 6 | Write the paper: both gates | ⭐ |
| 7 | Publish, and read the evidence | ⭐ |

The notebook is generated from the appbook's harness modules by
`../../scripts/build_deep_research_notebook.py`.
