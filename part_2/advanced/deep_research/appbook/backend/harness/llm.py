"""One way to ask the model for a typed answer."""
from __future__ import annotations

import json
from typing import Any

from .config import CFG, claude

USAGE: dict[str, int] = {"calls": 0, "input_tokens": 0, "output_tokens": 0}


def strict(schema: dict[str, Any]) -> dict[str, Any]:
    """Structured output wants every object closed: no property the schema does not name."""
    if schema.get("type") == "object":
        schema = {**schema, "additionalProperties": False,
                  "properties": {k: strict(v) for k, v in schema.get("properties", {}).items()}}
    if schema.get("type") == "array":
        schema = {**schema, "items": strict(schema["items"])}
    return schema


def ask_typed(instructions: str, request: str, name: str, schema: dict[str, Any],
              max_tokens: int = 8000, effort: str | None = None) -> dict[str, Any]:
    """The model's reply is constrained to the schema, so the harness never parses prose.

    Text that comes from the web is data, and the instructions say so. The name is
    kept in the trace so the ledger says which typed question was asked.
    """
    with claude().messages.stream(          # streamed, so a long answer is not refused up front
            model=CFG.model, max_tokens=max_tokens, system=instructions,
            messages=[{"role": "user", "content": request}],
            output_config={"effort": effort or CFG.effort, "format": {"type": "json_schema", "schema": strict(schema)}}) as stream:
        reply = stream.get_final_message()
    USAGE["calls"] += 1
    USAGE["input_tokens"] += reply.usage.input_tokens
    USAGE["output_tokens"] += reply.usage.output_tokens
    if reply.stop_reason == "max_tokens" and max_tokens < 32_000:      # cut off mid-answer: ask again with more room
        return ask_typed(instructions, request, name, schema, max_tokens=min(max_tokens * 2, 32_000), effort=effort)
    text = "".join(block.text for block in reply.content if block.type == "text")
    try:
        return json.loads(text)
    except json.JSONDecodeError as error:
        raise RuntimeError(f"The model's {name} was not valid JSON: {text[:300]}") from error
