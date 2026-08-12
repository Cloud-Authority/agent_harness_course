"""Chapter 7: reconstruct the process-scoped agent over persistent memory."""
from fastapi import APIRouter

from backend.core.agent import get_agent

router = APIRouter(prefix="/api/the_restart", tags=["the_restart"])


@router.get("/status")
async def status():
    return {"chapter": "The Restart", "ready": True,
            "note": "The button reconstructs every in-process object. scripts/restart_proof.py performs the genuine two-process acceptance test."}


@router.post("/run")
async def run():
    before = get_agent().memory.exclusions()
    agent = get_agent(restart=True)
    result = agent.run("Morning brief.", thread_id="after-restart")
    return {"process_objects_rebuilt": True, "preferences_before": before,
            "preferences_after": agent.memory.exclusions(), "result": result}
