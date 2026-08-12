"""Chapter 1: the single substrate."""
from fastapi import APIRouter

from backend.core import store
from backend.core.component_map import component_map

router = APIRouter(prefix="/api/foundation", tags=["foundation"])


@router.get("/status")
async def status():
    return {"chapter": "Component Map & Foundation", **store.status(), **component_map(),
            "teaching_point": "Business data and memories about decisions on that data share one transaction, backup and security boundary."}
