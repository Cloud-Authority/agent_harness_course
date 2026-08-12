"""Stage 1 — one model decision, no memory."""
import json
import _bootstrap  # noqa: F401
from backend.core.llm_client import model

question = "Which regions are most profitable this quarter?"
print(json.dumps({"question": question, "decision": model.decide(question, {})}, indent=2))
