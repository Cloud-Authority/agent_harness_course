"""Persist appbook activity in MemoRizz's native Oracle observability stores.

The appbook has a deterministic teaching profile as well as a live MemAgent profile.
Both should be inspectable in ``memorizz ui``.  This bridge records the teaching
profile with the same conversation trace-bundle and TOOL_LOG contracts used by
``MemAgent.run_stream``; it never sends telemetry to a third-party service.
"""
from __future__ import annotations

from functools import lru_cache
import json
import logging
import re
import uuid
from typing import Any

from backend.config import settings

logger = logging.getLogger(__name__)

APPBOOK_AGENT_ID = "erpa-appbook-observability"
APPBOOK_AGENT_NAME = "ERPA · Appbook"
APPBOOK_MEMORY_ID = "erpa-memorizz-workshop"
APPBOOK_USER_ID = "alex-course-user"


def _safe_value(value: Any, *, depth: int = 0) -> Any:
    """Bound trace payloads and remove secrets or large inline artifacts."""
    if depth > 5:
        return "<maximum trace depth reached>"
    if isinstance(value, dict):
        safe = {}
        for key, item in value.items():
            lowered = str(key).lower()
            if any(token in lowered for token in ("password", "api_key", "token", "authorization", "secret")):
                safe[str(key)] = "<redacted>"
            elif lowered == "data_url" and isinstance(item, str):
                safe[str(key)] = f"<inline artifact omitted; {len(item)} characters>"
            else:
                safe[str(key)] = _safe_value(item, depth=depth + 1)
        return safe
    if isinstance(value, (list, tuple)):
        return [_safe_value(item, depth=depth + 1) for item in value[:50]]
    if isinstance(value, str):
        value = re.sub(r"(?i)(bearer\s+)[A-Za-z0-9._~+\-/=]+", r"\1<redacted>", value)
        return value if len(value) <= 12_000 else value[:12_000] + "…<truncated>"
    if value is None or isinstance(value, (bool, int, float)):
        return value
    return str(value)[:12_000]


@lru_cache(maxsize=1)
def _observability_agent():
    """Create or update the stable appbook agent in the shared Oracle provider."""
    if not settings.memorizz_observability:
        raise RuntimeError("ERPA_MEMORIZZ_OBSERVABILITY is disabled")
    if not settings.oracle_configured:
        raise RuntimeError("Oracle credentials are not configured")

    from memorizz import ApplicationMode, MemAgentBuilder, OracleConfig, OracleProvider

    provider = OracleProvider(OracleConfig(
        user=settings.oracle_user,
        password=settings.oracle_password,
        dsn=settings.oracle_dsn,
        schema=settings.oracle_user,
        lazy_vector_indexes=True,
        in_database_embedding=settings.embedding_backend.lower() == "oracle",
        embedding_provider=None,
        embedding_config={"dimensions": 384, "install_if_missing": True},
        pool_min=1,
        pool_max=3,
        pool_increment=1,
    ))
    agent = (
        MemAgentBuilder()
        .with_name(APPBOOK_AGENT_NAME)
        .with_instruction(
            "Capture ERPA appbook execution traces and tool evidence for local "
            "workshop observability. Do not execute user requests from this recorder."
        )
        .with_application_mode(ApplicationMode.ASSISTANT.value)
        .with_memory_provider(provider)
        .with_memory_ids(APPBOOK_MEMORY_ID)
        .with_max_steps(1)
        .build(validate=False)
    )
    agent.agent_id = APPBOOK_AGENT_ID
    agent.save()
    return agent, provider


def _request_text(action: str, payload: dict[str, Any]) -> str:
    for key in ("query", "question", "reference_id", "proposal_id"):
        if payload.get(key):
            return str(payload[key])
    return f"Appbook action: {action}"


def _answer_text(result: Any, error: Exception | None) -> str:
    if error is not None:
        return f"{type(error).__name__}: {error}"
    if isinstance(result, dict) and result.get("answer"):
        return str(result["answer"])
    return json.dumps(_safe_value(result), ensure_ascii=False, default=str)[:4_000]


def _tool_executions(result: Any) -> list[dict[str, Any]]:
    """Normalize appbook response variants into observable tool executions."""
    if not isinstance(result, dict):
        return []
    executions: list[dict[str, Any]] = []
    execution = result.get("execution")
    if isinstance(execution, dict):
        call = execution.get("call") if isinstance(execution.get("call"), dict) else execution
        tool_name = call.get("tool_name") or call.get("name")
        if tool_name:
            executions.append({
                "tool_name": str(tool_name),
                "arguments": call.get("arguments", call.get("arguments_used", {})),
                "result": execution.get("output", call.get("result", result.get("evidence", {}))),
                "tool_call_id": execution.get("tool_call_id") or call.get("tool_call_id"),
                "success": execution.get("status", "complete") not in {"failed", "error"},
            })
    tool = result.get("tool")
    if isinstance(tool, dict) and tool.get("tool_name") and not executions:
        executions.append({
            "tool_name": str(tool["tool_name"]),
            "arguments": tool.get("arguments_used", {}),
            "result": tool.get("result", {}),
            "tool_call_id": tool.get("tool_call_id"),
            "success": "error" not in tool,
        })
    trace = result.get("trace")
    decision = trace.get("decision", {}) if isinstance(trace, dict) else {}
    if not executions and decision.get("tools"):
        for tool_name in decision["tools"]:
            executions.append({
                "tool_name": str(tool_name), "arguments": {},
                "result": result.get("data", result.get("evidence", {})),
                "tool_call_id": None, "success": True,
            })
    return executions


def record_appbook_run(
    action: str,
    payload: dict[str, Any],
    result: Any = None,
    *,
    error: Exception | None = None,
    duration_ms: float = 0.0,
) -> dict[str, Any]:
    """Persist one appbook action as conversation, trace-bundle, and tool-log rows."""
    if not settings.memorizz_observability:
        return {"recorded": False, "reason": "disabled", "ui_url": settings.memorizz_ui_url}
    if not settings.oracle_configured:
        return {"recorded": False, "reason": "oracle_not_configured", "ui_url": settings.memorizz_ui_url}
    try:
        from memorizz.enums import Role

        agent, _ = _observability_agent()
        manager = agent.memory_manager
        thread_id = str(payload.get("thread_id") or f"appbook-{action}")
        query = _request_text(action, payload)
        answer = _answer_text(result, error)
        run_id = f"run-{uuid.uuid4().hex[:12]}"
        executions = _tool_executions(result)
        events: list[dict[str, Any]] = [{
            "trace_kind": "lifecycle",
            "title": f"Appbook action · {action}",
            "content": json.dumps({
                "run_id": run_id,
                "status": "error" if error else "complete",
                "duration_ms": round(duration_ms, 2),
                "profile": settings.execution_profile,
            }, ensure_ascii=False),
            "trace_id": run_id,
        }]

        for index, execution in enumerate(executions, start=1):
            tool_call_id = execution.get("tool_call_id") or f"{run_id}-tool-{index}"
            arguments = _safe_value(execution.get("arguments", {}))
            output = _safe_value(execution.get("result", {}))
            events.extend([
                {
                    "trace_kind": "tool_call",
                    "title": f"Tool Call · {execution['tool_name']}",
                    "content": json.dumps(arguments, ensure_ascii=False, default=str),
                    "trace_id": str(tool_call_id),
                },
                {
                    "trace_kind": "tool_result",
                    "title": f"Tool Result · {execution['tool_name']}",
                    "content": json.dumps(output, ensure_ascii=False, default=str),
                    "trace_id": f"result:{tool_call_id}",
                },
            ])
            manager.store_tool_log(
                tool_name=execution["tool_name"],
                arguments=arguments,
                result=output,
                memory_id=APPBOOK_MEMORY_ID,
                agent_id=APPBOOK_AGENT_ID,
                tool_call_id=str(tool_call_id),
                success=bool(execution.get("success", True)),
                error=str(error) if error else None,
                thread_id=thread_id,
                user_id=APPBOOK_USER_ID,
            )

        def save(role: Role, content: str) -> None:
            unit = manager.create_conversation_memory_unit(
                role=role,
                content=content,
                thread_id=thread_id,
                memory_id=APPBOOK_MEMORY_ID,
                agent_id=APPBOOK_AGENT_ID,
                user_id=APPBOOK_USER_ID,
            )
            manager.save_memory_unit(unit, APPBOOK_MEMORY_ID)

        save(Role.USER, query)
        save(Role.TOOL, json.dumps({"type": "trace_bundle", "version": 1, "events": events}, ensure_ascii=False))
        save(Role.ASSISTANT, answer)
        return {
            "recorded": True,
            "agent_id": APPBOOK_AGENT_ID,
            "memory_id": APPBOOK_MEMORY_ID,
            "thread_id": thread_id,
            "run_id": run_id,
            "trace_events": len(events),
            "tool_logs": len(executions),
            "ui_url": f"{settings.memorizz_ui_url}/traces?agent_id={APPBOOK_AGENT_ID}",
        }
    except Exception as exc:
        logger.warning("MemoRizz observability write failed for %s: %s", action, exc)
        return {
            "recorded": False,
            "reason": f"{type(exc).__name__}: {exc}",
            "ui_url": settings.memorizz_ui_url,
        }


def observability_status() -> dict[str, Any]:
    """Return readiness without exposing credentials."""
    status = {
        "enabled": settings.memorizz_observability,
        "oracle_configured": settings.oracle_configured,
        "agent_id": APPBOOK_AGENT_ID,
        "memory_id": APPBOOK_MEMORY_ID,
        "ui_url": settings.memorizz_ui_url,
    }
    if settings.memorizz_observability and settings.oracle_configured:
        try:
            agent, provider = _observability_agent()
            status.update({
                "ready": True,
                "provider": type(provider).__name__,
                "persisted_agent_id": agent.agent_id,
            })
        except Exception as exc:
            status.update({"ready": False, "error": f"{type(exc).__name__}: {exc}"})
    else:
        status["ready"] = False
    return status
