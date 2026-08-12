"""Stage 4 — progressive skill disclosure with a visible token comparison."""
import json
import _bootstrap  # noqa: F401
from backend.core.skills import disclose

print(json.dumps(disclose("Prepare my morning brief"), indent=2))
