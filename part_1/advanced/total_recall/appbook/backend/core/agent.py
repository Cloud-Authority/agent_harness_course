"""Grounded agent loop driven by GPT-5.5 through the Responses API."""

from __future__ import annotations

import asyncio
import json
from typing import Any

from ..config import settings
from . import db, memory, registries
from .llm_client import client, function_calls, request_options, response_items, response_text


SYSTEM = (
    "You are a retail-analytics agent. Ground yourself in the schema catalog "
    "before writing SQL. Reuse proven workflows and Skills. Prefer "
    "create_automation when the user requests recurring work. Use only the "
    "provided Tools and answer concisely."
)
ESSENTIAL = [
    "run_sql",
    "list_sources",
    "create_automation",
    "search_memory",
    "recall_workflow",
    "find_skill",
    "load_skill",
]
_JSON_TYPE = {
    "string": "string",
    "number": "number",
    "integer": "integer",
    "boolean": "boolean",
}


def _select_tool_names(query: str, k: int = 8) -> list[str]:
    names = [row["NAME"] for row in registries.retrieve_tools(query, k)]
    return [name for name in dict.fromkeys(names + ESSENTIAL) if name in registries.TOOLS]


def _openai_tools(names: list[str]) -> list[dict]:
    tools = []
    for name in names:
        schema = registries.get_tool_schema(name)
        if not schema:
            continue
        properties = {
            parameter: {"type": _JSON_TYPE.get(kind, "string")}
            for parameter, kind in (schema.get("parameters") or {}).items()
        }
        tools.append(
            {
                "type": "function",
                "name": name,
                "description": schema.get("description", ""),
                "parameters": {
                    "type": "object",
                    "properties": properties,
                    "required": list(properties),
                    "additionalProperties": False,
                },
                "strict": True,
            }
        )
    return tools


async def run_agent(prompt: str, thread_id: str = "appbook"):
    await asyncio.to_thread(memory.add_turn, thread_id, "user", prompt)

    catalog = await asyncio.to_thread(db.semantic_search, prompt, 5)
    manifest = await asyncio.to_thread(registries.build_skill_manifest, prompt, 4)
    card = await asyncio.to_thread(memory.context_card, thread_id) or ""
    recipes = await asyncio.to_thread(memory.recall_workflow, prompt, 3)
    recipe_lines = [
        f"{row['INTENT']} (x{row['OCCURRENCES']})" for row in (recipes or [])
    ]
    tool_names = await asyncio.to_thread(_select_tool_names, prompt)
    tools = _openai_tools(tool_names)

    developer = (
        f"{SYSTEM}\n\n# SCHEMA CATALOG\n"
        + "\n".join(str(item["CONTENT"]) for item in catalog)
        + f"\n\n# SKILLS (manifest)\n{manifest}"
        + (("\n\n# PROVEN RECIPES\n" + "\n".join(recipe_lines)) if recipe_lines else "")
        + f"\n\n# WORKING MEMORY (context card)\n{card}"
    )

    yield {
        "type": "context",
        "provider": "OpenAI Responses API",
        "model": settings.model,
        "catalog": [str(item["CONTENT"])[:90] for item in catalog],
        "skills": manifest,
        "recipes": recipe_lines,
        "tools": tool_names,
        "card": card[:1200],
        "est_tokens": len(developer) // 4,
        "system_chars": len(developer),
    }

    items: list[Any] = [
        {"role": "developer", "content": developer},
        {"role": "user", "content": prompt},
    ]
    used: list[str] = []
    answer = ""

    for _ in range(10):
        request = request_options(input=items)
        if tools:
            request.update(
                {
                    "tools": tools,
                    "tool_choice": "auto",
                    "parallel_tool_calls": True,
                    "include": ["reasoning.encrypted_content"],
                }
            )
        response = await asyncio.to_thread(client.responses.create, **request)
        answer = response_text(response)
        if answer:
            yield {"type": "delta", "text": answer}
        calls = function_calls(response)
        if not calls:
            break
        items.extend(response_items(response))
        for call in calls:
            name, arguments, call_id = (
                call["name"],
                call["arguments"],
                call["call_id"],
            )
            used.append(name)
            yield {"type": "tool_call", "name": name, "args": arguments}
            try:
                result = await asyncio.to_thread(registries.TOOLS[name], **arguments)
            except Exception as exc:
                result = {"error": str(exc)}
            payload = json.dumps(result, default=str)
            yield {"type": "tool_result", "name": name, "preview": payload[:600]}
            items.append(
                {"type": "function_call_output", "call_id": call_id, "output": payload[:6000]}
            )
    else:
        closing_input = items + [
            {
                "role": "developer",
                "content": "The Tool budget is exhausted. Answer from gathered evidence now.",
            }
        ]
        response = await asyncio.to_thread(
            client.responses.create,
            **request_options(input=closing_input),
        )
        answer = response_text(response)
        if answer:
            yield {"type": "delta", "text": answer}

    if answer:
        await asyncio.to_thread(memory.add_turn, thread_id, "assistant", answer)
    if used:
        await asyncio.to_thread(
            memory.capture_workflow,
            prompt,
            [{"tool": name} for name in used],
            list(dict.fromkeys(used)),
        )
    yield {"type": "done", "tools_used": used}
