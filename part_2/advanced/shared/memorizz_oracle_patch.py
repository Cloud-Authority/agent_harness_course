"""One patch for MemoRizz's Oracle provider on the Free 'lite' image.

``OracleProvider`` checks that existing VECTOR columns match the embedder by
reading each table's DDL through ``DBMS_METADATA``, which needs XDB. The lite
image ships without XDB, so the check fails with ORA-00600. The data
dictionary already knows the answer: ``USER_TAB_COLS.VECTOR_INFO`` holds the
declared type of every VECTOR column, so the dimension can be read from there.
"""
from __future__ import annotations

import re
from typing import Dict


def vector_dimensions_from_dictionary(self) -> Dict[str, int]:
    owner = str(self.config.schema or self.config.user).strip().upper()
    dimensions: Dict[str, int] = {}
    with self._get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT table_name, column_name, vector_info FROM all_tab_cols "
                       "WHERE owner = :owner AND data_type = 'VECTOR' AND column_name = 'EMBEDDING'", {"owner": owner})
        for table_name, column_name, info in cursor.fetchall():
            found = re.search(r"VECTOR\((\d+)", str(info or ""))
            if found:
                dimensions[f"{table_name}.{column_name}"] = int(found.group(1))
        cursor.close()
    return dimensions


def patch_oracle_provider() -> None:
    from memorizz.memory_provider.oracle import provider
    provider.OracleProvider.get_vector_schema_dimensions = vector_dimensions_from_dictionary
