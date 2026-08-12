"""Stage 2 — OAMP-style semantic, episodic and procedural recall."""
import json
import _bootstrap  # noqa: F401
from backend.core.memory import memory_provider

print(json.dumps({"recalled": memory_provider.recall("Morning brief."),
                  "types": {k: len(v) for k, v in memory_provider.list().items()}}, indent=2))
