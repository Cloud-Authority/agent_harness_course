"""Zero-credential acceptance suite for all ERPA workshop deliverables.

Run from the repository root with ``python part_1/tests/smoke_test.py``.  Build A and
Build B are exercised in separate interpreters because both intentionally expose a
top-level package named ``backend``.
"""
from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PART = ROOT / "part_1"
PYTHON = sys.executable


def run(command: list[str], *, cwd: Path = ROOT) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(command, cwd=cwd, text=True, capture_output=True)
    if result.returncode:
        raise AssertionError(
            f"Command failed ({result.returncode}): {' '.join(map(str, command))}\n"
            f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
        )
    return result


def run_json(source: str) -> dict:
    output = run([PYTHON, "-c", source]).stdout.strip()
    return json.loads(output.splitlines()[-1])


def test_dataset() -> None:
    seed = PART / "_shared/seed"
    source = f"""
import json, sys
from pathlib import Path
sys.path.insert(0, {str(seed)!r})
from generate_seed_data import DB_PATH, build_sqlite, validate
counts = build_sqlite(DB_PATH)
print(json.dumps({{"counts": counts, "validated": validate(DB_PATH)}}))
"""
    result = run_json(source)
    counts = result["counts"]
    assert counts == result["validated"]
    assert counts["products"] == 60 and counts["variants"] == 1029
    assert counts["customers"] == 5000 and counts["orders"] == 40000
    assert counts["order_lines"] == 90000 and counts["below_reorder"] == 4


def _build_acceptance(appbook: Path, build: str) -> dict:
    if build == "memorizz":
        imports = "from backend.core.agent import get_agent\nrunner = get_agent().run"
        stock_assertion = "assert len(turns[2]['data']['rows']) > 0"
        memory_import = "from backend.core.agent import get_agent\nexclusions = get_agent().memory.exclusions()"
    else:
        imports = "from backend.core.agent import get_graph\nrunner = get_graph().run"
        stock_assertion = "assert '<svg' in turns[2]['data']['chart_svg'] and turns[2]['data']['file_pointer'].startswith('dbfs://')"
        memory_import = "from backend.core.memory import memory_provider\nexclusions = memory_provider.exclusions()"

    source = f"""
import json, sys, uuid
sys.path.insert(0, {str(appbook)!r})
{imports}
messages = [
    "Morning brief.",
    "Why did WarmLayer spike in the UK last week?",
    "Show me ThermaCore stock across regions.",
    "Which regions are most profitable this quarter — and don't show me Accessories again.",
    "Morning brief.",
]
thread = "smoke-" + uuid.uuid4().hex
turns=[]
for index, message in enumerate(messages):
    kwargs = {{"thread_id": f"{{thread}}-{{index}}"}}
    if {build!r} == "custom": kwargs["bypass_cache"] = True
    turns.append(runner(message, **kwargs))
assert len(turns[0]["data"]["restock"]) == 3
assert [x["po_id"] for x in turns[0]["data"]["suppressed"]] == ["PO-BER-THC-OPEN"]
assert turns[1]["data"]["internal"]["last_7d_units"] > turns[1]["data"]["internal"]["prior_weekly_average"]
{stock_assertion}
{memory_import}
assert "Accessories" in exclusions
assert "Accessories" not in turns[4]["answer"]
for item in turns:
    assert set(item["instrumentation"]) == {{"recall", "decide", "write"}}
print(json.dumps({{
    "restocks": len(turns[0]["data"]["restock"]),
    "suppressed": turns[0]["data"]["suppressed"][0]["po_id"],
    "warm_units": turns[1]["data"]["internal"]["last_7d_units"],
    "exclusions": exclusions,
    "span_counts": [len(item["trace"]["spans"]) for item in turns],
}}))
"""
    return run_json(source)


def test_both_builds() -> None:
    memo = PART / "harness_done_for_you/memorizz/assistant/appbook"
    custom = PART / "custom_harness/appbook"
    for appbook, build in ((memo, "memorizz"), (custom, "custom")):
        result = _build_acceptance(appbook, build)
        assert result["restocks"] == 3
        assert result["suppressed"] == "PO-BER-THC-OPEN"
        assert all(count >= 4 for count in result["span_counts"])


def _route_acceptance(appbook: Path, expected_status_paths: list[str], stream_path: str) -> dict:
    source = f"""
import json, sys
from pathlib import Path
appbook = Path({str(appbook)!r})
sys.path.insert(0, str(appbook))
from fastapi.testclient import TestClient
from backend.main import app
paths = {expected_status_paths!r}
with TestClient(app) as client:
    root = client.get("/")
    results = {{path: client.get(path).status_code for path in paths}}
    stream = client.get({stream_path!r})
assert root.status_code == 200 and all(code == 200 for code in results.values())
assert stream.status_code == 200 and stream.headers["content-type"].startswith("text/event-stream")
print(json.dumps({{"root": root.status_code, "routes": results, "sse": stream.status_code}}))
"""
    return run_json(source)


def test_appbook_routes() -> None:
    memo_paths = [
        "/api/overview/status", "/api/the_store/status", "/api/the_memagent/status",
        "/api/memory/status", "/api/tools/status", "/api/the_brief/status",
        "/api/the_restart/status",
    ]
    custom_paths = [
        "/api/foundation/status", "/api/memory_layer/status", "/api/semantic_layer/status",
        "/api/retrieval/status", "/api/skills/status", "/api/tools_and_mcp/status",
        "/api/the_loop/status", "/api/cache/status", "/api/mission_control/status",
        "/api/data_explorer/status", "/api/storefront/catalog",
    ]
    assert len(_route_acceptance(PART / "harness_done_for_you/memorizz/assistant/appbook", memo_paths, "/api/the_brief/stream")["routes"]) == 7
    assert len(_route_acceptance(PART / "custom_harness/appbook", custom_paths, "/api/the_loop/stream?message=Morning%20brief.")["routes"]) == 11


def test_memorizz_appbook_sandbox_payloads_are_valid_python() -> None:
    """Tool evidence containing SQL NULLs must become Python ``None`` in E2B."""
    appbook = PART / "harness_done_for_you/memorizz/assistant/appbook"
    source = f"""
import contextlib, io, json, os, sys
os.environ["ERPA_RUN_E2B"] = "0"
sys.path.insert(0, {str(appbook)!r})
from backend.core.course_runtime import tools_chat
checks = {{}}
for name, query in (
    ("inventory", "Show ThermaCore inventory and calculate the total shortfall."),
    ("competitor", "Review competitor evidence."),
    ("finance", "Rank revenue by region."),
):
    result = tools_chat(query)
    code = result["sandbox"]["code"]
    compile(code, f"<{{name}}-sandbox>", "exec")
    output = io.StringIO()
    with contextlib.redirect_stdout(output):
        exec(code, {{}})
    checks[name] = output.getvalue().strip()
assert "null" not in tools_chat("Show ThermaCore inventory.")["sandbox"]["code"]
assert "16" in checks["inventory"] and "5" in checks["inventory"]
print(json.dumps(checks))
"""
    result = run_json(source)
    assert set(result) == {"inventory", "competitor", "finance"}


def test_data_explorer_and_storefront() -> None:
    appbook = PART / "custom_harness/appbook"
    source = f"""
import json, sys
from pathlib import Path
appbook = Path({str(appbook)!r})
sys.path.insert(0, str(appbook))
from fastapi.testclient import TestClient
from backend.main import app
from backend.core import store
from backend.core.activity import activity
order = None
with TestClient(app) as client:
    tables = client.get('/api/data_explorer/tables').json()['tables']
    names = {{table['name'] for table in tables}}
    assert {{'inventory','custom_store_orders','custom_store_order_lines'}} <= names
    page = client.get('/api/data_explorer/tables/inventory/rows?limit=4').json()
    assert len(page['rows']) == 4 and page['primary_keys'] == ['variant_id','location_id','snapshot_date']
    catalog = client.get('/api/storefront/catalog').json()
    assert len(catalog['products']) == 60
    product = next(item for item in catalog['products'] if item['total_stock']-item['reserved'] > 0)
    response = client.post('/api/storefront/checkout', json={{
        'customer_name':'Smoke Shopper','email':'smoke@example.test',
        'lines':[{{'sku':product['sku'],'quantity':1}}]
    }})
    assert response.status_code == 200, response.text
    order = response.json()
    try:
        with store.connect() as connection:
            assert connection.execute('SELECT COUNT(*) FROM custom_store_orders WHERE order_id=? AND status=?',
                                      (order['order_id'],'confirmed')).fetchone()[0] == 1
            assert connection.execute('SELECT COUNT(*) FROM custom_store_order_lines WHERE order_id=?',
                                      (order['order_id'],)).fetchone()[0] == 1
        events = activity.recent(40)
        assert any(event['table']=='inventory' and event['operation']=='WRITE' and event['status']=='active' for event in events)
        assert any(event['table']=='custom_store_orders' and event['status']=='committed' for event in events)
    finally:
        item = order['items'][0]
        with store.connect() as connection:
            connection.execute('UPDATE inventory SET on_hand=on_hand+? WHERE variant_id=? AND location_id=? AND snapshot_date=?',
                               (item['quantity'],item['variant_id'],item['location_id'],'2026-09-29'))
            connection.execute('DELETE FROM custom_store_order_lines WHERE order_id=?',(order['order_id'],))
            connection.execute('DELETE FROM custom_store_orders WHERE order_id=?',(order['order_id'],))
frontend = (appbook / 'frontend/app.js').read_text(encoding='utf-8')
markup = (appbook / 'frontend/index.html').read_text(encoding='utf-8')
assert 'Kata Store' in frontend and 'erpa-launcher' in frontend
assert 'data-explorer' in markup and 'Transaction activity' in markup
print(json.dumps({{'tables':len(tables),'products':len(catalog['products']),'transaction_events':len(events)}}))
"""
    result = run_json(source)
    assert result["tables"] >= 26 and result["products"] == 60 and result["transaction_events"] >= 6


def test_stages() -> None:
    stages = sorted((PART / "custom_harness/stages").glob("stage_[0-9][0-9]_*.py"))
    assert len(stages) == 6
    for stage in stages:
        output = run([PYTHON, str(stage)]).stdout
        assert output.strip(), f"{stage.name} produced no workshop output"


def test_guardrails_scheduler_and_cache() -> None:
    appbook = PART / "custom_harness/appbook"
    source = f"""
import json, sys
sys.path.insert(0, {str(appbook)!r})
from backend.core.semantic import semantic_layer
from backend.core.scheduler import scheduler
catalog = semantic_layer.catalog()
assert catalog["tables"]["products"]["columns"]["unit_cost"] == "NUMBER"
assert semantic_layer.search_catalog("stock by size and location")
blocked=[]
for sql in ("UPDATE products SET name='x'", "SELECT * FROM products CROSS JOIN orders"):
    try: semantic_layer.execute_read_only(sql)
    except (ValueError, PermissionError) as exc: blocked.append(type(exc).__name__)
brief = scheduler.run_now()
assert len(blocked) == 2 and brief["brief_id"]
print(json.dumps({{"blocked": blocked, "brief_id": brief["brief_id"]}}))
"""
    result = run_json(source)
    assert len(result["blocked"]) == 2
    measurement = json.loads(run([PYTHON, str(PART / "scripts/cache_measurement.py")]).stdout)
    assert measurement["cold"]["cache_hit"] is False
    assert measurement["warm"]["cache_hit"] is True
    assert measurement["warm"]["model_span"] is False
    assert measurement["delta"]["estimated_cost_usd"] > 0


def test_real_restart() -> None:
    for build in ("memorizz", "custom"):
        result = json.loads(run([PYTHON, str(PART / "scripts/restart_proof.py"), "--build", build]).stdout)
        assert result["different_processes"] is True
        assert result["phases"][0]["pid"] != result["phases"][1]["pid"]
        assert "Accessories" in result["phases"][1]["exclusions"]


def test_notebooks_and_fixtures() -> None:
    notebooks = [
        PART / "harness_done_for_you/memorizz/assistant/notebook/erpa_memorizz_complete.ipynb",
        PART / "custom_harness/notebook/erpa_custom_complete.ipynb",
    ]
    for path in notebooks:
        notebook = json.loads(path.read_text(encoding="utf-8"))
        cells = notebook["cells"]
        code = [cell for cell in cells if cell["cell_type"] == "code"]
        assert cells and code

    memorizz_notebook = json.loads(notebooks[0].read_text(encoding="utf-8"))
    memorizz_cells = memorizz_notebook["cells"]
    rendered = "\n".join("".join(cell.get("source", [])) for cell in memorizz_cells)
    assert "15-minute" not in rendered
    assert rendered.count("```mermaid") >= 4
    assert "| Harness concern | MemoRizz component |" in rendered
    assert "OracleProvider.from_env" in rendered and "in_database_embedding=True" not in rendered
    assert 'MEMORIZZ_ORACLE_IN_DATABASE_EMBEDDING", "true"' in rendered
    assert "https://mcp.notion.com/mcp" in rendered
    assert "E2BSandboxProvider" in rendered and ".with_sandbox(sandbox)" in rendered
    assert ".with_delegation(" in rendered and "delegate" in rendered.lower()
    assert "# Part 13 · Human in the loop" in rendered
    assert "# Part 16 · Governed semantic layer" in rendered
    assert "Toolbox.from_functions" in rendered and "discover_business_tools" not in rendered
    assert "generate_summaries" in rendered and "TOOL_LOG" in rendered
    assert "1. **Understand Alex's intent.**" in rendered
    assert 'memorizz[oracle,sandbox-e2b,ui]>=0.5.0' in rendered and 'pandas>=2.2' in rendered
    assert "from getpass import getpass" in rendered and "require_secret" in rendered
    assert "ALL_MINILM_L12_V2" in rendered and "pre-inference network round trips" in rendered
    assert "pd.DataFrame" in rendered and "table_frames" in rendered
    assert rendered.count("> 🔩 **Harness connection / decision**") >= 30
    assert "| Tool | Kind | Reads or changes |" in rendered
    assert "DeterministicToolMetadataOnly" not in rendered
    assert "Oracle `SKILLBOX` table" in rendered and '.with_skills(course_skills, persistence="skillbox")' in rendered
    assert ".with_skill_paths(" not in rendered
    assert "ERPA uses Notion as a reviewed collaboration surface" in rendered
    assert "## The `MemAgentBuilder` assembly point" in rendered
    assert "Shared memory** is the coordination plane" in rendered
    assert "src/memorizz/memagent/core.py" not in rendered
    assert "from backend" not in rendered and "import backend" not in rendered
    assert "_shared" not in rendered

    custom_notebook = json.loads(notebooks[1].read_text(encoding="utf-8"))
    custom_rendered = "\n".join("".join(cell.get("source", [])) for cell in custom_notebook["cells"])
    assert "TODO" not in custom_rendered.upper()
    for feature in (
        "## Custom harness component map", "Trusted function tools and the Custom Toolbox",
        "SecureFile ScratchFS", "ERPA_SESSION_END_PROMOTE", "OracleAgentMemory",
        "ChatAnthropic", 'thinking={"type": "adaptive"}', "E2B Code Interpreter",
        "OracleSaver", "OracleSemanticCache", "DBMS_SCHEDULER", "LangSmith",
        "V$SQL", "Prompt caching: where it would fit",
    ):
        assert feature in custom_rendered
    assert 'langchain-oracledb==1.5.0' in custom_rendered
    assert 'langgraph-oracledb==1.0.1' in custom_rendered
    assert "github.com/oracle/langchain-oracle/archive" not in custom_rendered
    assert "from backend" not in custom_rendered and "import backend" not in custom_rendered

    pages = list((PART / "_shared/fixtures/notion_pages").glob("*.md"))
    assert 10 <= len(pages) <= 14
    assert len([page for page in pages if page.name.startswith("review-notes-")]) == 4
    fixture = json.loads((PART / "_shared/fixtures/memory_fixtures.json").read_text(encoding="utf-8"))
    assert all(fixture[kind] for kind in ("semantic", "episodic", "procedural"))


def test_live_oracle_wiring_contract() -> None:
    """Prevent live Oracle adapters from regressing into unused example factories."""
    custom = PART / "custom_harness"
    requirements = (custom / "appbook/requirements-live.txt").read_text(encoding="utf-8")
    oracle = (custom / "appbook/backend/core/oracle_live.py").read_text(encoding="utf-8")
    memory = (custom / "appbook/backend/core/memory.py").read_text(encoding="utf-8")
    cache = (custom / "appbook/backend/core/cache.py").read_text(encoding="utf-8")
    live_graph = (custom / "appbook/backend/core/langgraph_live.py").read_text(encoding="utf-8")
    tools = (custom / "appbook/backend/core/tools.py").read_text(encoding="utf-8")
    sandbox = (custom / "appbook/backend/core/sandbox.py").read_text(encoding="utf-8")
    scratch = (custom / "appbook/backend/core/scratchfs.py").read_text(encoding="utf-8")
    bootstrap = (custom / "appbook/docker/bootstrap_oracle.py").read_text(encoding="utf-8")
    components = (custom / "appbook/backend/core/component_map.py").read_text(encoding="utf-8")
    compose = (custom / "deploy/docker-compose.yml").read_text(encoding="utf-8")
    schema = (PART / "_shared/seed/schema.sql").read_text(encoding="utf-8")

    assert "oracleagentmemory==26.6.0" in requirements
    assert "langchain-oracledb==1.5.0" in requirements
    assert "langgraph-oracledb==1.0.1" in requirements
    assert "github.com/oracle/langchain-oracle/archive" not in requirements
    assert "langchain-anthropic>=1.3" in requirements
    assert "e2b-code-interpreter==2.9.0" in requirements
    for feature in (
        "MemoryExtractionMode.BACKGROUND", "WAIT_THEN_RAISE", "OracleDBEmbedder",
        "SearchStrategy.HYBRID", "context_summary_update_frequency=2",
        "MemoryRetentionConfig", "OracleSemanticCache", "OracleSaver",
        "OracleInDatabaseEmbeddings", "checkpoint_connection",
    ):
        assert feature in oracle
    for feature in (
        "get_context_card", "exact_user_match=True", "exact_agent_match=True",
        "index_texts=[policy_chunks]", "update_memory", "delete_memory",
    ):
        assert feature in memory
    assert ".semantic_cache.lookup(" in cache and ".semantic_cache.update(" in cache
    assert "builder.compile(checkpointer=checkpointer)" in live_graph
    assert "self.compiled.invoke(" in live_graph and "self.stack.checkpointer.get(config)" in live_graph
    assert "ChatAnthropic" in live_graph and 'thinking={"type": settings.anthropic_thinking}' in live_graph
    assert "Sandbox.create" in sandbox and "no host execution fallback" in sandbox
    assert "run_python_in_e2b" in tools
    assert "stage_session_end" in scratch and "drain_promotion_queue" in scratch
    assert "ERPA_SESSION_END_PROMOTE" in bootstrap.upper()
    assert "V$SQL" in bootstrap and "ERPA_SEMANTIC_REFRESH_JOB" in bootstrap
    assert '"concern": "MCP"' in components and '"status": "missing"' in components
    assert "container-registry.oracle.com/database/free:latest-lite" in compose
    assert "condition: service_healthy" in compose and "erpa-oracle-data" in compose
    assert "ANTHROPIC_API_KEY" in compose and "E2B_API_KEY" in compose and "LANGSMITH_API_KEY" in compose
    for table in (
        "erpa_file_storage", "erpa_brief_queue", "erpa_agent_sessions",
        "erpa_scratch_files", "erpa_memory_promotion_queue", "erpa_semantic_catalog",
        "erpa_tool_registry", "erpa_skill_registry", "erpa_action_audit",
        "erpa_store_orders", "erpa_store_order_lines",
    ):
        assert f"CREATE TABLE {table}" in schema


def main() -> None:
    tests = [
        test_dataset,
        test_both_builds,
        test_appbook_routes,
        test_memorizz_appbook_sandbox_payloads_are_valid_python,
        test_data_explorer_and_storefront,
        test_stages,
        test_guardrails_scheduler_and_cache,
        test_real_restart,
        test_notebooks_and_fixtures,
        test_live_oracle_wiring_contract,
    ]
    started = time.perf_counter()
    for test in tests:
        tick = time.perf_counter()
        test()
        print(f"PASS {test.__name__} ({time.perf_counter() - tick:.2f}s)")
    print(f"PASS all {len(tests)} acceptance groups ({time.perf_counter() - started:.2f}s)")


if __name__ == "__main__":
    main()
