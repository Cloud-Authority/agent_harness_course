"""One live MemoRizz composition matching the standalone notebook.

The UI and routers do not reproduce provider, cache, skill, MCP, sandbox, or
orchestration setup.  They request a harness from this factory.  Keeping the assembly
behind one boundary is the package-level shape the course advocates.
"""
from __future__ import annotations

from functools import lru_cache

from backend.config import settings
from backend.core.course_runtime import (
    BUSINESS_TOOLS,
    ERPA_INSTRUCTION,
    MEMORY_ID,
    USER_ID,
)


@lru_cache(maxsize=1)
def create_live_memagent():
    """Build the Oracle-backed ERPA harness once per app process."""
    if not settings.oracle_configured or not settings.openai_api_key:
        raise RuntimeError(
            "Live MemoRizz requires ORACLE_DSN, ORACLE_USER, ORACLE_PASSWORD, "
            "and OPENAI_API_KEY."
        )

    from memorizz import (
        ApplicationMode,
        ContextPolicy,
        MemAgentBuilder,
        OracleConfig,
        OracleProvider,
        Persona,
        RoleType,
        Toolbox,
        ToolResultPolicy,
    )

    provider = OracleProvider(OracleConfig(
        user=settings.oracle_user,
        password=settings.oracle_password,
        dsn=settings.oracle_dsn,
        schema=settings.oracle_user,
        index_policy="lazy",
        in_database_embedding=settings.embedding_backend.lower() == "oracle",
        embedding_provider=None,
        embedding_config={"dimensions": 384, "install_if_missing": True},
        pool_min=1,
        pool_max=6,
        pool_increment=1,
    ))

    persona = Persona(
        name="ERPA",
        role=RoleType.ASSISTANT,
        goals=("Support Alex with inventory, merchandising, gross-margin and "
               "competitor decisions while keeping external actions reviewable."),
        background=("A senior retail-planning copilot that is concise, evidence-led, "
                    "and cautious with side effects."),
    )
    notion_token = settings.notion_mcp_token.strip()
    notion = {
        "name": "notion",
        "transport": "streamable_http",
        "url": "https://mcp.notion.com/mcp",
        "timeout": 45,
        "connect_timeout": 15,
        "max_retries": 2,
        "max_result_bytes": 2_000_000,
        "require_approval": True,
        "auth": ({"type": "bearer", "token": notion_token} if notion_token else {
            "type": "oauth", "redirect_uri": settings.notion_mcp_redirect_uri,
        }),
    }

    toolbox = Toolbox.from_functions(
        BUSINESS_TOOLS,
        memory_provider=provider,
        agent_id="erpa-appbook-live",
        user_id=USER_ID,
        augment=False,
    )

    builder = (
        MemAgentBuilder()
        .with_name("ERPA")
        .with_instruction(ERPA_INSTRUCTION)
        .with_persona(persona)
        .with_application_mode(ApplicationMode.ASSISTANT.value)
        .with_memory_provider(provider)
        .with_memory_ids(MEMORY_ID)
        .with_llm_config({
            "provider": "openai",
            "model": settings.openai_model,
            "api_key": settings.openai_api_key,
        })
        .with_toolbox(toolbox)
        .with_context_policy(ContextPolicy(tool_top_k=3))
        .with_tool_result_policy(ToolResultPolicy(offload_above_chars=500))
        .with_skill_retrieval(True, top_k=2, min_similarity=0.70)
        .with_mcp_servers([notion])
        .with_semantic_cache(enabled=True, threshold=0.86, scope="local")
        .with_continual_learning(True, config={
            "min_executions": 3,
            "min_success_rate": 0.80,
            "min_distinct_queries": 2,
            "require_shadow": True,
            "shadow_evaluation_enabled": True,
            "skill_injection_role": "user",
            "promotion_every_n_runs": 0,
        })
        .with_max_steps(20)
    )

    if settings.e2b_api_key:
        sandbox_config = {
            "provider": "e2b",
            "api_key": settings.e2b_api_key,
            "session_timeout": 120,
            "max_execution_timeout": 30,
            "allow_internet_access": False,
        }
        if settings.e2b_template:
            sandbox_config["template"] = settings.e2b_template
        builder.with_sandbox_provider(sandbox_config)
    agent = builder.build(validate=False)
    agent.agent_id = "erpa-appbook-live"
    if getattr(agent, "cache_manager", None) and getattr(agent.cache_manager, "cache_instance", None):
        agent.cache_manager.cache_instance.agent_id = agent.agent_id
    agent.save()
    return agent, provider


def live_capabilities() -> dict:
    """Describe the factory without constructing it or authenticating on import."""
    return {
        "provider": "OracleProvider",
        "embedding": "Oracle in-database / ALL_MINILM_L12_V2 / 384",
        "application_mode": "assistant",
        "tools": [function.__name__ for function in BUSINESS_TOOLS],
        "skill_source": "Oracle Skillbox",
        "mcp": ["Notion streamable HTTP"],
        "semantic_cache": "0.86 local scope / 15-minute application TTL",
        "sandbox": "E2B when configured",
        "builder": "MemAgentBuilder",
        "configured": settings.oracle_configured and bool(settings.openai_api_key),
    }
