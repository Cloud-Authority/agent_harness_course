"""Database substrate for the appbook: a connection pool, idempotent harness setup,
the retrieval ladder, and the in-database scratch filesystem.

This is the same harness the notebook builds, ported to a long-lived service. It
connects to the existing AGENT schema and creates anything missing idempotently
(it never resets). The vector store deliberately uses a small typed table plus
visible Oracle SQL for embedding, insertion, and cosine search. All embeddings
are produced in-database by the loaded ONNX model.
"""
from __future__ import annotations

import json
import os
import re
import threading

import oracledb

from part_1.advanced.shared.persistence import ORACLE_EMBEDDING_LOCK

from ..config import settings

oracledb.defaults.fetch_lobs = False   # CLOB -> str, BLOB -> bytes

EMB = settings.embed_model
RERANK = settings.rerank_model
DIM = settings.vector_dim
VSTORE = "AGENT_VSTORE"
if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_$#]{0,122}", EMB):
    raise ValueError("Unsafe Oracle mining-model identifier")

_pool: oracledb.ConnectionPool | None = None
_state = {
    "ready": False,
    "oracle": False,
    "rerank": False,
    "vector_index": "pending",
    "error": None,
}
_init_lock = threading.Lock()

_vector_lock = threading.Lock()
_embedding_lock = ORACLE_EMBEDDING_LOCK


# ── pool + helpers ────────────────────────────────────────────────────────
def _get_pool() -> oracledb.ConnectionPool:
    global _pool
    if _pool is None:
        _pool = oracledb.create_pool(user=settings.ora_user, password=settings.ora_password,
                                     dsn=settings.ora_dsn, min=2, max=8, increment=1)
    return _pool


def pool() -> oracledb.ConnectionPool:
    """Expose the app's shared pool to read-only infrastructure adapters."""
    return _get_pool()


def q(sql: str, params=None):
    pool = _get_pool()
    for attempt in range(2):
        conn = pool.acquire()
        try:
            with conn.cursor() as cur:
                cur.execute(sql, params or {})
                if cur.description is None:
                    return []
                cols = [c[0] for c in cur.description]
                return [dict(zip(cols, r)) for r in cur.fetchall()]
        except Exception as exc:
            if attempt == 0 and "DPY-4011" in str(exc):
                try:
                    pool.drop(conn)
                finally:
                    conn = None
                continue
            raise
        finally:
            if conn is not None:
                conn.close()
    raise RuntimeError("Oracle read retry exhausted")


def x(sql: str, params=None, many=False):
    with _get_pool().acquire() as conn:
        cur = conn.cursor()
        try:
            cur.executemany(sql, params or []) if many else cur.execute(sql, params or {})
            conn.commit()
        finally:
            cur.close()


_IGNORE = ("ORA-00955", "ORA-01920", "ORA-00942", "ORA-01430", "ORA-02260",
           "ORA-01408", "ORA-00001", "ORA-29879", "ORA-29833", "ORA-12003",
           "ORA-00904", "ORA-51962")


def ddl(sql: str):
    try:
        x(sql)
        return True
    except Exception as e:
        if any(c in str(e) for c in _IGNORE):
            return False
        raise


def status() -> dict:
    return dict(_state)


def _hnsw_enabled() -> bool:
    return os.environ.get("TR_ENABLE_HNSW", "0").strip().lower() in {
        "1", "true", "yes", "on"
    }


def _index_exists(name: str) -> bool:
    return bool(
        q(
            "SELECT 1 FROM user_indexes WHERE index_name=:name",
            {"name": name.upper()},
        )
    )


# ── the visible Oracle vector store ──────────────────────────────────────
def _build_store():
    """Ensure the typed vector table exists without hiding it behind an adapter."""
    ddl(f'''CREATE TABLE {VSTORE} (
      id RAW(16) DEFAULT SYS_GUID() PRIMARY KEY,
      text CLOB NOT NULL,
      metadata JSON NOT NULL,
      embedding VECTOR({DIM}, FLOAT32) NOT NULL)''')
    active = _index_exists("AGENT_VSTORE_HNSW")
    if _hnsw_enabled() and not active:
        active = ddl(f'''CREATE VECTOR INDEX agent_vstore_hnsw ON {VSTORE} (embedding)
          ORGANIZATION INMEMORY NEIGHBOR GRAPH DISTANCE COSINE
          WITH TARGET ACCURACY 95''')
    _state["vector_index"] = (
        "Oracle HNSW cosine" if active else "exact Oracle cosine fallback"
    )
    return VSTORE


def _metadata_value(value):
    if isinstance(value, dict):
        return value
    if hasattr(value, "read"):
        value = value.read()
    return json.loads(value) if isinstance(value, str) else {}


# ── idempotent harness setup ──────────────────────────────────────────────
def initialize():
    with _init_lock:
        if _state["ready"]:
            return
        try:
            ver = q("SELECT banner FROM v$version WHERE rownum=1")
            _state["oracle"] = bool(ver)
            _state["rerank"] = bool(q("SELECT 1 FROM user_mining_models WHERE model_name=:m", {"m": RERANK}))
            _ensure_tables()
            _build_store()
            _seed_schema()
            scan_semantic_layer()
            _seed_knowledge()
            from . import registries
            registries.register_default_tools()
            registries.seed_starter_skills()
            _state["ready"] = True
            _state["error"] = None
        except Exception as e:  # surface but keep serving the frontend
            _state["error"] = str(e).splitlines()[0]
            raise


def _ensure_tables():
    ddl('''CREATE TABLE agent_runtime_locks (
      lock_name VARCHAR2(80) PRIMARY KEY,
      created_at TIMESTAMP DEFAULT SYSTIMESTAMP)''')
    x('''MERGE INTO agent_runtime_locks target
      USING (SELECT 'ONNX_EMBEDDING' AS lock_name FROM dual) source
      ON (target.lock_name = source.lock_name)
      WHEN NOT MATCHED THEN INSERT (lock_name) VALUES (source.lock_name)''')
    # AGENT_VSTORE is created by _build_store so its four-column contract stays visible.
    ddl('''CREATE TABLE agent_scratch (
      path VARCHAR2(400) PRIMARY KEY, content BLOB, is_dir CHAR(1) DEFAULT 'N',
      promoted CHAR(1) DEFAULT 'N', updated_at TIMESTAMP DEFAULT SYSTIMESTAMP) LOB (content) STORE AS SECUREFILE''')
    ddl(f'''CREATE TABLE agent_workflow (
      id RAW(16) DEFAULT SYS_GUID() PRIMARY KEY, intent VARCHAR2(400), steps CLOB,
      tools_used VARCHAR2(1000), occurrences NUMBER DEFAULT 1, promoted CHAR(1) DEFAULT 'N',
      embedding VECTOR({DIM}, FLOAT32), created_at TIMESTAMP DEFAULT SYSTIMESTAMP,
      last_seen TIMESTAMP DEFAULT SYSTIMESTAMP)''')
    ddl(f'''CREATE TABLE agent_tools (
      name VARCHAR2(120) PRIMARY KEY, description VARCHAR2(600), category VARCHAR2(60),
      tool_schema JSON, embedding VECTOR({DIM}, FLOAT32), created_at TIMESTAMP DEFAULT SYSTIMESTAMP)''')
    tools_hnsw = _index_exists("AGENT_TOOLS_HNSW")
    if _hnsw_enabled() and not tools_hnsw:
        tools_hnsw = ddl('''CREATE VECTOR INDEX agent_tools_hnsw ON agent_tools (embedding)
          ORGANIZATION INMEMORY NEIGHBOR GRAPH DISTANCE COSINE WITH TARGET ACCURACY 95''')
    ddl(f'''CREATE TABLE agent_skills (
      name VARCHAR2(120) PRIMARY KEY, description VARCHAR2(600), sha VARCHAR2(64), source_url VARCHAR2(600),
      skill_md CLOB, tools_used VARCHAR2(600), source_workflow_id RAW(16), embedding VECTOR({DIM}, FLOAT32),
      created_at TIMESTAMP DEFAULT SYSTIMESTAMP, updated_at TIMESTAMP DEFAULT SYSTIMESTAMP)''')
    skills_hnsw = _index_exists("AGENT_SKILLS_HNSW")
    if _hnsw_enabled() and not skills_hnsw:
        skills_hnsw = ddl('''CREATE VECTOR INDEX agent_skills_hnsw ON agent_skills (embedding)
          ORGANIZATION INMEMORY NEIGHBOR GRAPH DISTANCE COSINE WITH TARGET ACCURACY 95''')
    _state["vector_index"] = (
        "HNSW requested or already present"
        if tools_hnsw or skills_hnsw
        else "exact Oracle cosine fallback"
    )
    ddl('''CREATE TABLE agent_automations (
      name VARCHAR2(120) PRIMARY KEY, description VARCHAR2(600), artifact VARCHAR2(120),
      job_name VARCHAR2(120), cadence_hours NUMBER, select_sql CLOB, created_at TIMESTAMP DEFAULT SYSTIMESTAMP)''')
    ddl(f'''CREATE TABLE agent_tool_log (
      id RAW(16) DEFAULT SYS_GUID() PRIMARY KEY, tool VARCHAR2(120), payload CLOB,
      embedding VECTOR({DIM}, FLOAT32), created_at TIMESTAMP DEFAULT SYSTIMESTAMP)''')


def _seed_schema():
    for d in [
        '''CREATE TABLE customers (customer_id NUMBER PRIMARY KEY, name VARCHAR2(100), email VARCHAR2(120),
            country VARCHAR2(40), segment VARCHAR2(20), signup_date DATE)''',
        '''CREATE TABLE products (product_id NUMBER PRIMARY KEY, name VARCHAR2(100), category VARCHAR2(40),
            unit_price NUMBER(10,2), unit_cost NUMBER(10,2))''',
        '''CREATE TABLE orders (order_id NUMBER PRIMARY KEY, customer_id NUMBER REFERENCES customers,
            order_date DATE, status VARCHAR2(20), channel VARCHAR2(20))''',
        '''CREATE TABLE order_items (order_item_id NUMBER PRIMARY KEY, order_id NUMBER REFERENCES orders,
            product_id NUMBER REFERENCES products, quantity NUMBER, unit_price NUMBER(10,2),
            discount NUMBER(5,2) DEFAULT 0)''']:
        ddl(d)
    if q("SELECT COUNT(*) n FROM customers")[0]["N"] == 0:
        import random
        rnd = random.Random(42)
        cats, chans, segs = ["Outdoors", "Electronics", "Home", "Apparel"], ["web", "store", "partner"], ["consumer", "smb", "enterprise"]
        x("INSERT INTO customers VALUES (:1,:2,:3,:4,:5, SYSDATE - :6)",
          [(i, f"Customer {i}", f"c{i}@example.com", rnd.choice(["US", "GB", "DE", "FR"]),
            rnd.choice(segs), rnd.randint(30, 900)) for i in range(1, 61)], many=True)
        x("INSERT INTO products VALUES (:1,:2,:3,:4,:5)",
          [(i, f"Product {i}", rnd.choice(cats), round(rnd.uniform(10, 400), 2),
            round(rnd.uniform(5, 200), 2)) for i in range(1, 41)], many=True)
        oid, items = 1, []
        for _ in range(400):
            x("INSERT INTO orders VALUES (:oid, :cust, SYSDATE - :age, :st, :ch)",
              {"oid": oid, "cust": rnd.randint(1, 60), "age": rnd.randint(0, 180),
               "st": rnd.choice(["paid", "paid", "paid", "refunded"]), "ch": rnd.choice(chans)})
            for _ in range(rnd.randint(1, 4)):
                items.append((len(items) + 1, oid, rnd.randint(1, 40), rnd.randint(1, 5),
                              round(rnd.uniform(10, 400), 2), rnd.choice([0, 0, 0, 5, 10])))
            oid += 1
        x("INSERT INTO order_items VALUES (:1,:2,:3,:4,:5,:6)", items, many=True)
    ddl('''CREATE OR REPLACE VIEW v_revenue AS
      SELECT o.order_id, o.order_date, o.channel, c.segment, c.country, p.category, oi.quantity,
             (oi.unit_price * oi.quantity) * (1 - NVL(oi.discount,0)/100) AS net_revenue
      FROM orders o JOIN order_items oi ON oi.order_id=o.order_id
                    JOIN products p ON p.product_id=oi.product_id
                    JOIN customers c ON c.customer_id=o.customer_id
      WHERE o.status='paid' ''')
    try:
        x("COMMENT ON COLUMN v_revenue.net_revenue IS 'Net paid revenue per line = price * qty * (1-discount)'")
        x("COMMENT ON TABLE orders IS 'One row per customer order; status is paid or refunded'")
        x("COMMENT ON COLUMN order_items.discount IS 'Percentage discount applied to the line (0-100)'")
    except Exception:
        pass


# ── encoding (write path) ────────────────────────────────────────────────
def add_texts(texts, metadatas=None, namespace="knowledge"):
    metadatas = metadatas or [{} for _ in texts]
    rows = [{**(m or {}), "namespace": namespace} for m in metadatas]
    with _vector_lock:
        _build_store()
        for text, metadata in zip(texts, rows):
            vector = embedding_vector(str(text))
            x(
                f'''INSERT INTO {VSTORE} (id, text, metadata, embedding)
                    VALUES (SYS_GUID(), :text, :metadata, :embedding)''',
                {
                    "text": str(text),
                    "metadata": json.dumps(metadata, sort_keys=True),
                    "embedding": vector,
                },
            )
    return len(texts)


def embed_dims(text: str) -> int:
    return len(embedding_vector(text))


def embedding_vector(text: str):
    """Return one database vector with cross-process ONNX serialization."""
    with _embedding_lock:
        pool = _get_pool()
        for attempt in range(2):
            conn = pool.acquire()
            try:
                with conn.cursor() as cur:
                    cur.execute('''SELECT lock_name FROM agent_runtime_locks
                      WHERE lock_name='ONNX_EMBEDDING' FOR UPDATE WAIT 120''')
                    cur.fetchone()
                    cur.execute(
                        f"SELECT VECTOR_EMBEDDING({EMB} USING :t AS DATA) v FROM dual",
                        {"t": str(text) if str(text).strip() else " "},
                    )
                    row = cur.fetchone()
                conn.rollback()
                vector = row[0] if row else None
                if vector is None or len(vector) != DIM:
                    raise RuntimeError(f"{EMB} returned an invalid embedding")
                return vector
            except Exception as exc:
                try:
                    conn.rollback()
                except Exception:
                    pass
                if attempt == 0 and "DPY-4011" in str(exc):
                    try:
                        pool.drop(conn)
                    finally:
                        conn = None
                    continue
                raise
            finally:
                if conn is not None:
                    conn.close()
    raise RuntimeError("Oracle embedding retry exhausted")


def embedding_preview(text: str, n: int = 8):
    v = list(embedding_vector(text))
    return {"dims": len(v), "head": [round(float(x), 4) for x in v[:n]]}


# ── retrieval ladder (read path) ─────────────────────────────────────────
def kw_search(query, namespace="knowledge", k=5):
    _build_store()
    rows = q(
        f'''SELECT RAWTOHEX(id) id, text, metadata FROM {VSTORE}
            WHERE (:namespace IS NULL OR JSON_VALUE(metadata,'$.namespace')=:namespace)
            FETCH FIRST 500 ROWS ONLY''',
        {"namespace": namespace},
    )
    tokens = re.findall(r"[a-z0-9]+", str(query).lower())
    ranked = []
    for row in rows:
        content = str(row["TEXT"])
        lowered = content.lower()
        score = sum(lowered.count(token) for token in tokens)
        if score:
            ranked.append(
                {
                    "ID": row["ID"],
                    "CONTENT": content,
                    "metadata": _metadata_value(row["METADATA"]),
                    "SCORE": score,
                }
            )
    return sorted(ranked, key=lambda item: (-item["SCORE"], item["ID"]))[:k]


def vec_search(query, namespace="knowledge", k=5):
    _build_store()
    vector = embedding_vector(str(query))
    rows = q(
        f'''SELECT RAWTOHEX(id) id, text, metadata,
                   VECTOR_DISTANCE(embedding, :embedding, COSINE) dist
            FROM {VSTORE}
            WHERE (:namespace IS NULL OR JSON_VALUE(metadata,'$.namespace')=:namespace)
            ORDER BY dist FETCH APPROX FIRST :k ROWS ONLY''',
        {"embedding": vector, "namespace": namespace, "k": int(k)},
    )
    return [
        {
            "ID": row["ID"],
            "CONTENT": str(row["TEXT"]),
            "metadata": _metadata_value(row["METADATA"]),
            "DIST": float(row["DIST"]),
        }
        for row in rows
    ]


def hybrid_search(query, namespace="knowledge", k=5, pool=20, c=60):
    v, t = vec_search(query, namespace, pool), kw_search(query, namespace, pool)
    scores, store = {}, {}
    for rank, r in enumerate(v):
        rid = r["ID"]; store[rid] = r; scores[rid] = scores.get(rid, 0) + 1.0 / (c + rank + 1)
    for rank, r in enumerate(t):
        rid = r["ID"]; store[rid] = r; scores[rid] = scores.get(rid, 0) + 1.0 / (c + rank + 1)
    ranked = sorted(scores, key=scores.get, reverse=True)[:k]
    return [dict(store[rid], rrf=round(scores[rid], 4)) for rid in ranked]


def rerank(query, candidates, k=5):
    if not _state["rerank"] or not candidates:
        return [dict(c, rerank_score=None) for c in candidates[:k]]
    docs = [str(c["CONTENT"])[:2000] for c in candidates]
    try:
        rows = q(f'''SELECT t.idx AS idx,
                 PREDICTION({RERANK} USING (:q || ' [SEP] ' || t.doc) AS DATA) AS score
                 FROM JSON_TABLE(:docs, '$[*]' COLUMNS (idx FOR ORDINALITY, doc VARCHAR2(4000) PATH '$')) t
                 ORDER BY score DESC''', {"q": query, "docs": json.dumps(docs)})
        return [dict(candidates[r["IDX"] - 1], rerank_score=round(float(r["SCORE"]), 3)) for r in rows[:k]]
    except Exception:
        return [dict(c, rerank_score=None) for c in candidates[:k]]


def retrieve(query, technique="hybrid", namespace="knowledge", k=5):
    if technique == "keyword":
        return kw_search(query, namespace, k)
    if technique == "vector":
        return vec_search(query, namespace, k)
    hits = hybrid_search(query, namespace, k=max(k, 8))
    if technique == "rerank":
        return rerank(query, hits, k)
    return hits[:k]


# ── semantic catalog ──────────────────────────────────────────────────────
def scan_semantic_layer():
    facts = []
    cols = q('''SELECT tc.table_name, tc.column_name, tc.data_type, cc.comments
        FROM user_tab_columns tc
        LEFT JOIN user_col_comments cc ON cc.table_name=tc.table_name AND cc.column_name=tc.column_name
        WHERE tc.table_name IN ('CUSTOMERS','PRODUCTS','ORDERS','ORDER_ITEMS')''')
    for c in cols:
        body = f"{c['TABLE_NAME']}.{c['COLUMN_NAME']} ({c['DATA_TYPE']})"
        if c["COMMENTS"]:
            body += f" -- {c['COMMENTS']}"
        facts.append((f"col:{c['TABLE_NAME']}.{c['COLUMN_NAME']}", body, "column"))
    for f in q('''SELECT a.table_name, a.column_name, c_pk.table_name AS ref_table
        FROM user_cons_columns a
        JOIN user_constraints c ON a.constraint_name=c.constraint_name AND c.constraint_type='R'
        JOIN user_constraints c_pk ON c.r_constraint_name=c_pk.constraint_name'''):
        facts.append((f"fk:{f['TABLE_NAME']}.{f['COLUMN_NAME']}",
                      f"{f['TABLE_NAME']}.{f['COLUMN_NAME']} joins to {f['REF_TABLE']}", "fk"))
    try:
        x(f"""DELETE FROM {VSTORE} WHERE JSON_VALUE(metadata,'$.namespace')='semantic'
              AND JSON_VALUE(metadata,'$.kind')='catalog'""")
    except Exception:
        pass
    add_texts([b for _, b, _ in facts],
              [{"kind": "catalog", "subject": s, "ftype": t} for s, b, t in facts], namespace="semantic")
    return len(facts)


def semantic_search(query, k=6):
    return vec_search(query, namespace="semantic", k=k)


def _seed_knowledge():
    n = q(f"SELECT COUNT(*) n FROM {VSTORE} WHERE JSON_VALUE(metadata,'$.namespace')='knowledge'")[0]["N"]
    if n > 0:
        return
    add_texts(
        ["The Outdoors category drove Q3 revenue growth.",
         "Supplier concentration is the top operational risk this quarter.",
         "A dual-sourcing decision for Outdoors is targeted for Q1.",
         "Customer churn rises sharply when delivery exceeds five days.",
         "Returns spike in the Apparel category right after the holidays.",
         "Enterprise-segment customers have the highest average order value."],
        [{"src": "kb"} for _ in range(6)], namespace="knowledge")
