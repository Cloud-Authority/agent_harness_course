"""Semantic toolbox, SKILL.md skillbox, and successful-workflow catalog.

These are typed application tables rather than generic vector stores.  A tool
needs a JSON contract and a category; a skill needs its complete markdown,
content SHA, and provenance; a workflow recipe needs outcome counters.  The
Python callable remains in memory because executable objects cannot be stored in
Oracle safely or usefully.
"""

from __future__ import annotations

import hashlib
import json
import re
import threading
import uuid
from array import array
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, Sequence

from .config import AdvancedSettings, settings as default_settings
from .persistence import SemanticEncoder, json_safe, stable_hash, utcnow


TOOL_TABLE = "ADV_AGENT_TOOLS"
SKILL_TABLE = "ADV_AGENT_SKILLS"
WORKFLOW_TABLE = "ADV_WORKFLOW_RECIPES"

# name -> executable half of a tool.  Model-facing metadata is persisted in the
# toolbox; callables and portable sandbox programs deliberately are not.
TOOL_REGISTRY: dict[str, dict[str, Any]] = {}


def _json_value(value: Any) -> Any:
    if hasattr(value, "read"):
        value = value.read()
    if isinstance(value, (str, bytes, bytearray)):
        return json.loads(value)
    return json_safe(value)


def _text_value(value: Any) -> str | None:
    if value is None:
        return None
    if hasattr(value, "read"):
        value = value.read()
    return str(value)


def _parse_skill_md(skill_md: str) -> dict[str, Any]:
    """Parse the small, deliberately constrained SKILL.md frontmatter shape."""

    match = re.match(r"\A---\s*\n(.*?)\n---\s*\n", skill_md, re.DOTALL)
    if match is None:
        raise ValueError("SKILL.md must start with YAML-style frontmatter")
    values: dict[str, str] = {}
    for raw in match.group(1).splitlines():
        if ":" not in raw:
            continue
        key, value = raw.split(":", 1)
        values[key.strip()] = value.strip()
    missing = [key for key in ("name", "description", "tools") if not values.get(key)]
    if missing:
        raise ValueError("SKILL.md frontmatter is missing " + ", ".join(missing))
    raw_tools = values["tools"].strip()
    if not (raw_tools.startswith("[") and raw_tools.endswith("]")):
        raise ValueError("SKILL.md tools must use a bracketed list")
    tools = [item.strip().strip("'\"") for item in raw_tools[1:-1].split(",")]
    return {
        "name": values["name"],
        "description": values["description"],
        "tools": [item for item in tools if item],
    }


class HarnessCatalog:
    """One API over Oracle typed vector tables and an explicit memory test profile."""

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
        self.backend = "oracle-vector-catalog" if course_settings.backend == "oracle" else "memory-vector-test-profile"
        self._tools: dict[str, dict[str, Any]] = {}
        self._skills: dict[str, dict[str, Any]] = {}
        self._workflows: dict[str, dict[str, Any]] = {}
        self.hnsw_indexes: dict[str, dict[str, Any]] = {}
        self._lock = threading.RLock()
        if course_settings.backend == "oracle":
            if pool is None:
                raise RuntimeError("Oracle catalog requires the shared Oracle connection pool")
            self._setup_oracle()
        elif course_settings.backend != "memory":
            raise ValueError("ADVANCED_BACKEND must be oracle or memory")

    @property
    def dimensions(self) -> int:
        return int(self.settings.embedding_dimensions)

    @staticmethod
    def _error_code(exc: Exception) -> int | None:
        details = exc.args[0] if getattr(exc, "args", ()) else None
        return int(getattr(details, "code", 0) or 0) or None

    def _ddl(
        self, statement: str, *, allow_vector_memory_fallback: bool = False
    ) -> bool:
        with self.pool.acquire() as connection:
            with connection.cursor() as cursor:
                try:
                    cursor.execute(statement)
                except Exception as exc:
                    if self._error_code(exc) == 955:  # object already exists
                        return True
                    if allow_vector_memory_fallback and self._error_code(exc) == 51962:
                        return False
                    raise
        return True

    def _setup_oracle(self) -> None:
        dim = self.dimensions
        self._ddl(
            f"""CREATE TABLE {TOOL_TABLE} (
                tenant_id VARCHAR2(120) NOT NULL,
                name VARCHAR2(120) NOT NULL,
                description VARCHAR2(600) NOT NULL,
                category VARCHAR2(60) NOT NULL,
                tool_schema JSON NOT NULL,
                augmented_description CLOB NOT NULL,
                embedding VECTOR({dim}, FLOAT32) NOT NULL,
                created_at TIMESTAMP DEFAULT SYSTIMESTAMP NOT NULL,
                updated_at TIMESTAMP DEFAULT SYSTIMESTAMP NOT NULL,
                CONSTRAINT ADV_TOOLS_PK PRIMARY KEY (tenant_id, name))"""
        )
        tools_hnsw = self._ddl(
            f"""CREATE VECTOR INDEX ADV_TOOLS_HNSW ON {TOOL_TABLE} (embedding)
                ORGANIZATION INMEMORY NEIGHBOR GRAPH DISTANCE COSINE
                WITH TARGET ACCURACY 95""",
            allow_vector_memory_fallback=True,
        )
        self.hnsw_indexes[TOOL_TABLE] = {
            "active": tools_hnsw,
            "fallback": None if tools_hnsw else "exact cosine (ORA-51962: vector memory pool full)",
        }
        self._ddl(
            f"""CREATE TABLE {SKILL_TABLE} (
                tenant_id VARCHAR2(120) NOT NULL,
                name VARCHAR2(120) NOT NULL,
                description VARCHAR2(600) NOT NULL,
                sha VARCHAR2(64) NOT NULL,
                source_url VARCHAR2(600),
                skill_md CLOB NOT NULL,
                tools_used JSON NOT NULL,
                source_workflow_id VARCHAR2(64),
                embedding VECTOR({dim}, FLOAT32) NOT NULL,
                created_at TIMESTAMP DEFAULT SYSTIMESTAMP NOT NULL,
                updated_at TIMESTAMP DEFAULT SYSTIMESTAMP NOT NULL,
                CONSTRAINT ADV_SKILLS_PK PRIMARY KEY (tenant_id, name))"""
        )
        skills_hnsw = self._ddl(
            f"""CREATE VECTOR INDEX ADV_SKILLS_HNSW ON {SKILL_TABLE} (embedding)
                ORGANIZATION INMEMORY NEIGHBOR GRAPH DISTANCE COSINE
                WITH TARGET ACCURACY 95""",
            allow_vector_memory_fallback=True,
        )
        self.hnsw_indexes[SKILL_TABLE] = {
            "active": skills_hnsw,
            "fallback": None if skills_hnsw else "exact cosine (ORA-51962: vector memory pool full)",
        }
        self._ddl(
            f"""CREATE TABLE {WORKFLOW_TABLE} (
                tenant_id VARCHAR2(120) NOT NULL,
                recipe_id VARCHAR2(64) NOT NULL,
                fingerprint VARCHAR2(64) NOT NULL,
                intent VARCHAR2(1000) NOT NULL,
                steps_json JSON NOT NULL,
                tools_used JSON NOT NULL,
                occurrences NUMBER DEFAULT 0 NOT NULL,
                successes NUMBER DEFAULT 0 NOT NULL,
                failures NUMBER DEFAULT 0 NOT NULL,
                last_outcome VARCHAR2(40) NOT NULL,
                promoted CHAR(1) DEFAULT 'N' NOT NULL,
                promoted_skill_name VARCHAR2(120),
                embedding VECTOR({dim}, FLOAT32) NOT NULL,
                created_at TIMESTAMP DEFAULT SYSTIMESTAMP NOT NULL,
                last_seen TIMESTAMP DEFAULT SYSTIMESTAMP NOT NULL,
                CONSTRAINT ADV_RECIPES_PK PRIMARY KEY (tenant_id, recipe_id),
                CONSTRAINT ADV_RECIPES_UK UNIQUE (tenant_id, fingerprint))"""
        )
        recipes_hnsw = self._ddl(
            f"""CREATE VECTOR INDEX ADV_RECIPES_HNSW ON {WORKFLOW_TABLE} (embedding)
                ORGANIZATION INMEMORY NEIGHBOR GRAPH DISTANCE COSINE
                WITH TARGET ACCURACY 95""",
            allow_vector_memory_fallback=True,
        )
        self.hnsw_indexes[WORKFLOW_TABLE] = {
            "active": recipes_hnsw,
            "fallback": None if recipes_hnsw else "exact cosine (ORA-51962: vector memory pool full)",
        }

    @staticmethod
    def _vector(values: Sequence[float]) -> array:
        return array("f", (float(item) for item in values))

    @staticmethod
    def _schema(name: str, description: str, params_schema: Mapping[str, Any]) -> dict[str, Any]:
        return {
            "name": name,
            "description": description,
            "parameters": json_safe(dict(params_schema)),
        }

    def register_tool(
        self,
        name: str,
        fn: Callable[..., Any],
        description: str,
        params_schema: Mapping[str, Any],
        *,
        sandbox_program: str,
        synonyms: Iterable[str] = (),
        examples: Iterable[str] = (),
        when_to_use: str = "",
        when_not: str = "",
        category: str = "general",
    ) -> dict[str, Any]:
        schema = self._schema(name, description, params_schema)
        enriched = (
            f"TOOL {name}: {description}\ncategory: {category}\n"
            f"synonyms: {', '.join(synonyms)}\nuse when: {when_to_use}\n"
            f"do not use when: {when_not}\nexamples: {' | '.join(examples)}"
        )
        embedding = self.encoder.embed(enriched)
        executable = {
            "fn": fn,
            "schema": schema,
            "sandbox_program": sandbox_program,
        }
        TOOL_REGISTRY[name] = executable
        row = {
            "name": name,
            "description": description,
            "category": category,
            "tool_schema": schema,
            "augmented_description": enriched,
            "embedding": embedding,
            "created_at": utcnow(),
            "updated_at": utcnow(),
        }
        if self.settings.backend == "memory":
            with self._lock:
                self._tools[name] = row
            return json_safe({key: value for key, value in row.items() if key != "embedding"})

        statement = f"""MERGE INTO {TOOL_TABLE} d
            USING (SELECT :tenant_id tenant_id, :name name FROM dual) s
            ON (d.tenant_id=s.tenant_id AND d.name=s.name)
            WHEN MATCHED THEN UPDATE SET description=:description, category=:category,
                tool_schema=:tool_schema, augmented_description=:augmented,
                embedding=:embedding, updated_at=SYSTIMESTAMP
            WHEN NOT MATCHED THEN INSERT
                (tenant_id,name,description,category,tool_schema,augmented_description,embedding)
                VALUES (:tenant_id,:name,:description,:category,:tool_schema,:augmented,:embedding)"""
        with self.pool.acquire() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    statement,
                    {
                        "tenant_id": self.settings.tenant_id,
                        "name": name,
                        "description": description,
                        "category": category,
                        "tool_schema": json.dumps(schema, sort_keys=True),
                        "augmented": enriched,
                        "embedding": self._vector(embedding),
                    },
                )
            connection.commit()
        return json_safe({key: value for key, value in row.items() if key != "embedding"})

    def resolve_tool(self, name: str) -> dict[str, Any]:
        try:
            return TOOL_REGISTRY[name]
        except KeyError as exc:
            raise KeyError(f"No callable registered for tool {name!r}") from exc

    def retrieve_tools(self, query: str, k: int = 6) -> list[dict[str, Any]]:
        limit = max(1, min(int(k), 50))
        vector = self.encoder.embed(query)
        if self.settings.backend == "memory":
            with self._lock:
                rows = list(self._tools.values())
            ranked = []
            for row in rows:
                distance = 1.0 - self.encoder.cosine(vector, row["embedding"])
                ranked.append((distance, row))
            ranked.sort(key=lambda item: (item[0], item[1]["name"]))
            return [
                {
                    "name": row["name"],
                    "description": row["description"],
                    "category": row["category"],
                    "tool_schema": json_safe(row["tool_schema"]),
                    "distance": round(float(distance), 6),
                }
                for distance, row in ranked[:limit]
            ]

        fetch_mode = "FETCH APPROX FIRST" if self.hnsw_indexes[TOOL_TABLE]["active"] else "FETCH FIRST"
        query_sql = f"""SELECT name, description, category, tool_schema,
                VECTOR_DISTANCE(embedding, :query_vector, COSINE) distance
            FROM {TOOL_TABLE}
            WHERE tenant_id=:tenant_id
            ORDER BY distance
            {fetch_mode} {limit} ROWS ONLY"""
        with self.pool.acquire() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    query_sql,
                    {"tenant_id": self.settings.tenant_id, "query_vector": self._vector(vector)},
                )
                values = cursor.fetchall()
        return [
            {
                "name": str(row[0]),
                "description": str(row[1]),
                "category": str(row[2]),
                "tool_schema": _json_value(row[3]),
                "distance": round(float(row[4]), 6),
            }
            for row in values
        ]

    def save_skill(
        self,
        name: str,
        description: str,
        skill_md: str,
        tools_used: Iterable[str],
        *,
        source_workflow_id: str | None = None,
        source_url: str | None = None,
    ) -> str:
        parsed = _parse_skill_md(skill_md)
        tools = [str(item) for item in tools_used]
        if parsed["name"] != name:
            raise ValueError("SKILL.md frontmatter name does not match the catalog key")
        if parsed["description"] != description:
            raise ValueError("SKILL.md frontmatter description does not match the catalog description")
        if parsed["tools"] != tools:
            raise ValueError("SKILL.md frontmatter tools do not match tools_used")
        sha = hashlib.sha256(skill_md.encode("utf-8")).hexdigest()
        embedding_text = (
            f"SKILL {name}: {description}\n"
            f"tools: {', '.join(tools)}\n{skill_md}"
        )
        embedding = self.encoder.embed(embedding_text)
        row = {
            "name": name,
            "description": description,
            "sha": sha,
            "source_url": source_url,
            "skill_md": skill_md,
            "tools_used": tools,
            "source_workflow_id": source_workflow_id,
            "embedding": embedding,
            "created_at": utcnow(),
            "updated_at": utcnow(),
        }
        if self.settings.backend == "memory":
            with self._lock:
                previous = self._skills.get(name)
                if previous:
                    row["created_at"] = previous["created_at"]
                self._skills[name] = row
            return sha

        statement = f"""MERGE INTO {SKILL_TABLE} d
            USING (SELECT :tenant_id tenant_id, :name name FROM dual) s
            ON (d.tenant_id=s.tenant_id AND d.name=s.name)
            WHEN MATCHED THEN UPDATE SET description=:description, sha=:sha,
                source_url=:source_url, skill_md=:skill_md, tools_used=:tools_used,
                source_workflow_id=:source_workflow_id, embedding=:embedding,
                updated_at=SYSTIMESTAMP
            WHEN NOT MATCHED THEN INSERT
                (tenant_id,name,description,sha,source_url,skill_md,tools_used,
                 source_workflow_id,embedding)
                VALUES (:tenant_id,:name,:description,:sha,:source_url,:skill_md,
                        :tools_used,:source_workflow_id,:embedding)"""
        with self.pool.acquire() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    statement,
                    {
                        "tenant_id": self.settings.tenant_id,
                        "name": name,
                        "description": description,
                        "sha": sha,
                        "source_url": source_url,
                        "skill_md": skill_md,
                        "tools_used": json.dumps(tools),
                        "source_workflow_id": source_workflow_id,
                        "embedding": self._vector(embedding),
                    },
                )
            connection.commit()
        return sha

    def seed_skill_files(self, root: Path) -> list[dict[str, Any]]:
        seeded = []
        source_prefix = f"repo:{root.as_posix().rstrip('/')}/"
        for path in sorted(root.glob("*/SKILL.md")):
            body = path.read_text(encoding="utf-8")
            metadata = _parse_skill_md(body)
            sha = self.save_skill(
                metadata["name"],
                metadata["description"],
                body,
                metadata["tools"],
                source_url=f"repo:{path.as_posix()}",
            )
            seeded.append({**metadata, "sha": sha, "path": str(path)})
        if not seeded:
            raise RuntimeError(f"No SKILL.md files found below {root}")
        canonical_names = {item["name"] for item in seeded}
        # Reconcile only repository-seeded skill rows. Generated/promoted skills
        # have a different source URL and remain untouched.
        if self.settings.backend == "memory":
            with self._lock:
                stale = [
                    name
                    for name, row in self._skills.items()
                    if str(row.get("source_url") or "").startswith(source_prefix)
                    and name not in canonical_names
                ]
                for name in stale:
                    del self._skills[name]
        else:
            with self.pool.acquire() as connection:
                with connection.cursor() as cursor:
                    cursor.execute(
                        f"""SELECT name FROM {SKILL_TABLE}
                            WHERE tenant_id=:tenant_id AND source_url LIKE :source_prefix""",
                        {
                            "tenant_id": self.settings.tenant_id,
                            "source_prefix": source_prefix + "%",
                        },
                    )
                    stale = [str(row[0]) for row in cursor.fetchall() if str(row[0]) not in canonical_names]
                    for name in stale:
                        cursor.execute(
                            f"DELETE FROM {SKILL_TABLE} WHERE tenant_id=:tenant_id AND name=:name",
                            {"tenant_id": self.settings.tenant_id, "name": name},
                        )
                connection.commit()
        return seeded

    def retrieve_skills(self, query: str, k: int = 5) -> list[dict[str, Any]]:
        """Level 1 retrieval: return a small manifest, never the full skill body."""

        limit = max(1, min(int(k), 50))
        vector = self.encoder.embed(query)
        if self.settings.backend == "memory":
            with self._lock:
                rows = list(self._skills.values())
            ranked = []
            for row in rows:
                distance = 1.0 - self.encoder.cosine(vector, row["embedding"])
                ranked.append((distance, row))
            ranked.sort(key=lambda item: (item[0], item[1]["name"]))
            return [
                {
                    "name": row["name"],
                    "description": row["description"],
                    "sha": row["sha"],
                    "distance": round(float(distance), 6),
                }
                for distance, row in ranked[:limit]
            ]

        fetch_mode = "FETCH APPROX FIRST" if self.hnsw_indexes[SKILL_TABLE]["active"] else "FETCH FIRST"
        query_sql = f"""SELECT name, description, sha,
                VECTOR_DISTANCE(embedding, :query_vector, COSINE) distance
            FROM {SKILL_TABLE}
            WHERE tenant_id=:tenant_id
            ORDER BY distance
            {fetch_mode} {limit} ROWS ONLY"""
        with self.pool.acquire() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    query_sql,
                    {"tenant_id": self.settings.tenant_id, "query_vector": self._vector(vector)},
                )
                values = cursor.fetchall()
        return [
            {
                "name": str(row[0]),
                "description": str(row[1]),
                "sha": str(row[2]),
                "distance": round(float(row[3]), 6),
            }
            for row in values
        ]

    def build_skill_manifest(self, query: str, k: int = 5) -> str:
        rows = self.retrieve_skills(query, k=k)
        return "\n".join(
            f"- {row['name']}: {row['description']} [sha:{row['sha'][:12]}]"
            for row in rows
        ) or "(no skills found)"

    def load_skill(self, name: str) -> dict[str, Any]:
        """Level 2 retrieval: load one committed full SKILL.md body by exact name."""

        if self.settings.backend == "memory":
            with self._lock:
                row = self._skills.get(name)
            if row is None:
                return {"error": "no such skill"}
            return json_safe({key: value for key, value in row.items() if key != "embedding"})

        query_sql = f"""SELECT name, description, sha, source_url, skill_md,
                tools_used, source_workflow_id, created_at, updated_at
            FROM {SKILL_TABLE}
            WHERE tenant_id=:tenant_id AND name=:name"""
        with self.pool.acquire() as connection:
            with connection.cursor() as cursor:
                cursor.execute(query_sql, {"tenant_id": self.settings.tenant_id, "name": name})
                row = cursor.fetchone()
        if row is None:
            return {"error": "no such skill"}
        return {
            "name": str(row[0]),
            "description": str(row[1]),
            "sha": str(row[2]),
            "source_url": _text_value(row[3]),
            "skill_md": _text_value(row[4]) or "",
            "tools_used": _json_value(row[5]),
            "source_workflow_id": _text_value(row[6]),
            "created_at": str(row[7]),
            "updated_at": str(row[8]),
        }

    def capture_workflow(
        self,
        *,
        intent: str,
        steps: Sequence[Mapping[str, Any]],
        tools_used: Sequence[str],
        success: bool,
    ) -> dict[str, Any]:
        canonical_steps = json_safe(list(steps))
        canonical_tools = [str(item) for item in tools_used]
        fingerprint = stable_hash(
            {"intent": intent, "steps": canonical_steps, "tools_used": canonical_tools}
        )
        embedding_text = (
            f"WORKFLOW: {intent}\nsteps: {json.dumps(canonical_steps, sort_keys=True)}\n"
            f"tools: {', '.join(canonical_tools)}"
        )
        embedding = self.encoder.embed(embedding_text)
        outcome = "success" if success else "failure"
        if self.settings.backend == "memory":
            with self._lock:
                existing = next(
                    (row for row in self._workflows.values() if row["fingerprint"] == fingerprint),
                    None,
                )
                if existing is None:
                    recipe_id = uuid.uuid4().hex
                    existing = {
                        "recipe_id": recipe_id,
                        "fingerprint": fingerprint,
                        "intent": intent,
                        "steps": canonical_steps,
                        "tools_used": canonical_tools,
                        "occurrences": 0,
                        "successes": 0,
                        "failures": 0,
                        "promoted": False,
                        "promoted_skill_name": None,
                        "embedding": embedding,
                        "created_at": utcnow(),
                    }
                    self._workflows[recipe_id] = existing
                existing["occurrences"] += 1
                existing["successes" if success else "failures"] += 1
                existing["last_outcome"] = outcome
                existing["last_seen"] = utcnow()
                return json_safe({key: value for key, value in existing.items() if key != "embedding"})

        recipe_id = uuid.uuid4().hex
        statement = f"""MERGE INTO {WORKFLOW_TABLE} d
            USING (SELECT :tenant_id tenant_id, :fingerprint fingerprint FROM dual) s
            ON (d.tenant_id=s.tenant_id AND d.fingerprint=s.fingerprint)
            WHEN MATCHED THEN UPDATE SET
                occurrences=d.occurrences+1,
                successes=d.successes+:success_increment,
                failures=d.failures+:failure_increment,
                last_outcome=:last_outcome, last_seen=SYSTIMESTAMP
            WHEN NOT MATCHED THEN INSERT
                (tenant_id,recipe_id,fingerprint,intent,steps_json,tools_used,
                 occurrences,successes,failures,last_outcome,promoted,embedding)
                VALUES (:tenant_id,:recipe_id,:fingerprint,:intent,:steps_json,
                        :tools_used,1,:success_increment,:failure_increment,
                        :last_outcome,'N',:embedding)"""
        with self.pool.acquire() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    statement,
                    {
                        "tenant_id": self.settings.tenant_id,
                        "recipe_id": recipe_id,
                        "fingerprint": fingerprint,
                        "intent": intent,
                        "steps_json": json.dumps(canonical_steps, sort_keys=True),
                        "tools_used": json.dumps(canonical_tools),
                        "success_increment": 1 if success else 0,
                        "failure_increment": 0 if success else 1,
                        "last_outcome": outcome,
                        "embedding": self._vector(embedding),
                    },
                )
            connection.commit()
        return self.get_workflow_by_fingerprint(fingerprint)

    def _workflow_from_row(self, row: Sequence[Any]) -> dict[str, Any]:
        return {
            "recipe_id": str(row[0]),
            "fingerprint": str(row[1]),
            "intent": str(row[2]),
            "steps": _json_value(row[3]),
            "tools_used": _json_value(row[4]),
            "occurrences": int(row[5]),
            "successes": int(row[6]),
            "failures": int(row[7]),
            "last_outcome": str(row[8]),
            "promoted": str(row[9]) == "Y",
            "promoted_skill_name": _text_value(row[10]),
            "created_at": str(row[11]),
            "last_seen": str(row[12]),
        }

    def get_workflow(self, recipe_id: str) -> dict[str, Any]:
        if self.settings.backend == "memory":
            with self._lock:
                row = self._workflows.get(recipe_id)
            return (
                json_safe({key: value for key, value in row.items() if key != "embedding"})
                if row
                else {"error": "no such workflow"}
            )
        query_sql = f"""SELECT recipe_id,fingerprint,intent,steps_json,tools_used,
                occurrences,successes,failures,last_outcome,promoted,promoted_skill_name,
                created_at,last_seen
            FROM {WORKFLOW_TABLE}
            WHERE tenant_id=:tenant_id AND recipe_id=:recipe_id"""
        with self.pool.acquire() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    query_sql,
                    {"tenant_id": self.settings.tenant_id, "recipe_id": recipe_id},
                )
                row = cursor.fetchone()
        return self._workflow_from_row(row) if row else {"error": "no such workflow"}

    def get_workflow_by_fingerprint(self, fingerprint: str) -> dict[str, Any]:
        if self.settings.backend == "memory":
            with self._lock:
                row = next(
                    (item for item in self._workflows.values() if item["fingerprint"] == fingerprint),
                    None,
                )
            return (
                json_safe({key: value for key, value in row.items() if key != "embedding"})
                if row
                else {"error": "no such workflow"}
            )
        query_sql = f"""SELECT recipe_id,fingerprint,intent,steps_json,tools_used,
                occurrences,successes,failures,last_outcome,promoted,promoted_skill_name,
                created_at,last_seen
            FROM {WORKFLOW_TABLE}
            WHERE tenant_id=:tenant_id AND fingerprint=:fingerprint"""
        with self.pool.acquire() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    query_sql,
                    {"tenant_id": self.settings.tenant_id, "fingerprint": fingerprint},
                )
                row = cursor.fetchone()
        return self._workflow_from_row(row) if row else {"error": "no such workflow"}

    def mark_promoted(self, recipe_id: str, skill_name: str) -> dict[str, Any]:
        if self.settings.backend == "memory":
            with self._lock:
                row = self._workflows.get(recipe_id)
                if row is None:
                    return {"error": "no such workflow"}
                row["promoted"] = True
                row["promoted_skill_name"] = skill_name
            return self.get_workflow(recipe_id)
        with self.pool.acquire() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    f"""UPDATE {WORKFLOW_TABLE}
                        SET promoted='Y', promoted_skill_name=:skill_name
                        WHERE tenant_id=:tenant_id AND recipe_id=:recipe_id""",
                    {
                        "tenant_id": self.settings.tenant_id,
                        "recipe_id": recipe_id,
                        "skill_name": skill_name,
                    },
                )
            connection.commit()
        return self.get_workflow(recipe_id)

    def recall_workflows(
        self, query: str, k: int = 3, *, include_promoted: bool = False
    ) -> list[dict[str, Any]]:
        limit = max(1, min(int(k), 50))
        vector = self.encoder.embed(query)
        if self.settings.backend == "memory":
            with self._lock:
                rows = list(self._workflows.values())
            ranked = []
            for row in rows:
                if row["promoted"] and not include_promoted:
                    continue
                distance = 1.0 - self.encoder.cosine(vector, row["embedding"])
                ranked.append((distance, row))
            ranked.sort(key=lambda item: (item[0], -item[1]["successes"]))
            return [
                {
                    **json_safe({key: value for key, value in row.items() if key != "embedding"}),
                    "distance": round(float(distance), 6),
                }
                for distance, row in ranked[:limit]
            ]
        promoted_filter = "" if include_promoted else "AND promoted='N'"
        fetch_mode = (
            "FETCH APPROX FIRST"
            if self.hnsw_indexes[WORKFLOW_TABLE]["active"]
            else "FETCH FIRST"
        )
        query_sql = f"""SELECT recipe_id,fingerprint,intent,steps_json,tools_used,
                occurrences,successes,failures,last_outcome,promoted,promoted_skill_name,
                created_at,last_seen,
                VECTOR_DISTANCE(embedding, :query_vector, COSINE) distance
            FROM {WORKFLOW_TABLE}
            WHERE tenant_id=:tenant_id {promoted_filter}
            ORDER BY distance
            {fetch_mode} {limit} ROWS ONLY"""
        with self.pool.acquire() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    query_sql,
                    {"tenant_id": self.settings.tenant_id, "query_vector": self._vector(vector)},
                )
                values = cursor.fetchall()
        return [
            {**self._workflow_from_row(row[:13]), "distance": round(float(row[13]), 6)}
            for row in values
        ]

    def status(self) -> dict[str, Any]:
        if self.settings.backend == "memory":
            counts = {
                "tools": len(self._tools),
                "skills": len(self._skills),
                "workflow_recipes": len(self._workflows),
            }
        else:
            counts = {}
            with self.pool.acquire() as connection:
                with connection.cursor() as cursor:
                    for key, table in (
                        ("tools", TOOL_TABLE),
                        ("skills", SKILL_TABLE),
                        ("workflow_recipes", WORKFLOW_TABLE),
                    ):
                        cursor.execute(
                            f"SELECT COUNT(*) FROM {table} WHERE tenant_id=:tenant_id",
                            {"tenant_id": self.settings.tenant_id},
                        )
                        counts[key] = int(cursor.fetchone()[0])
        return {
            "backend": self.backend,
            "retrieval": "semantic vector search",
            "index": (
                "Oracle HNSW cosine"
                if self.settings.backend == "oracle" and all(
                    item["active"] for item in self.hnsw_indexes.values()
                )
                else "Oracle exact cosine fallback"
                if self.settings.backend == "oracle"
                else "in-memory cosine test profile"
            ),
            "hnsw_indexes": json_safe(self.hnsw_indexes),
            "embedding_provider": (
                "OpenAI"
                if self.settings.semantic_backend == "openai"
                else "Oracle AI Database"
                if self.settings.semantic_backend == "oracle"
                else "deterministic feature hash (labelled fallback)"
            ),
            "embedding_model": (
                self.settings.openai_embed_model
                if self.settings.semantic_backend == "openai"
                else self.settings.oracle_embed_model
                if self.settings.semantic_backend == "oracle"
                else "feature-hash"
            ),
            "native_dimensions": (
                self.settings.oracle_embed_native_dimensions
                if self.settings.semantic_backend == "oracle"
                else self.dimensions
            ),
            "dimensions": self.dimensions,
            "typed_tables": [TOOL_TABLE, SKILL_TABLE, WORKFLOW_TABLE],
            "counts": counts,
        }


__all__ = [
    "HarnessCatalog",
    "SKILL_TABLE",
    "TOOL_REGISTRY",
    "TOOL_TABLE",
    "WORKFLOW_TABLE",
]
