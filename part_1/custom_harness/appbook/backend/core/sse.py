"""Server-Sent Events helper — every demo streams."""
from __future__ import annotations

from sse_starlette.sse import EventSourceResponse


def sse_response(gen):
    return EventSourceResponse(gen)
