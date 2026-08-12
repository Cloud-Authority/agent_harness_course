"""Chapter 2: persistent collections and vector-index status."""
from fastapi import APIRouter

from backend.core import store

router = APIRouter(prefix="/api/the_store", tags=["the_store"])


@router.get("/status")
async def status():
    return {"chapter": "The Store", **store.status()}
