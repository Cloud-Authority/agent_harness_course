"""Stage 6 — full graph, persistence, observability, scheduler and boundary cache."""
import json
import _bootstrap  # noqa: F401
from backend.core.agent import get_graph
from backend.core.cache import semantic_cache

semantic_cache.clear()
question = "Why did WarmLayer spike in the UK last week?"
cold = get_graph().run(question, "stage-06-cold")
warm = get_graph().run(question, "stage-06-warm")
print(json.dumps({"cold": cold["trace"], "warm": warm["trace"],
                  "warm_has_model_span": any(s["kind"] == "model" for s in warm["trace"]["spans"])}, indent=2))
