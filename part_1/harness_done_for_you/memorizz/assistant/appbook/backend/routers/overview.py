"""Chapter 1: recognise the anatomy MemoRizz supplies."""
from fastapi import APIRouter

from backend.core import store

router = APIRouter(prefix="/api/overview", tags=["overview"])


@router.get("/status")
async def status():
    return {"chapter": "Overview", "ready": store.status()["ready"],
            "anatomy": ["persona", "memory provider", "toolbox", "control loop", "persistent store"],
            "teaching_point": "The harness is abstracted, but recall → decide → write remains visible."}
