"""Stage 5 — discover trusted functions and read a governed outside signal."""
import json
import _bootstrap  # noqa: F401
from backend.core.tools import tool_registry

question = "Why did WarmLayer spike in the UK last week?"
print(json.dumps({"selected": tool_registry.retrieve(question),
                  "result": tool_registry.call(
                      "external_signal_search", region="UK", signal_type="weather"
                  )}, indent=2))
