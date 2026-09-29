"""Skills with progressive disclosure: manifests always visible, one body on demand.

A manifest is a name and a sentence. A body is a procedure. Every turn carries
the seven manifests; a body enters the context only when ``load_skill`` asks
for it. The registry lives in ``ppa_skill_registry`` so a body can be reviewed
and hashed like any other approved artefact.
"""
from __future__ import annotations

import hashlib
import re
from typing import Any

from backend.core import store

SKILLS: dict[str, dict[str, Any]] = {
    "morning-brief": {
        "description": "Compose the start-of-day brief: what needs attention first, today's calendar "
                       "with rule breaks, and at most three top tasks.",
        "triggers": ["morning", "brief", "start", "day", "today", "attention"],
        "body": """# Morning brief
1. Call `triage_inbox`, `day_overview` for today and `task_list`.
2. Lead with the first triage row: it has the lowest attention rank. Give the sender, the subject, why it ranks first and the thread ID.
3. List today's events in time order with their IDs. For every event in `meeting_rule_violations`, say which rule it breaks and offer to propose a later time. Responding to an invitation needs approval.
4. List at most three tasks in governed order and mark the urgent ones. If there are no tasks yet, say so and offer to triage the inbox.
5. Name the free slots that can hold a focus session.
6. Report quarantined threads in one line, by ID. Do not open them.
7. Keep it short enough to read in one minute. Sections: Needs you first, Today, Top tasks, Free for focus, Held back.""",
    },
    "inbox-triage": {
        "description": "Sort the inbox by governed category and turn actionable threads into tasks "
                       "and unsent drafts.",
        "triggers": ["triage", "inbox", "email", "mail", "actionable", "tasks", "sort"],
        "body": """# Inbox triage
1. Call `triage_inbox`. The category, VIP flag, tracking and quarantine in each row are decided by the harness. Do not overrule them.
2. `task`: call `task_add` with `source_type` "mail" and `source_ref` set to the thread ID. Read the thread first when you need a due date or a better estimate; set `due_at` only when the message states one.
3. `reply`: call `task_add` for the reply, then `mail_create_draft` addressed to the sender. Never send. For a meeting invitation, create the task only; responding is a separate, approved action.
4. `delegate`: draft a hand-over note to the suggested owner and create one task to follow up.
5. `tracked`: cite the existing task ID. Create nothing.
6. `archive`: count them. Create nothing.
7. `quarantine`: report the thread ID and the pattern names. Do not open, answer or forward it.
8. Summarise as a short list per category, with task IDs and draft IDs.""",
    },
    "meeting-prep": {
        "description": "Prepare a short brief for one meeting from its thread, its page and the last notes.",
        "triggers": ["meeting", "prep", "prepare", "call", "before", "agenda", "brief"],
        "body": """# Meeting prep
1. Find the event: use the ID given, or `day_overview` to pick the next meeting.
2. Call `meeting_prep` with the event ID. It returns the event, the people, the related thread, the related page and the owner's open actions.
3. If earlier mail on the same matter would help, call `mail_search_threads` with label "ALL" and the subject words.
4. Write the brief in this order: purpose in one sentence; who will be there and who is a VIP; what they are waiting for; facts to have ready; the owner's open actions; two questions worth asking.
5. Stay under 150 words. Quote figures exactly as the sources give them and cite thread and page IDs.""",
    },
    "time-block-tasks": {
        "description": "Place the top tasks into today's free slots and ask for approval before "
                       "writing to the calendar.",
        "triggers": ["time", "block", "schedule", "plan", "slots", "calendar", "top", "tasks"],
        "body": """# Time-block tasks
1. Call `task_list` and take the top three in governed order, unless specific tasks were named.
2. Call `plan_time_blocks` with those task IDs. The harness sizes each block by estimated Pomodoros and avoids every existing event.
3. For each block call `calendar_create_event` with kind "focus", the block's start and end, the task title as the title and only the owner as attendee. Issue all the calls together so they are approved in one step.
4. The run pauses for approval. If a block is declined, do not retry it. Say what was not written and leave the plan in `/plans/today.md`.
5. Report the blocks that were created with their event IDs, and any task that did not fit.""",
    },
    "focus-session": {
        "description": "Start, check or stop a Pomodoro tied to a task, and park distractions for the break.",
        "triggers": ["pomodoro", "focus", "timer", "session", "deep", "work", "distraction"],
        "body": """# Focus session
1. Resolve the task with `task_list`. If nothing matches, create the task with `task_add` first.
2. Call `pomodoro_start` with the task ID. Use the owner's default length unless a length was given.
3. While a session runs, anything that is not the task goes to `capture_note`. Do not act on it now.
4. `pomodoro_status` answers how long is left. `pomodoro_stop` ends the session early and records why.
5. When the session ends, list the parked distractions and suggest a break.""",
    },
    "end-of-day-wrap": {
        "description": "Close the workday: what was done, what carries over, tomorrow's first block, "
                       "and which notes to keep.",
        "triggers": ["end", "day", "wrap", "evening", "close", "tomorrow", "carry"],
        "body": """# End-of-day wrap
1. Call `end_of_day_data`. It returns what was completed today, what was planned but is still open, the focus minutes and tomorrow's first free slot.
2. Report three things: done, carried over, and tomorrow's first block with the task that should fill it.
3. List the scratch notes marked for promotion. Notes not marked are left behind.
4. Call `end_workday`. It ends the session, promotes the marked notes and counts one more slip for every planned task that is still open.
5. Close with one sentence. No advice unless something has now slipped twice.""",
    },
    "weekly-review": {
        "description": "Review the week: planned versus done, where time went, what keeps slipping "
                       "and what to drop.",
        "triggers": ["weekly", "week", "review", "slipping", "drop", "time", "went"],
        "body": """# Weekly review
1. Call `weekly_review_data`.
2. Planned versus done: tasks planned or due in the period against tasks completed, then focus minutes planned against minutes achieved.
3. Where time went: minutes by task, largest first, with unplanned time named as such.
4. What keeps slipping: tasks carried over at least twice. Suggest a smaller next step for each.
5. What to drop: open tasks with no due date that nobody has touched for 30 days.
6. End with one decision for next week. If the period holds no data yet, say so plainly.""",
    },
}


def estimate_tokens(text: str) -> int:
    """A stated approximation: four characters to a token."""
    return max(1, round(len(text) / 4))


def sync_registry() -> None:
    """Mirror the approved skills into ``ppa_skill_registry`` with a hash of each body."""
    stamp = store.real_now()
    for name, spec in SKILLS.items():
        store.execute(
            "INSERT INTO ppa_skill_registry(skill_name,description,triggers,body,body_sha256,status,updated_at) "
            "VALUES (?,?,?,?,?,'ACTIVE',?) ON CONFLICT(skill_name) DO UPDATE SET "
            "description=excluded.description,triggers=excluded.triggers,body=excluded.body,"
            "body_sha256=excluded.body_sha256,updated_at=excluded.updated_at",
            (name, spec["description"], ",".join(spec["triggers"]), spec["body"],
             hashlib.sha256(spec["body"].encode()).hexdigest(), stamp), trace=False)


def manifests() -> list[dict[str, Any]]:
    """Compact metadata only: what every turn carries."""
    return [{"name": item["skill_name"], "description": item["description"]} for item in store.rows(
        "SELECT skill_name,description FROM ppa_skill_registry WHERE status='ACTIVE' ORDER BY rowid")]


def manifest_text() -> str:
    return "\n".join(f"- {item['name']}: {item['description']}" for item in manifests())


def load(name: str) -> dict[str, Any] | None:
    """Disclose one full body."""
    found = store.row("SELECT * FROM ppa_skill_registry WHERE skill_name=? AND status='ACTIVE'", (name,))
    if found is None:
        return None
    return {"name": found["skill_name"], "description": found["description"], "body": found["body"],
            "body_sha256": found["body_sha256"], "tokens": estimate_tokens(found["body"])}


def rank(query: str) -> list[dict[str, Any]]:
    """Rank manifests for a request by overlap with their triggers and descriptions."""
    words = set(re.findall(r"[a-z]+", query.lower()))
    ranked = []
    for item in store.rows("SELECT * FROM ppa_skill_registry WHERE status='ACTIVE' ORDER BY rowid"):
        hits = words & set(item["triggers"].split(","))
        described = words & set(re.findall(r"[a-z]+", item["description"].lower()))
        name_hits = words & set(item["skill_name"].split("-"))
        score = len(hits) * 3 + len(name_hits) * 3 + len(described)
        if hits or name_hits:
            ranked.append({"name": item["skill_name"], "description": item["description"],
                           "score": score, "matched": sorted(hits | name_hits)})
    return sorted(ranked, key=lambda entry: (-entry["score"], entry["name"]))[:3]


def token_comparison(selected: str | None) -> dict[str, Any]:
    rows = store.rows("SELECT * FROM ppa_skill_registry WHERE status='ACTIVE'")
    manifest_tokens = estimate_tokens(manifest_text())
    every_body = sum(estimate_tokens(item["body"]) for item in rows)
    one_body = next((estimate_tokens(item["body"]) for item in rows if item["skill_name"] == selected), 0)
    return {"manifests_only": manifest_tokens, "dump_everything": manifest_tokens + every_body,
            "progressive": manifest_tokens + one_body,
            "saved": every_body - one_body, "method": "estimated at four characters per token"}


def disclose(query: str) -> dict[str, Any]:
    """Retrieve manifests, then load only the top match."""
    matched = rank(query)
    selected = matched[0]["name"] if matched else None
    return {"query": query, "manifests": manifests(), "matched": matched,
            "disclosed_skill": load(selected) if selected else None,
            "token_comparison": token_comparison(selected),
            "retrieval": "keyword overlap with triggers (vector search over the registry in the notebook)",
            "sequence": ["retrieve compact manifests", "select the top approved match",
                         "load one full body"]}
