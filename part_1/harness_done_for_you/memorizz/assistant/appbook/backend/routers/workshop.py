"""Notebook-aligned workshop API plus live visualization streams."""
import json

from fastapi import APIRouter, HTTPException

from backend.core.course_runtime import (
    chapter_status,
    data_explorer_snapshot,
    orchestration_stream,
    run_action,
)
from backend.core.sse import sse_response
from backend.schemas import WorkshopActionReq

router = APIRouter(prefix="/api/workshop", tags=["workshop"])


@router.get("/status")
async def status():
    return chapter_status("overview")


@router.get("/chapters/{chapter_id}")
async def chapter(chapter_id: str):
    return chapter_status(chapter_id)


@router.get("/data")
async def data():
    return data_explorer_snapshot()


@router.get("/orchestration/stream")
async def orchestration(question: str = "Prepare Alex's morning brief"):
    async def events():
        async for item in orchestration_stream(question):
            yield {"event": item["kind"], "data": json.dumps(item, default=str)}

    return sse_response(events())


@router.post("/actions/{action}")
async def action(action: str, req: WorkshopActionReq):
    try:
        return run_action(action, req.payload)
    except KeyError as exc:
        raise HTTPException(404, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
