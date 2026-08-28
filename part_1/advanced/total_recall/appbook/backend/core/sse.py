"""Turn an async generator of dict events into a Server-Sent-Events response."""
from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Any

from fastapi.responses import StreamingResponse


def sse_response(events: AsyncIterator[dict[str, Any]]) -> StreamingResponse:
    async def stream():
        async for event in events:
            yield f"data: {json.dumps(event, default=str)}\n\n"
        yield "event: end\ndata: {}\n\n"

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
