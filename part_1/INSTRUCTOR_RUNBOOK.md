# ERPA instructor runbook

## Timing (two hours)

| Time | Beat |
|---|---|
| 00:00–00:12 | Frame harnesses: analytics are stateless; decisions are not |
| 00:12–00:27 | Build A notebook: store, MemAgent, four memories, tools |
| 00:27–00:37 | Build A five turns and two-process restart proof |
| 00:37–00:47 | Break/questions; compare the shared trace anatomy |
| 00:47–01:17 | Build B stages 1–2 live; tour semantic layer, skills and tools |
| 01:17–01:32 | Four-node loop and five identical turns; render the size chart |
| 01:32–01:42 | Cache lab: cold/warm LangSmith traces and no-model-span proof |
| 01:42–01:50 | Scheduled brief and Vercel frontend deployment |
| 01:50–02:00 | Failure modes, takeaways and Q&A |

The notebooks are the primary teaching artifacts. Appbooks are the fast visual tour and
the attendee exploration surface.

## Day-before preflight

1. Create both Python environments from their `requirements-live.txt` files; do not
   install during the session. Confirm the MemoRizz OpenAI model and custom-harness
   Anthropic model separately.
2. Generate/validate fixtures and run `part_1/tests/smoke_test.py`.
3. Confirm MongoDB collections and every Atlas vector search index reports ready.
4. Load the same CSV set to Oracle; confirm the read-only application role and thin-mode
   connection from the OCI backend.
5. Share **every** demo Notion page/database with the read-only integration. Search for
   Restock Playbook, Glossary and W39 notes through the MCP server.
6. Refresh the dedicated Google OAuth token. Confirm only Calendar read/create scopes;
   create a disposable 10:30 event and remove it manually after the test.
7. Run a Tavily cold-snap query and open the LangSmith project. Confirm memory reads and
   writes are separate spans.
8. Run both genuine restart proofs and the cache measurement. Cold has a model span;
   warm does not.
9. Trigger the scheduler job and confirm an in-app brief is persisted.
10. Build the Docker image and `next build` the Vercel client. Store the known-good
    deployment URLs in presenter notes.

## Morning-of checks

- Sign in only with the dedicated demo Google account and dedicated Notion workspace.
- Verify OAuth again; expiry often appears as an agent bug.
- Confirm LangSmith and Tavily keys—these were missing from the published O'Reilly
  prerequisite list.
- Open both populated notebooks at the first cell and both appbooks in separate tabs.
- Keep `part_1/_shared/demo_script.md`, cache measurement output and two restart-proof
  outputs one click away.
- Start a three-minute timer and rehearse Build A cold start end to end.

## Canonical demonstration

Do not paraphrase the five turns; equivalence is the teaching device.

1. `Morning brief.` Point to three new restocks and the explicit Berlin suppression.
2. `Why did WarmLayer spike in the UK last week?` Point to internal, Notion and Tavily
   evidence; say correlation is not proof.
3. `Show me ThermaCore stock across regions.` Point to red M/L bars and tail overhang.
4. `Which regions are most profitable this quarter — and don't show me Accessories
   again.` Point to the canonical margin formula and memory-write span.
5. Run the separate-process proof, then `Morning brief.` Point to persistence.

Build B optional sixth beat: repeat turn 2. A correct warm trace contains only the
boundary-cache lookup—no context assembly or model span.

## Failure fallback

The notebooks contain saved output after every code cell. If a live external system
fails, set `ERPA_MODE=local`, restart the appbook, and continue against identical
fixtures. Use the appbook Answer/Trace/JSON tabs to show the same evidence. Do not debug
OAuth or provision an index in front of the audience.

If Vercel is unavailable, show the already-built appbook Mission Control; it exercises
the same backend. If Tavily is unavailable, the fixture response is labelled as such.
If LangSmith is unavailable, use the comparable local trace and saved cache output.

## Guardrails to say aloud

No real PII, payments, commercial write-back, Notion writes, Calendar deletes,
multi-agent orchestration or long-horizon autonomy. The planner approves POs and
markdowns. The sandbox is fixed-operation and cannot execute arbitrary user code.
