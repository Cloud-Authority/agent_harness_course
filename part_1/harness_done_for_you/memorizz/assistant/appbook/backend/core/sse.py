"""Server-Sent Events helper with a zero-extra-dependency fallback."""
from __future__ import annotations

import json

try:
    from sse_starlette.sse import EventSourceResponse
except ImportError:  # FastAPI/Starlette can still stream the legacy acceptance route.
    from starlette.responses import StreamingResponse

    class EventSourceResponse(StreamingResponse):
        def __init__(self, generator):
            async def encode():
                async for item in generator:
                    event = item.get("event", "message")
                    data = item.get("data", "")
                    if not isinstance(data, str):
                        data = json.dumps(data)
                    yield f"event: {event}\ndata: {data}\n\n"

            super().__init__(encode(), media_type="text/event-stream")


def sse_response(gen):
    return EventSourceResponse(gen)
