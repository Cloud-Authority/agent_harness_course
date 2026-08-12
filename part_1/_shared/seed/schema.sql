-- Kata — enterprise schema for ERPA.
-- Deliberately co-located with agent memory: business data and the agent's memory of
-- decisions about that data live in one database, one transaction, one backup.

CREATE TABLE products (
  sku           VARCHAR2(32) PRIMARY KEY,
  name          VARCHAR2(120) NOT NULL,
  product_line  VARCHAR2(60) NOT NULL,
  category      VARCHAR2(40)  NOT NULL,   -- Outerwear | Tops | Bottoms | Innerwear | Loungewear | Accessories
  collection    VARCHAR2(60),
  season        VARCHAR2(20),             -- AW25 | SS26 | CORE
  launch_date   DATE,
  base_price    NUMBER(10,2) NOT NULL,
  unit_cost     NUMBER(10,2) NOT NULL,
  fabric        VARCHAR2(60),
  is_core       NUMBER(1) DEFAULT 0       -- core replenishes; seasonal marks down
);

CREATE TABLE variants (
  variant_id    VARCHAR2(40) PRIMARY KEY,
  sku           VARCHAR2(32) REFERENCES products(sku),
  size_code     VARCHAR2(8),              -- XXS..XXL (`SIZE` is reserved in Oracle 26ai)
  colour        VARCHAR2(40)
);

CREATE TABLE locations (
  location_id   VARCHAR2(24) PRIMARY KEY,
  region        VARCHAR2(24),             -- JP | UK | US | EU | SEA
  type          VARCHAR2(16),             -- DC | store | 3PL
  country       VARCHAR2(40),
  city          VARCHAR2(60)
);

CREATE TABLE inventory (
  variant_id    VARCHAR2(40) REFERENCES variants(variant_id),
  location_id   VARCHAR2(24) REFERENCES locations(location_id),
  on_hand       NUMBER, in_transit NUMBER, reserved NUMBER,
  reorder_point NUMBER,
  snapshot_date DATE,
  CONSTRAINT pk_inventory PRIMARY KEY (variant_id, location_id, snapshot_date)
);

CREATE TABLE customers (
  customer_id      VARCHAR2(32) PRIMARY KEY,   -- synthetic + pseudonymised
  region           VARCHAR2(24),
  segment          VARCHAR2(32),               -- new | repeat | lapsed | vip
  first_order_date DATE,
  lifetime_orders  NUMBER,
  lifetime_value   NUMBER(12,2)
);

CREATE TABLE orders (
  order_id    VARCHAR2(32) PRIMARY KEY,
  customer_id VARCHAR2(32) REFERENCES customers(customer_id),
  order_date  DATE,
  region      VARCHAR2(24),
  channel     VARCHAR2(24)                     -- web | app | store
);

CREATE TABLE order_lines (
  line_id    NUMBER PRIMARY KEY,
  order_id   VARCHAR2(32) REFERENCES orders(order_id),
  variant_id VARCHAR2(40) REFERENCES variants(variant_id),
  qty        NUMBER,
  unit_price NUMBER(10,2),
  discount   NUMBER(5,2)
);

CREATE TABLE returns (
  return_id   NUMBER PRIMARY KEY,
  order_id    VARCHAR2(32),
  variant_id  VARCHAR2(40),
  qty         NUMBER,
  reason_code VARCHAR2(24),                    -- size | quality | changed_mind | damaged
  return_date DATE
);

CREATE TABLE suppliers (
  supplier_id       VARCHAR2(24) PRIMARY KEY,
  name              VARCHAR2(80),
  lead_time_days    NUMBER,
  reliability_score NUMBER(3,2),
  minimum_order_qty NUMBER
);

CREATE TABLE product_suppliers (
  sku         VARCHAR2(32) PRIMARY KEY REFERENCES products(sku),
  supplier_id VARCHAR2(24) REFERENCES suppliers(supplier_id)
);

CREATE TABLE purchase_orders (
  po_id       VARCHAR2(32) PRIMARY KEY,
  variant_id  VARCHAR2(40),
  location_id VARCHAR2(24),
  qty         NUMBER,
  raised_date DATE,
  status      VARCHAR2(16)                     -- open | received | cancelled
);

-- Harness-owned tables share the same Oracle substrate as the business data.
-- Vector columns and the OAMP/LangGraph-managed tables are created by their adapters.
CREATE TABLE erpa_memories (
  memory_id   VARCHAR2(64) PRIMARY KEY,
  user_id     VARCHAR2(32) NOT NULL,
  memory_type VARCHAR2(16) NOT NULL,
  content     CLOB NOT NULL,
  metadata    CLOB,
  created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE erpa_briefs (
  brief_id    VARCHAR2(64) PRIMARY KEY,
  user_id     VARCHAR2(32) NOT NULL,
  content     CLOB NOT NULL,
  created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE erpa_brief_queue (
  request_id VARCHAR2(64) PRIMARY KEY,
  user_id VARCHAR2(32) NOT NULL,
  prompt VARCHAR2(200) NOT NULL,
  status VARCHAR2(16) DEFAULT 'queued' NOT NULL,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  completed_at TIMESTAMP,
  error_message VARCHAR2(2000)
);

CREATE TABLE erpa_file_storage (
  file_id VARCHAR2(64) PRIMARY KEY,
  mime_type VARCHAR2(120),
  content CLOB,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Session-scoped Oracle SecureFile scratchpad.  These rows are working state,
-- not long-term memory; the session-end trigger stages only opted-in files.
CREATE TABLE erpa_agent_sessions (
  session_id VARCHAR2(80) PRIMARY KEY,
  user_id VARCHAR2(80) NOT NULL,
  thread_id VARCHAR2(120) NOT NULL,
  status VARCHAR2(20) DEFAULT 'ACTIVE' NOT NULL,
  started_at TIMESTAMP DEFAULT SYSTIMESTAMP NOT NULL,
  ended_at TIMESTAMP
);

CREATE TABLE erpa_scratch_files (
  session_id VARCHAR2(80) REFERENCES erpa_agent_sessions(session_id),
  path VARCHAR2(400),
  content BLOB,
  is_dir CHAR(1) DEFAULT 'N' NOT NULL,
  promotion_state CHAR(1) DEFAULT 'N' NOT NULL,
  promote_on_end CHAR(1) DEFAULT 'N' NOT NULL,
  updated_at TIMESTAMP DEFAULT SYSTIMESTAMP NOT NULL,
  CONSTRAINT pk_erpa_scratch_files PRIMARY KEY(session_id,path)
) LOB(content) STORE AS SECUREFILE;

CREATE TABLE erpa_memory_promotion_queue (
  queue_id RAW(16) DEFAULT SYS_GUID() PRIMARY KEY,
  session_id VARCHAR2(80) NOT NULL,
  path VARCHAR2(400) NOT NULL,
  chunk CLOB NOT NULL,
  consumed CHAR(1) DEFAULT 'N' NOT NULL,
  staged_at TIMESTAMP DEFAULT SYSTIMESTAMP NOT NULL,
  consumed_at TIMESTAMP
);

-- A living semantic catalog: curated meaning plus schema/comments and observed
-- workload shapes.  The bootstrap process fills embeddings in Oracle itself.
CREATE TABLE erpa_semantic_hints (
  subject VARCHAR2(200) PRIMARY KEY,
  hint_type VARCHAR2(40) NOT NULL,
  hint_text VARCHAR2(2000) NOT NULL,
  priority NUMBER DEFAULT 100 NOT NULL
);

CREATE TABLE erpa_semantic_catalog (
  catalog_id VARCHAR2(200) PRIMARY KEY,
  source_type VARCHAR2(40) NOT NULL,
  catalog_text VARCHAR2(4000) NOT NULL,
  refreshed_at TIMESTAMP DEFAULT SYSTIMESTAMP NOT NULL,
  embedding VECTOR(384,FLOAT32)
);

CREATE TABLE erpa_tool_registry (
  tool_name VARCHAR2(80) PRIMARY KEY,
  description VARCHAR2(1000) NOT NULL,
  transport VARCHAR2(200) NOT NULL,
  embedding VECTOR(384,FLOAT32)
);

CREATE TABLE erpa_skill_registry (
  skill_name VARCHAR2(100) PRIMARY KEY,
  description VARCHAR2(1000) NOT NULL,
  body CLOB NOT NULL,
  body_sha256 VARCHAR2(64) NOT NULL,
  status VARCHAR2(20) DEFAULT 'ACTIVE' NOT NULL,
  embedding VECTOR(384,FLOAT32)
);

CREATE TABLE erpa_action_audit (
  action_id VARCHAR2(64) PRIMARY KEY,
  thread_id VARCHAR2(120) NOT NULL,
  action_type VARCHAR2(80) NOT NULL,
  payload CLOB NOT NULL,
  approval_state VARCHAR2(20) DEFAULT 'PENDING' NOT NULL,
  created_at TIMESTAMP DEFAULT SYSTIMESTAMP NOT NULL,
  approved_at TIMESTAMP
);

CREATE TABLE erpa_external_signals (
  signal_id VARCHAR2(80) PRIMARY KEY,
  observed_at DATE NOT NULL,
  region VARCHAR2(20) NOT NULL,
  signal_type VARCHAR2(40) NOT NULL,
  summary VARCHAR2(1000) NOT NULL,
  source_url VARCHAR2(500) NOT NULL
);

-- New orders placed through the educational storefront are intentionally separate
-- from the immutable historical commerce fixtures used by workshop assertions.
CREATE TABLE erpa_store_orders (
  order_id VARCHAR2(32) PRIMARY KEY,
  customer_name VARCHAR2(80) NOT NULL,
  email VARCHAR2(160) NOT NULL,
  order_date DATE NOT NULL,
  region VARCHAR2(24) NOT NULL,
  channel VARCHAR2(24) NOT NULL,
  status VARCHAR2(20) NOT NULL,
  total NUMBER(12,2) NOT NULL
);

CREATE TABLE erpa_store_order_lines (
  line_id NUMBER PRIMARY KEY,
  order_id VARCHAR2(32) REFERENCES erpa_store_orders(order_id),
  sku VARCHAR2(32) REFERENCES products(sku),
  variant_id VARCHAR2(40) REFERENCES variants(variant_id),
  location_id VARCHAR2(24) REFERENCES locations(location_id),
  qty NUMBER NOT NULL,
  unit_price NUMBER(10,2) NOT NULL
);
