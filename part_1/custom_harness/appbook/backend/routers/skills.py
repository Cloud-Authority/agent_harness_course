"""Chapter 5: progressive skill disclosure and live token delta."""
from fastapi import APIRouter

from backend.core.skills import SKILLS, demonstrate_disclosure
from backend.schemas import QueryReq

router = APIRouter(prefix="/api/skills", tags=["skills"])


@router.get("/status")
async def status():
    return {"chapter": "Skills", "ready": True,
            "metadata": [{"name": name, "description": value["description"]} for name, value in SKILLS.items()]}


@router.post("/match")
async def match(req: QueryReq):
    return demonstrate_disclosure(req.query)
