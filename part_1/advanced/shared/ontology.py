"""Governed ontology projection and knowledge-graph retrieval for Total Recall.

Oracle's RDF documentation defines an ontology as classes, properties, and
optional instances.  This module keeps those three layers explicit in typed
application tables, projects operational business objects into graph nodes and
edges, and uses vector search only to choose seed entities.  Multi-hop impact is
established by traversing stored relationships, not by asking an LLM to invent
joins.

The projection is refreshed by a stored procedure.  When the application schema
has ``CREATE JOB``, a ``DBMS_SCHEDULER`` job invokes that procedure on a cadence.
The direct refresh endpoint remains available and is visibly labelled when a
least-privilege teaching account has not received the optional scheduler grant.
"""

from __future__ import annotations

import json
import re
import threading
import uuid
from array import array
from collections import defaultdict, deque
from datetime import datetime, timezone
from typing import Any, Iterable, Mapping, Sequence

from .config import AdvancedSettings, settings as default_settings
from .inspector import context_window
from .persistence import SemanticEncoder, json_safe, stable_hash, utcnow


TERM_TABLE = "ADV_ONTOLOGY_TERMS"
SOURCE_NODE_TABLE = "ADV_BUSINESS_OBJECTS"
SOURCE_EDGE_TABLE = "ADV_BUSINESS_LINKS"
NODE_TABLE = "ADV_ONTOLOGY_NODES"
EDGE_TABLE = "ADV_ONTOLOGY_EDGES"
REFRESH_TABLE = "ADV_ONTOLOGY_REFRESH_RUNS"
QUERY_TABLE = "ADV_ONTOLOGY_QUERY_RUNS"
REFRESH_PROCEDURE = "ADV_REFRESH_ONTOLOGY"
REFRESH_JOB = "ADV_ONTOLOGY_REFRESH_JOB"
BASE_URI = "https://example.test/ontology/supply-chain/"


ONTOLOGY_TERMS: tuple[dict[str, Any], ...] = (
    {"term_id": "BusinessObject", "kind": "class", "label": "Business object", "definition": "A governed enterprise object with stable identity and provenance."},
    {"term_id": "Supplier", "kind": "class", "parent": "BusinessObject", "label": "Supplier", "definition": "An organization that supplies a governed material or component."},
    {"term_id": "Component", "kind": "class", "parent": "BusinessObject", "label": "Component", "definition": "A material or part used by a product."},
    {"term_id": "Product", "kind": "class", "parent": "BusinessObject", "label": "Product", "definition": "A sellable product assembled from components."},
    {"term_id": "Plant", "kind": "class", "parent": "BusinessObject", "label": "Plant", "definition": "A manufacturing site responsible for products."},
    {"term_id": "Customer", "kind": "class", "parent": "BusinessObject", "label": "Customer", "definition": "An organization receiving an order."},
    {"term_id": "CustomerOrder", "kind": "class", "parent": "BusinessObject", "label": "Customer order", "definition": "A dated commercial commitment for a product and customer."},
    {"term_id": "Contract", "kind": "class", "parent": "BusinessObject", "label": "Contract", "definition": "A governed agreement containing service and compliance obligations."},
    {"term_id": "Evidence", "kind": "class", "parent": "BusinessObject", "label": "Evidence", "definition": "A dated record used to establish control status."},
    {"term_id": "Control", "kind": "class", "parent": "BusinessObject", "label": "Control", "definition": "A required business or compliance check."},
    {"term_id": "Policy", "kind": "class", "parent": "BusinessObject", "label": "Policy", "definition": "A governed rule that defines applicability and thresholds."},
    {"term_id": "RiskEvent", "kind": "class", "parent": "BusinessObject", "label": "Risk event", "definition": "An event whose effect must be traced across business relationships."},
    {"term_id": "RemediationAction", "kind": "class", "parent": "BusinessObject", "label": "Remediation action", "definition": "An owned action that reduces or closes a risk."},
    {"term_id": "Skill", "kind": "class", "parent": "BusinessObject", "label": "Skill", "definition": "A versioned procedural document available to the harness."},
    {"term_id": "Tool", "kind": "class", "parent": "BusinessObject", "label": "Tool", "definition": "A model-facing callable contract available to the harness."},
    {"term_id": "supplies", "kind": "property", "domain": "Supplier", "range": "Component", "label": "supplies", "definition": "Connects a supplier to a supplied component."},
    {"term_id": "usedIn", "kind": "property", "domain": "Component", "range": "Product", "label": "used in", "definition": "Connects a component to a product that depends on it."},
    {"term_id": "producedAt", "kind": "property", "domain": "Product", "range": "Plant", "label": "produced at", "definition": "Connects a product to its production site."},
    {"term_id": "containsProduct", "kind": "property", "domain": "CustomerOrder", "range": "Product", "label": "contains product", "definition": "Connects an order to the ordered product."},
    {"term_id": "orderedBy", "kind": "property", "domain": "CustomerOrder", "range": "Customer", "label": "ordered by", "definition": "Connects an order to its customer."},
    {"term_id": "governedBy", "kind": "property", "domain": "CustomerOrder", "range": "Contract", "label": "governed by", "definition": "Connects a commercial commitment to its contract."},
    {"term_id": "evidences", "kind": "property", "domain": "Evidence", "range": "Control", "label": "evidences", "definition": "Connects evidence to the control it supports."},
    {"term_id": "appliesTo", "kind": "property", "domain": "Control", "range": "Supplier", "label": "applies to", "definition": "Connects a control to the governed supplier."},
    {"term_id": "definedBy", "kind": "property", "domain": "Control", "range": "Policy", "label": "defined by", "definition": "Connects a control to its governing policy."},
    {"term_id": "triggeredBy", "kind": "property", "domain": "RiskEvent", "range": "Evidence", "label": "triggered by", "definition": "Connects a risk event to the evidence condition that triggered it."},
    {"term_id": "affects", "kind": "property", "domain": "RiskEvent", "range": "Supplier", "label": "affects", "definition": "Connects a risk event to its initial affected supplier."},
    {"term_id": "mitigatedBy", "kind": "property", "domain": "RiskEvent", "range": "RemediationAction", "label": "mitigated by", "definition": "Connects a risk event to an owned remediation action."},
    {"term_id": "handledBySkill", "kind": "property", "domain": "RiskEvent", "range": "Skill", "label": "handled by skill", "definition": "Connects a risk event to the procedure authorized to handle it."},
    {"term_id": "usesTool", "kind": "property", "domain": "Skill", "range": "Tool", "label": "uses tool", "definition": "Connects a procedure to a required callable contract."},
)


BUSINESS_OBJECTS: tuple[dict[str, Any], ...] = (
    {"id": "SUP-NORTHSTAR", "class": "Supplier", "label": "Northstar Textiles", "description": "High-risk production-critical EU supplier with 4.8 million USD annual spend.", "status": "review_required", "source": "supplier-master"},
    {"id": "SUP-IBERIA", "class": "Supplier", "label": "Iberia Materials", "description": "Approved alternate supplier for the XR-12 treatment component.", "status": "approved_alternate", "source": "supplier-master"},
    {"id": "COMP-XR12", "class": "Component", "label": "XR-12 restricted-substance treatment", "description": "Chemical treatment used by the ThermaCore outerwear range.", "status": "dependent", "source": "product-lifecycle"},
    {"id": "PROD-THERMACORE", "class": "Product", "label": "ThermaCore Jacket", "description": "Production outerwear product whose material specification requires XR-12.", "status": "active", "source": "product-lifecycle"},
    {"id": "PLANT-LEEDS", "class": "Plant", "label": "Leeds Manufacturing Plant", "description": "Primary European production site for the ThermaCore Jacket.", "status": "operational", "source": "manufacturing"},
    {"id": "CUST-ALPINE", "class": "Customer", "label": "Alpine Outfitters", "description": "Strategic retail customer with a dated winter-delivery commitment.", "status": "active", "source": "customer-master"},
    {"id": "ORDER-8842", "class": "CustomerOrder", "label": "Order 8842", "description": "18,000 ThermaCore Jackets due before the winter launch window.", "status": "at_risk", "source": "order-management"},
    {"id": "CONTRACT-77", "class": "Contract", "label": "Alpine supply agreement 77", "description": "Contract with delivery, restricted-substance, and notification obligations.", "status": "active", "source": "contract-management"},
    {"id": "EVID-RSC-2026", "class": "Evidence", "label": "Restricted-substance certificate EV-219", "description": "Northstar certificate is 401 days old; policy limit is 365 days.", "status": "expired", "source": "compliance-evidence"},
    {"id": "CTRL-RSC-365", "class": "Control", "label": "Restricted-substance freshness control", "description": "Blocks production qualification when certificate age exceeds 365 days.", "status": "failed", "source": "control-library"},
    {"id": "POLICY-365", "class": "Policy", "label": "Evidence freshness policy", "description": "Supplier compliance evidence must be no more than 365 days old.", "status": "effective", "source": "policy-library"},
    {"id": "RISK-CERT-EXPIRY", "class": "RiskEvent", "label": "Northstar certificate expiry", "description": "Potential product, plant, order, customer, and contract impact caused by expired evidence.", "status": "open", "source": "risk-register"},
    {"id": "ACTION-REPLACE-CERT", "class": "RemediationAction", "label": "Obtain replacement certificate", "description": "Compliance owner must obtain and validate replacement evidence within seven days.", "status": "open", "source": "remediation-tracker"},
    {"id": "SKILL-IMPACT", "class": "Skill", "label": "Supply-chain impact analysis", "description": "Versioned procedure for semantic seed retrieval, graph traversal, citation, and escalation.", "status": "active", "source": "skillbox"},
    {"id": "TOOL-ONTOLOGY-SEARCH", "class": "Tool", "label": "ontology_search", "description": "Find ontology seed entities by meaning and return governed identifiers.", "status": "active", "source": "toolbox"},
    {"id": "TOOL-TRACE-IMPACT", "class": "Tool", "label": "trace_business_impact", "description": "Traverse stored relationships and return bounded impact paths.", "status": "active", "source": "toolbox"},
    {"id": "TOOL-COUNT-AFFECTED", "class": "Tool", "label": "count_affected_entities", "description": "Count unique affected entity IDs inside a disposable sandbox and verify the result in the host.", "status": "active", "source": "toolbox"},
)


BUSINESS_LINKS: tuple[dict[str, str], ...] = (
    {"id": "L01", "subject": "SUP-NORTHSTAR", "predicate": "supplies", "object": "COMP-XR12", "evidence": "supplier-master:SUP-NORTHSTAR"},
    {"id": "L02", "subject": "SUP-IBERIA", "predicate": "supplies", "object": "COMP-XR12", "evidence": "supplier-master:SUP-IBERIA"},
    {"id": "L03", "subject": "COMP-XR12", "predicate": "usedIn", "object": "PROD-THERMACORE", "evidence": "bom:THERMACORE:XR12"},
    {"id": "L04", "subject": "PROD-THERMACORE", "predicate": "producedAt", "object": "PLANT-LEEDS", "evidence": "routing:THERMACORE:LEEDS"},
    {"id": "L05", "subject": "ORDER-8842", "predicate": "containsProduct", "object": "PROD-THERMACORE", "evidence": "order-line:8842:1"},
    {"id": "L06", "subject": "ORDER-8842", "predicate": "orderedBy", "object": "CUST-ALPINE", "evidence": "order:8842"},
    {"id": "L07", "subject": "ORDER-8842", "predicate": "governedBy", "object": "CONTRACT-77", "evidence": "contract-link:8842:77"},
    {"id": "L08", "subject": "EVID-RSC-2026", "predicate": "evidences", "object": "CTRL-RSC-365", "evidence": "evidence:EV-219"},
    {"id": "L09", "subject": "CTRL-RSC-365", "predicate": "appliesTo", "object": "SUP-NORTHSTAR", "evidence": "control-scope:CTRL-RSC-365"},
    {"id": "L10", "subject": "CTRL-RSC-365", "predicate": "definedBy", "object": "POLICY-365", "evidence": "policy-map:CTRL-RSC-365"},
    {"id": "L11", "subject": "RISK-CERT-EXPIRY", "predicate": "triggeredBy", "object": "EVID-RSC-2026", "evidence": "risk:RISK-CERT-EXPIRY"},
    {"id": "L12", "subject": "RISK-CERT-EXPIRY", "predicate": "affects", "object": "SUP-NORTHSTAR", "evidence": "risk:RISK-CERT-EXPIRY"},
    {"id": "L13", "subject": "RISK-CERT-EXPIRY", "predicate": "mitigatedBy", "object": "ACTION-REPLACE-CERT", "evidence": "remediation:ACTION-REPLACE-CERT"},
    {"id": "L14", "subject": "RISK-CERT-EXPIRY", "predicate": "handledBySkill", "object": "SKILL-IMPACT", "evidence": "routing:impact-analysis"},
    {"id": "L15", "subject": "SKILL-IMPACT", "predicate": "usesTool", "object": "TOOL-ONTOLOGY-SEARCH", "evidence": "skill:impact-analysis"},
    {"id": "L16", "subject": "SKILL-IMPACT", "predicate": "usesTool", "object": "TOOL-TRACE-IMPACT", "evidence": "skill:impact-analysis"},
    {"id": "L17", "subject": "SKILL-IMPACT", "predicate": "usesTool", "object": "TOOL-COUNT-AFFECTED", "evidence": "skill:impact-analysis"},
)


def _json_from_db(value: Any) -> Any:
    if hasattr(value, "read"):
        value = value.read()
    if isinstance(value, str):
        return json.loads(value)
    return json_safe(value)


class OntologyStore:
    """Typed ontology, operational projection, vector seeds, and graph traversal."""

    def __init__(
        self,
        course_settings: AdvancedSettings = default_settings,
        *,
        pool: Any = None,
        encoder: SemanticEncoder | None = None,
    ) -> None:
        self.settings = course_settings
        self.pool = pool
        self.encoder = encoder or SemanticEncoder(course_settings)
        self._lock = threading.RLock()
        self._terms: dict[str, dict[str, Any]] = {}
        self._source_nodes: dict[str, dict[str, Any]] = {}
        self._source_edges: dict[str, dict[str, Any]] = {}
        self._nodes: dict[str, dict[str, Any]] = {}
        self._edges: dict[str, dict[str, Any]] = {}
        self._refreshes: list[dict[str, Any]] = []
        self._queries: list[dict[str, Any]] = []
        self.hnsw_active = False
        self.hnsw_fallback: str | None = None
        self._last_context = context_window(
            [{"title": "Use-case objective", "kind": "user", "content": self.default_question()}],
            provider="none",
            model="none",
            phase="awaiting_query",
            actual_model_call=False,
            max_tokens=12_000,
        )
        if course_settings.backend == "oracle":
            if pool is None:
                raise RuntimeError("Oracle ontology requires the shared Oracle pool")
            self._setup_oracle()
        elif course_settings.backend == "memory":
            self._setup_memory()
        else:
            raise ValueError("ADVANCED_BACKEND must be oracle or memory")

    @staticmethod
    def default_question() -> str:
        return (
            "Northstar's restricted-substance certificate is expired. Which products, "
            "plants, customer orders, customers, contracts, policies, remediation actions, "
            "Skills, and Tools are connected to the risk, and what should the operator do?"
        )

    @property
    def dimensions(self) -> int:
        return int(self.settings.embedding_dimensions)

    @staticmethod
    def _error_code(exc: Exception) -> int | None:
        details = exc.args[0] if getattr(exc, "args", ()) else None
        return int(getattr(details, "code", 0) or 0) or None

    @staticmethod
    def _vector(values: Sequence[float]) -> array:
        return array("f", (float(item) for item in values))

    def _ddl(self, statement: str, *, vector_fallback: bool = False) -> bool:
        with self.pool.acquire() as connection:
            with connection.cursor() as cursor:
                try:
                    cursor.execute(statement)
                except Exception as exc:
                    if self._error_code(exc) == 955:
                        return True
                    if vector_fallback and self._error_code(exc) == 51962:
                        return False
                    raise
        return True

    def _setup_memory(self) -> None:
        self._terms = {item["term_id"]: self._term_row(item) for item in ONTOLOGY_TERMS}
        self._source_nodes = {item["id"]: self._source_node_row(item) for item in BUSINESS_OBJECTS}
        self._source_edges = {item["id"]: self._source_edge_row(item) for item in BUSINESS_LINKS}
        self.refresh(trigger="initial-memory-projection")

    def _setup_oracle(self) -> None:
        dim = self.dimensions
        self._ddl(
            f"""CREATE TABLE {TERM_TABLE} (
                tenant_id VARCHAR2(120) NOT NULL,
                term_id VARCHAR2(120) NOT NULL,
                term_kind VARCHAR2(20) NOT NULL,
                uri VARCHAR2(600) NOT NULL,
                label VARCHAR2(300) NOT NULL,
                definition VARCHAR2(2000) NOT NULL,
                parent_term_id VARCHAR2(120),
                domain_class VARCHAR2(120),
                range_class VARCHAR2(120),
                updated_at TIMESTAMP DEFAULT SYSTIMESTAMP NOT NULL,
                CONSTRAINT ADV_ONT_TERMS_PK PRIMARY KEY (tenant_id, term_id))"""
        )
        self._ddl(
            f"""CREATE TABLE {SOURCE_NODE_TABLE} (
                tenant_id VARCHAR2(120) NOT NULL,
                object_id VARCHAR2(160) NOT NULL,
                class_id VARCHAR2(120) NOT NULL,
                label VARCHAR2(400) NOT NULL,
                description VARCHAR2(2000) NOT NULL,
                status VARCHAR2(80) NOT NULL,
                source_system VARCHAR2(160) NOT NULL,
                attributes JSON NOT NULL,
                source_updated_at TIMESTAMP DEFAULT SYSTIMESTAMP NOT NULL,
                CONSTRAINT ADV_BIZ_OBJECTS_PK PRIMARY KEY (tenant_id, object_id))"""
        )
        self._ddl(
            f"""CREATE TABLE {SOURCE_EDGE_TABLE} (
                tenant_id VARCHAR2(120) NOT NULL,
                link_id VARCHAR2(160) NOT NULL,
                subject_id VARCHAR2(160) NOT NULL,
                predicate_id VARCHAR2(120) NOT NULL,
                object_id VARCHAR2(160) NOT NULL,
                evidence_ref VARCHAR2(600) NOT NULL,
                attributes JSON NOT NULL,
                source_updated_at TIMESTAMP DEFAULT SYSTIMESTAMP NOT NULL,
                CONSTRAINT ADV_BIZ_LINKS_PK PRIMARY KEY (tenant_id, link_id))"""
        )
        self._ddl(
            f"""CREATE TABLE {NODE_TABLE} (
                tenant_id VARCHAR2(120) NOT NULL,
                node_id VARCHAR2(160) NOT NULL,
                class_id VARCHAR2(120) NOT NULL,
                label VARCHAR2(400) NOT NULL,
                semantic_text VARCHAR2(4000) NOT NULL,
                status VARCHAR2(80) NOT NULL,
                source_system VARCHAR2(160) NOT NULL,
                attributes JSON NOT NULL,
                source_updated_at TIMESTAMP NOT NULL,
                embedding VECTOR({dim}, FLOAT32),
                refreshed_at TIMESTAMP DEFAULT SYSTIMESTAMP NOT NULL,
                CONSTRAINT ADV_ONT_NODES_PK PRIMARY KEY (tenant_id, node_id))"""
        )
        self._ddl(
            f"""CREATE TABLE {EDGE_TABLE} (
                tenant_id VARCHAR2(120) NOT NULL,
                edge_id VARCHAR2(160) NOT NULL,
                subject_id VARCHAR2(160) NOT NULL,
                predicate_id VARCHAR2(120) NOT NULL,
                object_id VARCHAR2(160) NOT NULL,
                evidence_ref VARCHAR2(600) NOT NULL,
                validation_status VARCHAR2(40) NOT NULL,
                source_updated_at TIMESTAMP NOT NULL,
                refreshed_at TIMESTAMP DEFAULT SYSTIMESTAMP NOT NULL,
                CONSTRAINT ADV_ONT_EDGES_PK PRIMARY KEY (tenant_id, edge_id))"""
        )
        self._ddl(
            f"""CREATE TABLE {REFRESH_TABLE} (
                tenant_id VARCHAR2(120) NOT NULL,
                run_id VARCHAR2(64) NOT NULL,
                trigger_type VARCHAR2(80) NOT NULL,
                started_at TIMESTAMP NOT NULL,
                completed_at TIMESTAMP,
                node_count NUMBER DEFAULT 0 NOT NULL,
                edge_count NUMBER DEFAULT 0 NOT NULL,
                status VARCHAR2(40) NOT NULL,
                detail VARCHAR2(2000),
                CONSTRAINT ADV_ONT_REFRESH_PK PRIMARY KEY (tenant_id, run_id))"""
        )
        self._ddl(
            f"""CREATE TABLE {QUERY_TABLE} (
                tenant_id VARCHAR2(120) NOT NULL,
                query_id VARCHAR2(64) NOT NULL,
                thread_id VARCHAR2(160) NOT NULL,
                question VARCHAR2(2000) NOT NULL,
                seed_nodes JSON NOT NULL,
                path_ids JSON NOT NULL,
                answer CLOB NOT NULL,
                citations JSON NOT NULL,
                verified CHAR(1) NOT NULL,
                model_provider VARCHAR2(160) NOT NULL,
                created_at TIMESTAMP DEFAULT SYSTIMESTAMP NOT NULL,
                CONSTRAINT ADV_ONT_QUERY_PK PRIMARY KEY (tenant_id, query_id))"""
        )
        self._create_refresh_procedure()
        self._seed_oracle()
        self._call_refresh_procedure()
        self._backfill_embeddings()
        self.hnsw_active = self._ddl(
            f"""CREATE VECTOR INDEX ADV_ONT_NODES_HNSW ON {NODE_TABLE} (embedding)
                ORGANIZATION INMEMORY NEIGHBOR GRAPH DISTANCE COSINE
                WITH TARGET ACCURACY 95""",
            vector_fallback=True,
        )
        if not self.hnsw_active:
            self.hnsw_fallback = "exact cosine (ORA-51962: vector memory pool full)"
        self.install_scheduler()

    @staticmethod
    def _term_row(item: Mapping[str, Any]) -> dict[str, Any]:
        term_id = str(item["term_id"])
        return {
            "term_id": term_id,
            "term_kind": str(item["kind"]),
            "uri": BASE_URI + term_id,
            "label": str(item["label"]),
            "definition": str(item["definition"]),
            "parent_term_id": item.get("parent"),
            "domain_class": item.get("domain"),
            "range_class": item.get("range"),
        }

    @staticmethod
    def _source_node_row(item: Mapping[str, Any]) -> dict[str, Any]:
        attributes = {key: value for key, value in item.items() if key not in {"id", "class", "label", "description", "status", "source"}}
        return {
            "object_id": str(item["id"]),
            "class_id": str(item["class"]),
            "label": str(item["label"]),
            "description": str(item["description"]),
            "status": str(item["status"]),
            "source_system": str(item["source"]),
            "attributes": attributes,
            "source_updated_at": utcnow(),
        }

    @staticmethod
    def _source_edge_row(item: Mapping[str, Any]) -> dict[str, Any]:
        return {
            "link_id": str(item["id"]),
            "subject_id": str(item["subject"]),
            "predicate_id": str(item["predicate"]),
            "object_id": str(item["object"]),
            "evidence_ref": str(item["evidence"]),
            "attributes": {},
            "source_updated_at": utcnow(),
        }

    def _seed_oracle(self) -> None:
        tenant = self.settings.tenant_id
        with self.pool.acquire() as connection:
            with connection.cursor() as cursor:
                for raw in ONTOLOGY_TERMS:
                    item = self._term_row(raw)
                    cursor.execute(
                        f"""MERGE INTO {TERM_TABLE} d
                            USING (SELECT :tenant tenant_id,:term_id term_id FROM dual) s
                            ON (d.tenant_id=s.tenant_id AND d.term_id=s.term_id)
                            WHEN MATCHED THEN UPDATE SET term_kind=:kind,uri=:uri,label=:label,
                                definition=:definition,parent_term_id=:parent,domain_class=:domain,
                                range_class=:range,updated_at=SYSTIMESTAMP
                            WHEN NOT MATCHED THEN INSERT
                                (tenant_id,term_id,term_kind,uri,label,definition,parent_term_id,
                                 domain_class,range_class)
                                VALUES (:tenant,:term_id,:kind,:uri,:label,:definition,:parent,:domain,:range)""",
                        {"tenant": tenant, "term_id": item["term_id"], "kind": item["term_kind"], "uri": item["uri"], "label": item["label"], "definition": item["definition"], "parent": item["parent_term_id"], "domain": item["domain_class"], "range": item["range_class"]},
                    )
                for raw in BUSINESS_OBJECTS:
                    item = self._source_node_row(raw)
                    cursor.execute(
                        f"""MERGE INTO {SOURCE_NODE_TABLE} d
                            USING (SELECT :tenant tenant_id,:object_id object_id FROM dual) s
                            ON (d.tenant_id=s.tenant_id AND d.object_id=s.object_id)
                            WHEN MATCHED THEN UPDATE SET class_id=:class_id,label=:label,
                                description=:description,status=:status,source_system=:source,
                                attributes=:attributes
                            WHEN NOT MATCHED THEN INSERT
                                (tenant_id,object_id,class_id,label,description,status,source_system,attributes)
                                VALUES (:tenant,:object_id,:class_id,:label,:description,:status,:source,:attributes)""",
                        {"tenant": tenant, "object_id": item["object_id"], "class_id": item["class_id"], "label": item["label"], "description": item["description"], "status": item["status"], "source": item["source_system"], "attributes": json.dumps(item["attributes"])},
                    )
                for raw in BUSINESS_LINKS:
                    item = self._source_edge_row(raw)
                    cursor.execute(
                        f"""MERGE INTO {SOURCE_EDGE_TABLE} d
                            USING (SELECT :tenant tenant_id,:link_id link_id FROM dual) s
                            ON (d.tenant_id=s.tenant_id AND d.link_id=s.link_id)
                            WHEN MATCHED THEN UPDATE SET subject_id=:subject,predicate_id=:predicate,
                                object_id=:object,evidence_ref=:evidence,attributes=:attributes
                            WHEN NOT MATCHED THEN INSERT
                                (tenant_id,link_id,subject_id,predicate_id,object_id,evidence_ref,attributes)
                                VALUES (:tenant,:link_id,:subject,:predicate,:object,:evidence,:attributes)""",
                        {"tenant": tenant, "link_id": item["link_id"], "subject": item["subject_id"], "predicate": item["predicate_id"], "object": item["object_id"], "evidence": item["evidence_ref"], "attributes": json.dumps(item["attributes"])},
                    )
            connection.commit()

    def _create_refresh_procedure(self) -> None:
        statement = f"""CREATE OR REPLACE PROCEDURE {REFRESH_PROCEDURE} AS
            v_run_id VARCHAR2(64) := RAWTOHEX(SYS_GUID());
            v_nodes NUMBER := 0;
            v_edges NUMBER := 0;
            v_error VARCHAR2(2000);
            v_trigger VARCHAR2(80) := CASE
              WHEN UPPER(SYS_CONTEXT('USERENV','MODULE')) LIKE '%SCHEDULER%' THEN 'DBMS_SCHEDULER'
              ELSE 'direct-stored-procedure' END;
          BEGIN
            INSERT INTO {REFRESH_TABLE}
              (tenant_id,run_id,trigger_type,started_at,status)
              SELECT DISTINCT tenant_id,v_run_id,v_trigger,SYSTIMESTAMP,'running'
              FROM {SOURCE_NODE_TABLE};

            MERGE INTO {NODE_TABLE} d
            USING (
              SELECT b.tenant_id,b.object_id node_id,b.class_id,b.label,
                     b.label || '. ' || b.description || '. Type ' || b.class_id ||
                     '. Status ' || b.status || '. Source ' || b.source_system semantic_text,
                     b.status,b.source_system,b.attributes,b.source_updated_at
              FROM {SOURCE_NODE_TABLE} b
              JOIN {TERM_TABLE} t ON t.tenant_id=b.tenant_id
                AND t.term_id=b.class_id AND t.term_kind='class'
            ) s
            ON (d.tenant_id=s.tenant_id AND d.node_id=s.node_id)
            WHEN MATCHED THEN UPDATE SET d.class_id=s.class_id,d.label=s.label,
              d.embedding=CASE WHEN d.semantic_text=s.semantic_text THEN d.embedding ELSE NULL END,
              d.semantic_text=s.semantic_text,d.status=s.status,d.source_system=s.source_system,
              d.attributes=s.attributes,d.source_updated_at=s.source_updated_at,d.refreshed_at=SYSTIMESTAMP
            WHEN NOT MATCHED THEN INSERT
              (tenant_id,node_id,class_id,label,semantic_text,status,source_system,attributes,
               source_updated_at,embedding,refreshed_at)
              VALUES (s.tenant_id,s.node_id,s.class_id,s.label,s.semantic_text,s.status,
                      s.source_system,s.attributes,s.source_updated_at,NULL,SYSTIMESTAMP);

            DELETE FROM {NODE_TABLE} d WHERE NOT EXISTS (
              SELECT 1 FROM {SOURCE_NODE_TABLE} s
              WHERE s.tenant_id=d.tenant_id AND s.object_id=d.node_id);

            MERGE INTO {EDGE_TABLE} d
            USING (
              SELECT l.tenant_id,l.link_id edge_id,l.subject_id,l.predicate_id,l.object_id,
                     l.evidence_ref,l.source_updated_at,
                     CASE WHEN p.term_kind='property' AND sn.class_id=p.domain_class
                               AND onode.class_id=p.range_class THEN 'valid' ELSE 'review' END validation_status
              FROM {SOURCE_EDGE_TABLE} l
              JOIN {TERM_TABLE} p ON p.tenant_id=l.tenant_id AND p.term_id=l.predicate_id
              JOIN {SOURCE_NODE_TABLE} sn ON sn.tenant_id=l.tenant_id AND sn.object_id=l.subject_id
              JOIN {SOURCE_NODE_TABLE} onode ON onode.tenant_id=l.tenant_id AND onode.object_id=l.object_id
            ) s
            ON (d.tenant_id=s.tenant_id AND d.edge_id=s.edge_id)
            WHEN MATCHED THEN UPDATE SET d.subject_id=s.subject_id,d.predicate_id=s.predicate_id,
              d.object_id=s.object_id,d.evidence_ref=s.evidence_ref,
              d.validation_status=s.validation_status,d.source_updated_at=s.source_updated_at,
              d.refreshed_at=SYSTIMESTAMP
            WHEN NOT MATCHED THEN INSERT
              (tenant_id,edge_id,subject_id,predicate_id,object_id,evidence_ref,
               validation_status,source_updated_at,refreshed_at)
              VALUES (s.tenant_id,s.edge_id,s.subject_id,s.predicate_id,s.object_id,
                      s.evidence_ref,s.validation_status,s.source_updated_at,SYSTIMESTAMP);

            DELETE FROM {EDGE_TABLE} d WHERE NOT EXISTS (
              SELECT 1 FROM {SOURCE_EDGE_TABLE} s
              WHERE s.tenant_id=d.tenant_id AND s.link_id=d.edge_id);

            SELECT COUNT(*) INTO v_nodes FROM {NODE_TABLE};
            SELECT COUNT(*) INTO v_edges FROM {EDGE_TABLE};
            UPDATE {REFRESH_TABLE} SET completed_at=SYSTIMESTAMP,node_count=v_nodes,
              edge_count=v_edges,status='succeeded',detail='operational rows projected and validated'
              WHERE run_id=v_run_id;
            COMMIT;
          EXCEPTION WHEN OTHERS THEN
            v_error := SUBSTR(SQLERRM,1,2000);
            ROLLBACK;
            INSERT INTO {REFRESH_TABLE}
              (tenant_id,run_id,trigger_type,started_at,completed_at,status,detail)
              SELECT DISTINCT tenant_id,v_run_id,v_trigger,SYSTIMESTAMP,SYSTIMESTAMP,
                     'failed',v_error FROM {SOURCE_NODE_TABLE};
            COMMIT;
            RAISE;
          END;"""
        with self.pool.acquire() as connection:
            with connection.cursor() as cursor:
                cursor.execute(statement)

    def _call_refresh_procedure(self) -> None:
        with self.pool.acquire() as connection:
            with connection.cursor() as cursor:
                cursor.callproc(REFRESH_PROCEDURE)

    def _backfill_embeddings(self) -> int:
        if self.settings.backend == "memory":
            return 0
        with self.pool.acquire() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    f"SELECT node_id,semantic_text FROM {NODE_TABLE} "
                    "WHERE tenant_id=:tenant AND embedding IS NULL ORDER BY node_id",
                    {"tenant": self.settings.tenant_id},
                )
                rows = [(str(row[0]), str(row[1])) for row in cursor.fetchall()]
                for node_id, text in rows:
                    cursor.execute(
                        f"UPDATE {NODE_TABLE} SET embedding=:embedding "
                        "WHERE tenant_id=:tenant AND node_id=:node_id",
                        {"embedding": self._vector(self.encoder.embed(text)), "tenant": self.settings.tenant_id, "node_id": node_id},
                    )
            connection.commit()
        return len(rows)

    def _has_create_job(self) -> bool:
        if self.settings.backend != "oracle":
            return False
        with self.pool.acquire() as connection:
            with connection.cursor() as cursor:
                cursor.execute("SELECT COUNT(*) FROM user_sys_privs WHERE privilege='CREATE JOB'")
                return bool(cursor.fetchone()[0])

    def install_scheduler(self) -> dict[str, Any]:
        if self.settings.backend != "oracle":
            return {"installed": False, "provider": "memory simulation", "reason": "DBMS_SCHEDULER requires Oracle"}
        if not self._has_create_job():
            return {
                "installed": False,
                "provider": "Oracle DBMS_SCHEDULER",
                "reason": "application user lacks CREATE JOB",
                "required_grant": f"GRANT CREATE JOB TO {self.settings.ora_user}",
            }
        with self.pool.acquire() as connection:
            with connection.cursor() as cursor:
                job_action = (
                    "BEGIN DBMS_APPLICATION_INFO.SET_MODULE("
                    "'ADV_ONTOLOGY_SCHEDULER', NULL); "
                    f"{REFRESH_PROCEDURE}; END;"
                )
                cursor.execute(
                    "SELECT job_type,job_action FROM user_scheduler_jobs WHERE job_name=:job_name",
                    {"job_name": REFRESH_JOB},
                )
                existing = cursor.fetchone()
                exists = existing is not None
                replace = bool(
                    existing
                    and (
                        str(existing[0]) != "PLSQL_BLOCK"
                        or "ADV_ONTOLOGY_SCHEDULER" not in str(existing[1] or "")
                    )
                )
                if replace:
                    cursor.callproc(
                        "DBMS_SCHEDULER.DROP_JOB",
                        keyword_parameters={"job_name": REFRESH_JOB, "force": True},
                    )
                    exists = False
                if not exists:
                    cursor.callproc(
                        "DBMS_SCHEDULER.CREATE_JOB",
                        keyword_parameters={
                            "job_name": REFRESH_JOB,
                            "job_type": "PLSQL_BLOCK",
                            "job_action": job_action,
                            "repeat_interval": "FREQ=MINUTELY;INTERVAL=15",
                            "enabled": True,
                            "auto_drop": False,
                            "comments": "Refresh the Total Recall business ontology projection.",
                        },
                    )
                else:
                    cursor.callproc(
                        "DBMS_SCHEDULER.SET_ATTRIBUTE",
                        keyword_parameters={"name": REFRESH_JOB, "attribute": "repeat_interval", "value": "FREQ=MINUTELY;INTERVAL=15"},
                    )
                    cursor.callproc("DBMS_SCHEDULER.ENABLE", [REFRESH_JOB])
            connection.commit()
        return self.scheduler_status()

    def scheduler_status(self) -> dict[str, Any]:
        if self.settings.backend != "oracle":
            return {
                "provider": "memory simulation",
                "job_name": REFRESH_JOB,
                "installed": False,
                "enabled": False,
                "repeat_interval": "FREQ=MINUTELY;INTERVAL=15",
                "claim_boundary": "The offline profile demonstrates the contract, not Oracle scheduling.",
            }
        if not self._has_create_job():
            return {
                "provider": "Oracle DBMS_SCHEDULER",
                "job_name": REFRESH_JOB,
                "installed": False,
                "enabled": False,
                "repeat_interval": "FREQ=MINUTELY;INTERVAL=15",
                "reason": "CREATE JOB has not been granted to the least-privilege application user",
                "required_grant": f"GRANT CREATE JOB TO {self.settings.ora_user}",
            }
        with self.pool.acquire() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """SELECT enabled,state,repeat_interval,
                              TO_CHAR(last_start_date,'YYYY-MM-DD"T"HH24:MI:SS.FF TZH:TZM'),
                              TO_CHAR(next_run_date,'YYYY-MM-DD"T"HH24:MI:SS.FF TZH:TZM'),
                              run_count,failure_count
                       FROM user_scheduler_jobs WHERE job_name=:name""",
                    {"name": REFRESH_JOB},
                )
                row = cursor.fetchone()
                cursor.execute(
                    """SELECT status,
                              TO_CHAR(actual_start_date,'YYYY-MM-DD"T"HH24:MI:SS.FF TZH:TZM'),
                              TO_CHAR(run_duration),additional_info
                       FROM user_scheduler_job_run_details
                       WHERE job_name=:name ORDER BY log_id DESC FETCH FIRST 1 ROW ONLY""",
                    {"name": REFRESH_JOB},
                )
                latest_run = cursor.fetchone()
        if row is None:
            return {"provider": "Oracle DBMS_SCHEDULER", "job_name": REFRESH_JOB, "installed": False, "enabled": False}
        return {
            "provider": "Oracle DBMS_SCHEDULER",
            "job_name": REFRESH_JOB,
            "installed": True,
            "enabled": str(row[0]) == "TRUE",
            "state": str(row[1]),
            "repeat_interval": str(row[2]),
            "last_start_date": str(row[3]) if row[3] else None,
            "next_run_date": str(row[4]) if row[4] else None,
            "run_count": int(row[5] or 0),
            "failure_count": int(row[6] or 0),
            "latest_run": (
                {
                    "status": str(latest_run[0]),
                    "actual_start_date": str(latest_run[1]) if latest_run[1] else None,
                    "run_duration": str(latest_run[2]) if latest_run[2] else None,
                    "additional_info": str(latest_run[3]) if latest_run[3] else None,
                }
                if latest_run
                else None
            ),
        }

    def refresh(self, *, trigger: str = "manual") -> dict[str, Any]:
        if self.settings.backend == "memory":
            with self._lock:
                self._nodes = {}
                for object_id, source in self._source_nodes.items():
                    semantic_text = (
                        f"{source['label']}. {source['description']}. Type {source['class_id']}. "
                        f"Status {source['status']}. Source {source['source_system']}"
                    )
                    self._nodes[object_id] = {
                        "node_id": object_id,
                        "class_id": source["class_id"],
                        "label": source["label"],
                        "semantic_text": semantic_text,
                        "status": source["status"],
                        "source_system": source["source_system"],
                        "attributes": source["attributes"],
                        "embedding": self.encoder.embed(semantic_text),
                        "refreshed_at": utcnow(),
                    }
                self._edges = {}
                for edge_id, source in self._source_edges.items():
                    term = self._terms.get(source["predicate_id"], {})
                    subject = self._nodes.get(source["subject_id"], {})
                    obj = self._nodes.get(source["object_id"], {})
                    valid = subject.get("class_id") == term.get("domain_class") and obj.get("class_id") == term.get("range_class")
                    self._edges[edge_id] = {
                        "edge_id": edge_id,
                        "subject_id": source["subject_id"],
                        "predicate_id": source["predicate_id"],
                        "object_id": source["object_id"],
                        "evidence_ref": source["evidence_ref"],
                        "validation_status": "valid" if valid else "review",
                    }
                record = {"run_id": uuid.uuid4().hex, "trigger_type": trigger, "started_at": utcnow(), "completed_at": utcnow(), "node_count": len(self._nodes), "edge_count": len(self._edges), "status": "succeeded", "detail": "memory projection refreshed"}
                self._refreshes.append(record)
                return json_safe(record)
        scheduler = self.scheduler_status()
        used_scheduler = trigger == "scheduler" and scheduler.get("installed")
        if used_scheduler:
            with self.pool.acquire() as connection:
                with connection.cursor() as cursor:
                    cursor.callproc("DBMS_SCHEDULER.RUN_JOB", keyword_parameters={"job_name": REFRESH_JOB, "use_current_session": True})
        else:
            self._call_refresh_procedure()
        enriched = self._backfill_embeddings()
        latest = self.refresh_history(limit=1)[0]
        return {**latest, "embedding_rows_enriched": enriched, "scheduler_invoked": used_scheduler, "fallback": None if used_scheduler else "direct stored procedure"}

    def terms(self) -> list[dict[str, Any]]:
        if self.settings.backend == "memory":
            return sorted(
                json_safe(list(self._terms.values())),
                key=lambda item: (item["term_kind"], item["term_id"]),
            )
        with self.pool.acquire() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    f"""SELECT term_id,term_kind,uri,label,definition,parent_term_id,domain_class,range_class
                        FROM {TERM_TABLE} WHERE tenant_id=:tenant ORDER BY term_kind,term_id""",
                    {"tenant": self.settings.tenant_id},
                )
                rows = cursor.fetchall()
        return [{"term_id": str(row[0]), "term_kind": str(row[1]), "uri": str(row[2]), "label": str(row[3]), "definition": str(row[4]), "parent_term_id": str(row[5]) if row[5] else None, "domain_class": str(row[6]) if row[6] else None, "range_class": str(row[7]) if row[7] else None} for row in rows]

    def _all_nodes(self) -> list[dict[str, Any]]:
        if self.settings.backend == "memory":
            return [json_safe({key: value for key, value in row.items() if key != "embedding"}) for row in self._nodes.values()]
        with self.pool.acquire() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    f"SELECT node_id,class_id,label,semantic_text,status,source_system,attributes,refreshed_at FROM {NODE_TABLE} WHERE tenant_id=:tenant ORDER BY node_id",
                    {"tenant": self.settings.tenant_id},
                )
                rows = cursor.fetchall()
        return [{"node_id": str(row[0]), "class_id": str(row[1]), "label": str(row[2]), "semantic_text": str(row[3]), "status": str(row[4]), "source_system": str(row[5]), "attributes": _json_from_db(row[6]), "refreshed_at": str(row[7])} for row in rows]

    def _all_edges(self) -> list[dict[str, Any]]:
        if self.settings.backend == "memory":
            return sorted(
                json_safe(list(self._edges.values())), key=lambda item: item["edge_id"]
            )
        with self.pool.acquire() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    f"SELECT edge_id,subject_id,predicate_id,object_id,evidence_ref,validation_status,refreshed_at FROM {EDGE_TABLE} WHERE tenant_id=:tenant ORDER BY edge_id",
                    {"tenant": self.settings.tenant_id},
                )
                rows = cursor.fetchall()
        return [{"edge_id": str(row[0]), "subject_id": str(row[1]), "predicate_id": str(row[2]), "object_id": str(row[3]), "evidence_ref": str(row[4]), "validation_status": str(row[5]), "refreshed_at": str(row[6])} for row in rows]

    def graph(self) -> dict[str, Any]:
        nodes = self._all_nodes()
        edges = self._all_edges()
        return {"nodes": nodes, "edges": edges, "node_count": len(nodes), "edge_count": len(edges), "all_edges_valid": all(item["validation_status"] == "valid" for item in edges)}

    def semantic_seeds(self, query: str, *, k: int = 4) -> list[dict[str, Any]]:
        limit = max(1, min(int(k), 12))
        query_vector = self.encoder.embed(query)
        if self.settings.backend == "memory":
            ranked = []
            for row in self._nodes.values():
                distance = 1.0 - self.encoder.cosine(query_vector, row["embedding"])
                ranked.append((distance, row))
            ranked.sort(key=lambda item: (item[0], item[1]["node_id"]))
            return [{"node_id": row["node_id"], "class_id": row["class_id"], "label": row["label"], "status": row["status"], "distance": round(float(distance), 6)} for distance, row in ranked[:limit]]
        fetch = "FETCH APPROX FIRST" if self.hnsw_active else "FETCH FIRST"
        with self.pool.acquire() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    f"""SELECT node_id,class_id,label,status,
                               VECTOR_DISTANCE(embedding,:query_vector,COSINE) distance
                        FROM {NODE_TABLE} WHERE tenant_id=:tenant AND embedding IS NOT NULL
                        ORDER BY distance {fetch} {limit} ROWS ONLY""",
                    {"tenant": self.settings.tenant_id, "query_vector": self._vector(query_vector)},
                )
                rows = cursor.fetchall()
        return [{"node_id": str(row[0]), "class_id": str(row[1]), "label": str(row[2]), "status": str(row[3]), "distance": round(float(row[4]), 6)} for row in rows]

    def retrieve(self, query: str, *, k: int = 4, max_hops: int = 4) -> dict[str, Any]:
        seeds = self.semantic_seeds(query, k=k)
        graph = self.graph()
        node_map = {item["node_id"]: item for item in graph["nodes"]}
        adjacency: dict[str, list[tuple[dict[str, Any], str, str]]] = defaultdict(list)
        for edge in graph["edges"]:
            adjacency[edge["subject_id"]].append((edge, edge["object_id"], "outbound"))
            adjacency[edge["object_id"]].append((edge, edge["subject_id"], "inbound"))
        paths: list[dict[str, Any]] = []
        seen_paths: set[str] = set()
        for seed in seeds:
            queue: deque[tuple[str, list[str], list[dict[str, Any]]]] = deque([(seed["node_id"], [seed["node_id"]], [])])
            while queue and len(paths) < 80:
                current, node_path, edge_path = queue.popleft()
                if len(edge_path) >= max_hops:
                    continue
                for edge, neighbor, direction in adjacency.get(current, []):
                    if neighbor in node_path:
                        continue
                    next_nodes = [*node_path, neighbor]
                    next_edges = [*edge_path, {**edge, "direction": direction}]
                    path_id = stable_hash({"seed": seed["node_id"], "nodes": next_nodes, "edges": [item["edge_id"] for item in next_edges]})[:16]
                    if path_id not in seen_paths:
                        seen_paths.add(path_id)
                        paths.append(
                            {
                                "path_id": path_id,
                                "seed_node_id": seed["node_id"],
                                "hop_count": len(next_edges),
                                "node_ids": next_nodes,
                                "nodes": [{"node_id": node_id, "class_id": node_map[node_id]["class_id"], "label": node_map[node_id]["label"], "status": node_map[node_id]["status"]} for node_id in next_nodes],
                                "predicates": [item["predicate_id"] for item in next_edges],
                                "edge_ids": [item["edge_id"] for item in next_edges],
                                "evidence_refs": [item["evidence_ref"] for item in next_edges],
                                "all_edges_valid": all(item["validation_status"] == "valid" for item in next_edges),
                            }
                        )
                    queue.append((neighbor, next_nodes, next_edges))
        affected_ids = {node_id for path in paths for node_id in path["node_ids"]}
        affected = [node_map[node_id] for node_id in sorted(affected_ids)]
        by_class: dict[str, list[str]] = defaultdict(list)
        for node in affected:
            by_class[node["class_id"]].append(node["node_id"])
        return {
            "query": query,
            "retrieval": "semantic vector seeds -> bounded stored-edge traversal",
            "seed_nodes": seeds,
            "max_hops": max_hops,
            "paths": paths,
            "affected_nodes": affected,
            "affected_by_class": dict(sorted(by_class.items())),
            "ontology_version": "supply-chain-impact-rdfs-v1",
        }

    def _deterministic_answer(self, retrieval: Mapping[str, Any]) -> str:
        classes = retrieval["affected_by_class"]
        lines = [
            "Northstar's expired certificate is not an isolated document problem.",
            "The governed graph connects the failed evidence and control to Northstar, "
            "the XR-12 component, the ThermaCore product, Leeds plant, order 8842, "
            "Alpine Outfitters, and contract 77.",
            "Production qualification should remain blocked until ACTION-REPLACE-CERT "
            "is completed and the named owner verifies replacement evidence.",
            "Iberia Materials is connected as an approved alternate source and should be "
            "evaluated against the contract and delivery window before substitution.",
            "The harness should load supply-chain-impact-analysis and bind only "
            "ontology_search and trace_business_impact.",
            "Affected identifiers by class: " + "; ".join(
                f"{name}={','.join(values)}" for name, values in classes.items()
            ),
        ]
        return "\n\n".join(lines)

    def answer(
        self,
        question: str | None = None,
        *,
        thread_id: str = "total-recall-main",
        skill_manifest: str = "",
        tool_contracts: Sequence[Mapping[str, Any]] = (),
        memory_context: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        question = str(question or self.default_question()).strip()
        retrieval = self.retrieve(question, k=4, max_hops=4)
        compact_paths = [
            {key: path[key] for key in ("path_id", "node_ids", "predicates", "evidence_refs", "all_edges_valid")}
            for path in retrieval["paths"]
            if path["hop_count"] <= 4
        ]
        sections = [
            {"id": "system", "title": "Harness contract", "kind": "system", "source": "host policy", "content": "Answer only from cited ontology nodes and stored relationship paths. Vector similarity selects seeds but never proves a relationship. Do not invent edges, approvals, or status."},
            {"id": "user", "title": "Operator question", "kind": "user", "source": "operator", "content": question},
            {"id": "memory", "title": "Durable memory context", "kind": "memory", "source": "Oracle Agent Memory", "content": memory_context or {"status": "no prior thread context"}},
            {"id": "skills", "title": "Retrieved Skill manifest", "kind": "procedural", "source": "semantic Skillbox", "content": skill_manifest or "(no Skill manifest supplied)"},
            {"id": "tools", "title": "Bound tool contracts", "kind": "tools", "source": "semantic Toolbox", "content": list(tool_contracts)},
            {"id": "seeds", "title": "Semantic seed entities", "kind": "retrieval", "source": NODE_TABLE, "content": retrieval["seed_nodes"]},
            {"id": "paths", "title": "Stored graph paths", "kind": "knowledge_graph", "source": EDGE_TABLE, "content": compact_paths},
        ]
        live_model = bool(self.settings.use_model_synthesis and self.settings.openai_api_key)
        provider = "OpenAI Responses API" if live_model else "deterministic ontology synthesizer"
        model = self.settings.openai_model if live_model else "none"
        self._last_context = context_window(
            sections,
            provider=provider,
            model=model,
            phase="ontology_grounded_answer",
            actual_model_call=live_model,
            max_tokens=12_000,
            note="Vector seed scores and graph paths are shown separately so relevance cannot masquerade as relationship proof.",
        )
        if live_model:
            from openai import OpenAI

            client = OpenAI(api_key=self.settings.openai_api_key)
            response = client.responses.create(
                model=self.settings.openai_model,
                input=[
                    {"role": "system", "content": [{"type": "input_text", "text": sections[0]["content"]}]},
                    {"role": "user", "content": [{"type": "input_text", "text": json.dumps({"question": question, "seeds": retrieval["seed_nodes"], "paths": compact_paths}, ensure_ascii=False)}]},
                ],
            )
            answer = str(response.output_text)
        else:
            answer = self._deterministic_answer(retrieval)
        citations = [f"KG:NODE:{item['node_id']}" for item in retrieval["seed_nodes"]]
        citations.extend(f"KG:PATH:{item['path_id']}" for item in retrieval["paths"][:12])
        verified = bool(retrieval["seed_nodes"] and retrieval["paths"] and all(item["all_edges_valid"] for item in retrieval["paths"]))
        query_id = uuid.uuid4().hex
        result = {
            "query_id": query_id,
            "thread_id": thread_id,
            "question": question,
            "answer": answer,
            "citations": citations,
            "verified": verified,
            "retrieval": retrieval,
            "context_window": self._last_context,
            "model": {"provider": provider, "model": model, "actual_call": live_model},
        }
        self._persist_query(result)
        return json_safe(result)

    def _persist_query(self, result: Mapping[str, Any]) -> None:
        row = {
            "query_id": result["query_id"],
            "thread_id": result["thread_id"],
            "question": result["question"],
            "seed_nodes": [item["node_id"] for item in result["retrieval"]["seed_nodes"]],
            "path_ids": [item["path_id"] for item in result["retrieval"]["paths"]],
            "answer": result["answer"],
            "citations": result["citations"],
            "verified": result["verified"],
            "model_provider": result["model"]["provider"],
            "created_at": utcnow(),
        }
        if self.settings.backend == "memory":
            self._queries.append(row)
            return
        with self.pool.acquire() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    f"""INSERT INTO {QUERY_TABLE}
                        (tenant_id,query_id,thread_id,question,seed_nodes,path_ids,answer,
                         citations,verified,model_provider)
                        VALUES (:tenant,:query_id,:thread_id,:question,:seed_nodes,:path_ids,
                                :answer,:citations,:verified,:model_provider)""",
                    {"tenant": self.settings.tenant_id, "query_id": row["query_id"], "thread_id": row["thread_id"], "question": row["question"], "seed_nodes": json.dumps(row["seed_nodes"]), "path_ids": json.dumps(row["path_ids"]), "answer": row["answer"], "citations": json.dumps(row["citations"]), "verified": "Y" if row["verified"] else "N", "model_provider": row["model_provider"]},
                )
            connection.commit()

    def context_snapshot(self) -> dict[str, Any]:
        return json_safe(self._last_context)

    def refresh_history(self, *, limit: int = 20) -> list[dict[str, Any]]:
        if self.settings.backend == "memory":
            return list(reversed(json_safe(self._refreshes[-limit:])))
        with self.pool.acquire() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    f"""SELECT run_id,trigger_type,started_at,completed_at,node_count,edge_count,status,detail
                        FROM {REFRESH_TABLE} WHERE tenant_id=:tenant
                        ORDER BY started_at DESC FETCH FIRST {max(1, min(limit, 100))} ROWS ONLY""",
                    {"tenant": self.settings.tenant_id},
                )
                rows = cursor.fetchall()
        return [{"run_id": str(row[0]), "trigger_type": str(row[1]), "started_at": str(row[2]), "completed_at": str(row[3]) if row[3] else None, "node_count": int(row[4]), "edge_count": int(row[5]), "status": str(row[6]), "detail": str(row[7]) if row[7] else ""} for row in rows]

    def query_history(self, *, limit: int = 20) -> list[dict[str, Any]]:
        if self.settings.backend == "memory":
            return list(reversed(json_safe(self._queries[-limit:])))
        with self.pool.acquire() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    f"""SELECT query_id,thread_id,question,seed_nodes,path_ids,citations,verified,
                               model_provider,created_at
                        FROM {QUERY_TABLE} WHERE tenant_id=:tenant
                        ORDER BY created_at DESC FETCH FIRST {max(1, min(limit, 100))} ROWS ONLY""",
                    {"tenant": self.settings.tenant_id},
                )
                rows = cursor.fetchall()
        return [{"query_id": str(row[0]), "thread_id": str(row[1]), "question": str(row[2]), "seed_nodes": _json_from_db(row[3]), "path_ids": _json_from_db(row[4]), "citations": _json_from_db(row[5]), "verified": str(row[6]) == "Y", "model_provider": str(row[7]), "created_at": str(row[8])} for row in rows]

    def native_rdf_status(self) -> dict[str, Any]:
        if self.settings.backend != "oracle":
            return {"sem_apis_available": False, "active_projection": "RDFS-compatible typed tables", "reason": "offline profile"}
        with self.pool.acquire() as connection:
            with connection.cursor() as cursor:
                cursor.execute("SELECT COUNT(*) FROM all_synonyms WHERE synonym_name='SEM_APIS'")
                available = bool(cursor.fetchone()[0])
        return {
            "sem_apis_available": available,
            "active_projection": "RDFS-compatible typed tables",
            "native_rdf_network_created": False,
            "reason": "Native RDF network creation is a separate DBA/licensing decision; the lab does not create system semantic structures implicitly.",
        }

    def status(self) -> dict[str, Any]:
        graph = self.graph()
        terms = self.terms()
        return {
            "ready": True,
            "ontology_version": "supply-chain-impact-rdfs-v1",
            "anatomy": {"classes": sum(item["term_kind"] == "class" for item in terms), "properties": sum(item["term_kind"] == "property" for item in terms), "instances": graph["node_count"], "relationships": graph["edge_count"]},
            "retrieval": "semantic vector seeds -> bounded stored-edge traversal",
            "embedding": {"provider": self.encoder.backend, "dimensions": self.dimensions, "index": "Oracle HNSW cosine" if self.hnsw_active else self.hnsw_fallback or "memory exact cosine"},
            "all_edges_valid": graph["all_edges_valid"],
            "scheduler": self.scheduler_status(),
            "native_rdf": self.native_rdf_status(),
            "latest_refresh": self.refresh_history(limit=1)[0] if self.refresh_history(limit=1) else None,
            "tables": [TERM_TABLE, SOURCE_NODE_TABLE, SOURCE_EDGE_TABLE, NODE_TABLE, EDGE_TABLE, REFRESH_TABLE, QUERY_TABLE],
        }

    def explorer_snapshot(self) -> dict[str, list[dict[str, Any]]]:
        if self.settings.backend != "memory":
            return {}
        return {
            "ontology_terms": self.terms(),
            "business_objects": list(self._source_nodes.values()),
            "business_links": list(self._source_edges.values()),
            "ontology_nodes": self._all_nodes(),
            "ontology_edges": self._all_edges(),
            "ontology_refresh_runs": self.refresh_history(limit=100),
            "ontology_query_runs": self.query_history(limit=100),
        }


__all__ = [
    "EDGE_TABLE",
    "NODE_TABLE",
    "OntologyStore",
    "QUERY_TABLE",
    "REFRESH_JOB",
    "REFRESH_PROCEDURE",
    "REFRESH_TABLE",
    "SOURCE_EDGE_TABLE",
    "SOURCE_NODE_TABLE",
    "TERM_TABLE",
]
