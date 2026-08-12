"""Stage 3 — business glossary → schema → canonical metric → provenance."""
import json
import _bootstrap  # noqa: F401
from backend.core.semantic import semantic_layer

print(json.dumps(semantic_layer.ask("Which regions are most profitable this quarter?", ["Accessories"]), indent=2))
