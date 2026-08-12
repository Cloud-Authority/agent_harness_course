"""Request / response models shared across routers."""
from __future__ import annotations

from pydantic import BaseModel, Field


class ChatReq(BaseModel):
    thread_id: str = "demo-thread"
    message: str


class BriefReq(BaseModel):
    user_id: str = "planner-01"


class AskReq(BaseModel):
    thread_id: str = "demo-thread"
    question: str


class ToolReq(BaseModel):
    name: str
    arguments: dict = Field(default_factory=dict)


class MemoryReq(BaseModel):
    memory_type: str
    content: str
    user_id: str = "planner-01"


class WorkshopActionReq(BaseModel):
    payload: dict = Field(default_factory=dict)
