#!/usr/bin/env python3
"""Secret-safe OracleSaver, OracleStore, and vector-search preflight."""

from __future__ import annotations

import json
import sys
import uuid
from pathlib import Path


COURSE_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(COURSE_ROOT))

from part_1.advanced.shared.config import settings
from part_1.advanced.shared.persistence import (
    ScopedMemory,
    SemanticEncoder,
    create_persistence,
)


def main() -> None:
    if settings.backend != "oracle":
        raise RuntimeError("Set ADVANCED_BACKEND=oracle for this preflight")
    resources = create_persistence(settings)
    tenant = f"oracle-preflight-{uuid.uuid4().hex[:10]}"
    try:
        memory = ScopedMemory(resources.store, tenant_id=tenant)
        memory.put(
            "preflight",
            "semantic",
            {
                "text": (
                    "Durable checkpoints, idempotent operations, and exact host "
                    "approvals protect long-running agent workflows."
                )
            },
            key="durable-approval",
        )
        hits = memory.semantic_search(
            "preflight",
            "semantic",
            "checkpoint recovery and approval",
            encoder=SemanticEncoder(settings),
            limit=3,
            threshold=0.0,
        )
        if not hits or hits[0]["id"] != "durable-approval":
            raise RuntimeError("Oracle vector search did not return the seeded record")
        print(
            json.dumps(
                {
                    "ok": True,
                    "backend": resources.backend,
                    "oracle_version": resources.oracle_version,
                    "checkpointer": type(resources.checkpointer).__name__,
                    "store": type(resources.store).__name__,
                    "vector_table_suffix": resources.store.table_suffix,
                    "semantic_backend": settings.semantic_backend,
                    "top_hit": hits[0]["id"],
                    "similarity": hits[0]["similarity"],
                    "credentials_in_output": False,
                },
                indent=2,
            )
        )
    finally:
        resources.close()


if __name__ == "__main__":
    main()
