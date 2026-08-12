"""Request / response models shared across routers."""
from __future__ import annotations

from pydantic import BaseModel, Field


class ChatReq(BaseModel):
    thread_id: str = "demo-thread"
    session_id: str | None = None
    message: str


class BriefReq(BaseModel):
    user_id: str = "planner-01"


class AskReq(BaseModel):
    thread_id: str = "demo-thread"
    question: str


class MemoryReq(BaseModel):
    memory_type: str
    content: str
    user_id: str = "planner-01"
    thread_id: str | None = None
    ttl_days: int | None = None


class MemoryUpdateReq(BaseModel):
    content: str
    ttl_days: int | None = None


class ToolReq(BaseModel):
    name: str
    arguments: dict = {}


class SqlReq(BaseModel):
    sql: str


class QueryReq(BaseModel):
    query: str


class ScratchWriteReq(BaseModel):
    session_id: str = "appbook-session"
    thread_id: str = "appbook-thread"
    path: str = "/plans/current.md"
    content: str
    promote_on_end: bool = False


class SessionReq(BaseModel):
    session_id: str = "appbook-session"
    thread_id: str = "appbook-thread"
    user_id: str = "planner-01"


class ActionDraftReq(BaseModel):
    action_type: str
    payload: dict
    thread_id: str = "appbook-thread"


class CartLine(BaseModel):
    sku: str = Field(min_length=1, max_length=32)
    quantity: int = Field(ge=1, le=10)


class CheckoutReq(BaseModel):
    customer_name: str = Field(default="Demo Shopper", min_length=1, max_length=80)
    email: str = Field(default="shopper@example.test", min_length=3, max_length=160)
    lines: list[CartLine] = Field(min_length=1, max_length=20)
