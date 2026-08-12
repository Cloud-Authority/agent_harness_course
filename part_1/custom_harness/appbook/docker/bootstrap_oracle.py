"""Wait for the Compose database, create the ERPA schema and load shared fixtures."""
from __future__ import annotations

import os
import re
import sys
import hashlib
import json
import tempfile
import time
from pathlib import Path

import oracledb
import requests

APPBOOK = Path(__file__).resolve().parents[1]
PART = APPBOOK.parents[1]
SEED = PART / "_shared" / "seed"
EMBED_MODEL = os.environ.get("INDB_EMBED_MODEL", "ALL_MINILM_L12_V2")
EMBED_ONNX_URL = os.environ.get(
    "ERPA_EMBED_ONNX_URL",
    "https://objectstorage.us-ashburn-1.oraclecloud.com/n/adwc4pm/b/OML-Resources/o/all_MiniLM_L12_v2.onnx",
)

if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_$#]{0,29}", EMBED_MODEL):
    raise ValueError("INDB_EMBED_MODEL must be a safe unquoted Oracle identifier")


def connect_with_retry(timeout_seconds: int = 180):
    deadline = time.monotonic() + timeout_seconds
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        try:
            return oracledb.connect(
                user=os.environ["ORA_AGENT_USER"],
                password=os.environ["ORA_AGENT_PWD"],
                dsn=os.environ["ORA_DSN"],
            )
        except oracledb.Error as exc:
            last_error = exc
            time.sleep(2)
    raise RuntimeError(f"Oracle did not become ready within {timeout_seconds}s: {last_error}")


def apply_schema(connection) -> None:
    schema = (SEED / "schema.sql").read_text(encoding="utf-8")
    # Strip SQL line comments before splitting; a pedagogical comment may itself
    # contain a semicolon and must not truncate the following DDL statement.
    schema_without_comments = "\n".join(line.split("--", 1)[0] for line in schema.splitlines())
    statements = [statement.strip() for statement in schema_without_comments.split(";") if statement.strip()]
    with connection.cursor() as cursor:
        for statement in statements:
            try:
                cursor.execute(statement)
            except oracledb.DatabaseError as exc:
                error = exc.args[0]
                if getattr(error, "code", None) != 955:  # already exists
                    headline = " ".join(statement.split())[:180]
                    raise RuntimeError(f"Schema statement failed: {headline}") from exc
    connection.commit()


def apply_additive_migrations(connection) -> None:
    """Bring older workshop volumes forward without resetting queued work."""
    required = {
        "COMPLETED_AT": "TIMESTAMP",
        "ERROR_MESSAGE": "VARCHAR2(2000)",
    }
    with connection.cursor() as cursor:
        cursor.execute("SELECT column_name FROM user_tab_columns WHERE table_name='ERPA_BRIEF_QUEUE'")
        present = {row[0] for row in cursor.fetchall()}
        for column, data_type in required.items():
            if column not in present:
                cursor.execute(f"ALTER TABLE erpa_brief_queue ADD ({column} {data_type})")
    connection.commit()


def require_oamp_compatible_database(connection) -> None:
    """OAMP 26.6 requires Oracle AI Database 26ai or later."""
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT product,version_full FROM product_component_version "
            "WHERE product LIKE 'Oracle%Database%' FETCH FIRST 1 ROW ONLY"
        )
        row = cursor.fetchone()
        if row is None:
            raise RuntimeError("Could not identify the connected Oracle AI Database release")
        product, database_version = map(str, row)
    parts = [int(part) for part in re.findall(r"\d+", database_version)[:2]]
    compatible = bool(parts) and (parts[0] >= 26 or (parts[0] == 23 and len(parts) > 1 and parts[1] >= 26))
    if not compatible:
        raise RuntimeError(
            "OAMP 26.6 requires Oracle AI Database 26ai or later; "
            f"the connected container reports: {product} {database_version}"
        )


def ensure_embedding_model(connection) -> None:
    """Load the 384-dimensional ONNX model once, then prove in-DB inference."""
    with connection.cursor() as cursor:
        cursor.execute("SELECT COUNT(*) FROM user_mining_models WHERE model_name=:1", [EMBED_MODEL.upper()])
        present = int(cursor.fetchone()[0]) > 0
    if not present:
        model_dir = Path(tempfile.gettempdir()) / "erpa-oracle-models"
        model_dir.mkdir(parents=True, exist_ok=True)
        model_path = model_dir / "all_MiniLM_L12_v2.onnx"
        if not model_path.exists() or model_path.stat().st_size < 1_000_000:
            with requests.get(EMBED_ONNX_URL, stream=True, timeout=600) as response:
                response.raise_for_status()
                with model_path.open("wb") as output:
                    for chunk in response.iter_content(1 << 20):
                        output.write(chunk)
        lob = connection.createlob(oracledb.DB_TYPE_BLOB)
        lob.write(model_path.read_bytes())
        metadata = json.dumps({
            "function": "embedding",
            "embeddingOutput": "embedding",
            "input": {"input": ["DATA"]},
        })
        with connection.cursor() as cursor:
            cursor.execute(
                "BEGIN DBMS_VECTOR.LOAD_ONNX_MODEL(:name,:data,JSON(:metadata)); END;",
                {"name": EMBED_MODEL, "data": lob, "metadata": metadata},
            )
        connection.commit()
    with connection.cursor() as cursor:
        cursor.execute(f"SELECT VECTOR_EMBEDDING({EMBED_MODEL} USING 'ERPA smoke test' AS DATA) FROM dual")
        vector = cursor.fetchone()[0]
    if len(vector) != 384:
        raise RuntimeError(f"{EMBED_MODEL} returned {len(vector)} dimensions; expected 384")


def ensure_session_promotion(connection) -> None:
    """Install the logical session-end procedure and row trigger."""
    statements = [
        """CREATE OR REPLACE PROCEDURE erpa_stage_session_memory(p_session_id VARCHAR2) AS
          l_text CLOB;
          l_dest_offset INTEGER;
          l_src_offset INTEGER;
          l_lang_context INTEGER;
          l_warning INTEGER;
          l_position INTEGER;
        BEGIN
          FOR f IN (SELECT path,content FROM erpa_scratch_files
                    WHERE session_id=p_session_id AND is_dir='N'
                      AND promote_on_end='Y' AND promotion_state='N') LOOP
            DBMS_LOB.CREATETEMPORARY(l_text, TRUE);
            l_dest_offset := 1;
            l_src_offset := 1;
            l_lang_context := 0;
            DBMS_LOB.CONVERTTOCLOB(
              l_text, f.content, DBMS_LOB.LOBMAXSIZE, l_dest_offset, l_src_offset,
              NLS_CHARSET_ID('AL32UTF8'), l_lang_context, l_warning
            );
            l_position := 1;
            WHILE l_position <= DBMS_LOB.GETLENGTH(l_text) LOOP
              INSERT INTO erpa_memory_promotion_queue(session_id,path,chunk)
              VALUES (p_session_id,f.path,DBMS_LOB.SUBSTR(l_text,3500,l_position));
              l_position := l_position + 3200;
            END LOOP;
            DBMS_LOB.FREETEMPORARY(l_text);
            UPDATE erpa_scratch_files SET promotion_state='S'
              WHERE session_id=p_session_id AND path=f.path;
          END LOOP;
        END;""",
        """CREATE OR REPLACE TRIGGER erpa_session_end_promote
        AFTER UPDATE OF status ON erpa_agent_sessions
        FOR EACH ROW
        WHEN (NEW.status = 'ENDED' AND OLD.status <> 'ENDED')
        BEGIN
          erpa_stage_session_memory(:NEW.session_id);
        END;""",
    ]
    with connection.cursor() as cursor:
        for statement in statements:
            cursor.execute(statement)
    connection.commit()


def ensure_semantic_layer(connection) -> None:
    """Create governed meaning and the scheduled living-catalog refresh."""
    with connection.cursor() as cursor:
        cursor.execute("""CREATE OR REPLACE VIEW erpa_v_profitability AS
          SELECT o.region,
                 SUM(ol.qty) AS units,
                 ROUND(SUM(ol.qty*ol.unit_price*(1-ol.discount)),2) AS net_revenue,
                 ROUND(SUM(ol.qty*(ol.unit_price*(1-ol.discount)-p.unit_cost)),2) AS gross_margin,
                 ROUND(100*SUM(ol.qty*(ol.unit_price*(1-ol.discount)-p.unit_cost)) /
                   NULLIF(SUM(ol.qty*ol.unit_price*(1-ol.discount)),0),2) AS gross_margin_percent,
                 ROUND(100*AVG(ol.discount),2) AS avg_discount_percent
          FROM order_lines ol
          JOIN orders o ON o.order_id=ol.order_id
          JOIN variants v ON v.variant_id=ol.variant_id
          JOIN products p ON p.sku=v.sku
          GROUP BY o.region""")
        cursor.execute("COMMENT ON TABLE erpa_v_profitability IS 'Governed regional profitability view; profitable means gross-margin value'")
        cursor.execute("COMMENT ON COLUMN erpa_v_profitability.gross_margin IS 'Net revenue minus product cost; canonical profitability metric'")
        cursor.execute("COMMENT ON COLUMN purchase_orders.status IS 'OPEN indicates already actioned inventory that alerts must suppress'")
        hints = [
            ("metric:profitability", "metric", "Most profitable means highest gross_margin, never highest revenue.", 1000),
            ("join:inventory_po", "join", "Join inventory through variant and location to purchase_orders; suppress open purchase orders.", 900),
            ("scope:morning_brief", "filter", "Morning brief scope is UK and EU, Outerwear and Tops, minus remembered exclusions.", 800),
            ("query:warm_spike", "query", "Compare the latest WarmLayer UK week with the preceding four complete weeks and inspect promotions.", 700),
        ]
        cursor.execute("DELETE FROM erpa_semantic_hints")
        cursor.executemany("INSERT INTO erpa_semantic_hints VALUES (:1,:2,:3,:4)", hints)
        cursor.execute(f"""CREATE OR REPLACE PROCEDURE erpa_refresh_semantic_catalog AS
        BEGIN
          DELETE FROM erpa_semantic_catalog WHERE source_type IN ('column','hint');
          INSERT INTO erpa_semantic_catalog(catalog_id,source_type,catalog_text,embedding)
          SELECT 'column:'||c.table_name||'.'||c.column_name, 'column',
                 c.table_name||'.'||c.column_name||' ('||c.data_type||') '||NVL('-- '||cc.comments,''),
                 VECTOR_EMBEDDING({EMBED_MODEL} USING
                   c.table_name||'.'||c.column_name||' '||NVL(cc.comments,'') AS DATA)
          FROM user_tab_columns c
          LEFT JOIN user_col_comments cc ON cc.table_name=c.table_name AND cc.column_name=c.column_name
          WHERE c.table_name LIKE 'ERPA_%' OR c.table_name IN
            ('PRODUCTS','VARIANTS','INVENTORY','LOCATIONS','ORDERS','ORDER_LINES','PURCHASE_ORDERS');
          INSERT INTO erpa_semantic_catalog(catalog_id,source_type,catalog_text,embedding)
          SELECT subject,'hint',hint_type||': '||hint_text,
                 VECTOR_EMBEDDING({EMBED_MODEL} USING hint_type||': '||hint_text AS DATA)
          FROM erpa_semantic_hints;
          DELETE FROM erpa_semantic_catalog WHERE source_type='workload';
          INSERT INTO erpa_semantic_catalog(catalog_id,source_type,catalog_text,embedding)
          SELECT 'vsql:'||sql_id,'workload',catalog_text,
                 VECTOR_EMBEDDING({EMBED_MODEL} USING catalog_text AS DATA)
          FROM (
            SELECT sql_id,'Executed '||SUM(executions)||' times: '||MIN(SUBSTR(sql_text,1,700)) catalog_text
            FROM v$sql
            WHERE parsing_schema_name=USER AND UPPER(sql_text) LIKE '%ERPA_%'
            GROUP BY sql_id ORDER BY SUM(executions) DESC FETCH FIRST 10 ROWS ONLY
          );
          COMMIT;
        END;""")
    connection.commit()


def seed_tool_and_skill_registry(connection) -> None:
    tools = [
        ("morning_brief_inputs", "Return UK/EU low-stock actions and items suppressed by an open purchase order", "trusted Oracle function"),
        ("sales_signal", "Compare recent product demand with its prior baseline and promotion state", "trusted Oracle function"),
        ("inventory_status", "Read stock by product, region, city and size", "trusted Oracle function"),
        ("regional_profitability", "Rank regions with the governed gross-margin metric", "governed Oracle view"),
        ("institutional_search", "Retrieve approved policies and regional merchandising notes", "Oracle vector retrieval"),
        ("external_signal_search", "Read dated governed external evidence and its source", "Oracle ingestion table"),
        ("scratch_write", "Write or update a session plan, note, draft or tool artifact", "Oracle SecureFile ScratchFS"),
        ("scratch_read", "Read a file from the current session scratch mount", "Oracle SecureFile ScratchFS"),
        ("sandbox_python", "Execute generated Python in E2B and compact large output to ScratchFS", "E2B Code Interpreter"),
        ("remember_fact", "Persist an explicit preference, fact or guideline", "Oracle Agent Memory"),
        ("load_skill", "Load one retrieved approved procedure by name", "Oracle skill registry"),
    ]
    skills = [
        ("compose_morning_brief", "Personalised daily attention digest",
         "Recall scope and exclusions. Query low stock, suppress open POs, lead with numbers, and cite handled IDs."),
        ("restock_recommendation", "Core and seasonal stock decision",
         "Return SKU, variant, location, cover, lead time, quantity and rationale. Check open purchase orders first."),
        ("profitability_analysis", "Governed regional profit comparison",
         "Use gross-margin value for ranking; show margin percentage, unit volume, discounts and provenance."),
        ("stock_visualisation", "Size-curve analysis in the code sandbox",
         "Query stock, use sandbox_python for generated computation, and place large output in ScratchFS."),
        ("demand_anomaly_investigation", "Triangulate unusual demand with governed evidence",
         "Compare the recent window to its baseline, check internal promotions, retrieve seasonal guidance and dated external evidence, then separate correlation from causation."),
        ("size_curve_diagnosis", "Find broken size curves by product and region",
         "Aggregate stock by region and size, identify constrained and overstocked sizes, and cite the inventory snapshot."),
        ("returns_root_cause", "Analyse return concentration and reasons",
         "Rank returned units, split reason codes, protect customer privacy and recommend investigation without asserting causality."),
        ("supplier_risk_review", "Assess replenishment lead-time and reliability risk",
         "Join SKU to supplier, show lead time, reliability and MOQ, then relate those constraints to the stock decision."),
        ("purchase_order_suppression", "Prevent duplicate action when an open PO exists",
         "Check variant and location for an open PO before raising an alert and cite the PO ID when handled."),
        ("catalog_assortment_review", "Compare product, collection and seasonal assortment",
         "Group by category, collection and core status; show style, variant and available-stock counts."),
        ("promotion_memory_review", "Review ScratchFS notes before durable-memory promotion",
         "Inspect opted-in files, show staged chunks, end the logical session and verify promoted OAMP facts."),
    ]
    with connection.cursor() as cursor:
        cursor.execute("DELETE FROM erpa_external_signals")
        cursor.execute(
            "INSERT INTO erpa_external_signals VALUES "
            "('uk-cold-snap',TRUNC(SYSDATE),'UK','weather',"
            "'A UK cold snap pushed mean temperatures below the 12C presentation threshold.',"
            "'https://example.test/weather/uk-cold-snap')"
        )
        cursor.execute("DELETE FROM erpa_tool_registry")
        cursor.executemany(
            f"""INSERT INTO erpa_tool_registry(tool_name,description,transport,embedding)
                VALUES (:tool_name,:description,:transport,
                  VECTOR_EMBEDDING({EMBED_MODEL} USING :embed_text AS DATA))""",
            [{"tool_name": name, "description": description, "transport": transport,
              "embed_text": description} for name, description, transport in tools],
        )
        cursor.execute("DELETE FROM erpa_skill_registry")
        for name, description, body in skills:
            cursor.execute(
                f"""INSERT INTO erpa_skill_registry(skill_name,description,body,body_sha256,status,embedding)
                    VALUES (:skill_name,:description,:body,:body_sha,'ACTIVE',
                      VECTOR_EMBEDDING({EMBED_MODEL} USING :embed_text AS DATA))""",
                {"skill_name": name, "description": description, "body": body,
                 "body_sha": hashlib.sha256(body.encode()).hexdigest(), "embed_text": description},
            )
    connection.commit()


def refresh_semantic_catalog(connection) -> int:
    """Refresh governed schema, hint and currently observed V$SQL facts."""
    with connection.cursor() as cursor:
        cursor.callproc("erpa_refresh_semantic_catalog")
        cursor.execute("SELECT COUNT(*) FROM erpa_semantic_catalog")
        count = int(cursor.fetchone()[0])
    connection.commit()
    return count


def ensure_brief_job(connection) -> None:
    """Install the queueing DBMS_SCHEDULER job without replacing prior state."""
    with connection.cursor() as cursor:
        cursor.execute("""
        DECLARE
          job_count NUMBER;
        BEGIN
          SELECT COUNT(*) INTO job_count
          FROM user_scheduler_jobs
          WHERE job_name = 'ERPA_MORNING_BRIEF_JOB';
          IF job_count = 0 THEN
            DBMS_SCHEDULER.CREATE_JOB(
              job_name        => 'ERPA_MORNING_BRIEF_JOB',
              job_type        => 'PLSQL_BLOCK',
              job_action      => q'[BEGIN
                INSERT INTO erpa_brief_queue(request_id,user_id,prompt)
                VALUES (RAWTOHEX(SYS_GUID()), 'planner-01', 'Morning brief.');
                COMMIT;
              END;]',
              start_date      => SYSTIMESTAMP,
              repeat_interval => 'FREQ=WEEKLY;BYDAY=MON,TUE,WED,THU,FRI;BYHOUR=8;BYMINUTE=0;BYSECOND=0',
              enabled         => TRUE,
              comments        => 'Queues the standard ERPA LangGraph morning brief.'
            );
          END IF;
        END;
        """)
    connection.commit()


def ensure_semantic_refresh_job(connection) -> None:
    with connection.cursor() as cursor:
        cursor.execute("""
        DECLARE
          job_count NUMBER;
        BEGIN
          SELECT COUNT(*) INTO job_count FROM user_scheduler_jobs
          WHERE job_name = 'ERPA_SEMANTIC_REFRESH_JOB';
          IF job_count = 0 THEN
            DBMS_SCHEDULER.CREATE_JOB(
              job_name => 'ERPA_SEMANTIC_REFRESH_JOB',
              job_type => 'PLSQL_BLOCK',
              job_action => 'BEGIN erpa_refresh_semantic_catalog; END;',
              start_date => SYSTIMESTAMP,
              repeat_interval => 'FREQ=HOURLY;INTERVAL=6',
              enabled => TRUE,
              comments => 'Refreshes governed schema and hint facts in the ERPA living semantic catalog.'
            );
          END IF;
        END;
        """)
    connection.commit()


def main() -> None:
    connection = connect_with_retry()
    try:
        require_oamp_compatible_database(connection)
        apply_schema(connection)
        apply_additive_migrations(connection)
        ensure_embedding_model(connection)
        ensure_session_promotion(connection)
        ensure_semantic_layer(connection)
        ensure_brief_job(connection)
        ensure_semantic_refresh_job(connection)
    finally:
        connection.close()

    if str(SEED) not in sys.path:
        sys.path.insert(0, str(SEED))
    from generate_seed_data import DB_PATH, build_sqlite, export_csv

    build_sqlite(DB_PATH)
    export_csv(DB_PATH)

    scripts = SEED / "scripts"
    if str(scripts) not in sys.path:
        sys.path.insert(0, str(scripts))
    from load_oracle import main as load_oracle

    load_oracle()
    connection = connect_with_retry()
    try:
        seed_tool_and_skill_registry(connection)
        semantic_facts = refresh_semantic_catalog(connection)
    finally:
        connection.close()
    print(f"ERPA Oracle schema, fixtures and {semantic_facts} living semantic facts are ready.")


if __name__ == "__main__":
    main()
