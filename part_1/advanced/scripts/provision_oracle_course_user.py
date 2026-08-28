#!/usr/bin/env python3
"""Provision the local Oracle course user without exposing its password.

The password is read from the ignored course ``.env`` through ``settings`` and is
sent to SQL*Plus over stdin. It is never included in the process arguments or in
this script's output.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path


COURSE_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(COURSE_ROOT))

from part_1.advanced.shared.config import settings


ORACLE_IDENTIFIER = re.compile(r"[A-Z][A-Z0-9_$#]{0,127}")
CONTAINER_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}")


def _identifier(value: str, *, label: str) -> str:
    normalized = value.strip().upper()
    if not ORACLE_IDENTIFIER.fullmatch(normalized):
        raise ValueError(f"Invalid {label}")
    return normalized


def _container_name(value: str) -> str:
    if not CONTAINER_NAME.fullmatch(value):
        raise ValueError("Invalid Docker container name")
    return value


def _password_for_ddl(value: str) -> str:
    if not value:
        raise RuntimeError("ORA_AGENT_PWD/ADVANCED_ORA_PASSWORD is not configured")
    if any(character in value for character in ('"', "\n", "\r", "\x00")):
        raise RuntimeError(
            "The configured password contains a character that this safe "
            "provisioner intentionally refuses to place in Oracle DDL"
        )
    # The DDL is itself held in a PL/SQL string literal. Double single quotes so
    # passwords containing an apostrophe remain data rather than PL/SQL syntax.
    return value.replace("'", "''")


def _oracle_codes(output: str) -> list[str]:
    return sorted(set(re.findall(r"(?:ORA|SP2)-\d{4,5}", output)))


def provision(
    *, docker_container: str, pdb: str, tablespace: str, enable_scheduler: bool = False
) -> dict[str, object]:
    user = _identifier(settings.ora_user, label="Oracle course user")
    pdb_name = _identifier(pdb, label="pluggable database")
    tablespace_name = _identifier(tablespace, label="course tablespace")
    container = _container_name(docker_container)
    password = _password_for_ddl(settings.ora_password)

    user_ddl = (
        f'CREATE USER "{user}" IDENTIFIED BY "{password}" '
        f'DEFAULT TABLESPACE "{tablespace_name}" TEMPORARY TABLESPACE TEMP '
        f'QUOTA UNLIMITED ON "{tablespace_name}"'
    )
    alter_ddl = f'ALTER USER "{user}" IDENTIFIED BY "{password}" ACCOUNT UNLOCK'
    scheduler_privilege = ", create job" if enable_scheduler else ""
    sql = f"""
whenever sqlerror exit sql.sqlcode rollback
set echo off feedback off heading off verify off termout off define off
alter session set container = {pdb_name};
declare
  account_count number;
begin
  select count(*) into account_count
  from dba_users
  where username = '{user}';
  if account_count = 0 then
    execute immediate '{user_ddl}';
  else
    execute immediate '{alter_ddl}';
  end if;
end;
/
grant create session, create table, create view, create procedure,
      create sequence, create trigger{scheduler_privilege} to "{user}";
alter user "{user}" quota unlimited on "{tablespace_name}";
exit success
"""

    completed = subprocess.run(
        [
            "docker",
            "exec",
            "-i",
            container,
            "bash",
            "-lc",
            'sqlplus -s "/ as sysdba"',
        ],
        input=sql,
        text=True,
        capture_output=True,
        check=False,
    )
    if completed.returncode != 0:
        codes = _oracle_codes(completed.stdout + completed.stderr)
        suffix = f" ({', '.join(codes)})" if codes else ""
        raise RuntimeError(
            f"Oracle course-user provisioning failed with exit code "
            f"{completed.returncode}{suffix}"
        )

    import oracledb

    with oracledb.connect(**settings.oracle_connect_kwargs()) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                "select sys_context('USERENV', 'CON_NAME'), "
                "sys_context('USERENV', 'SESSION_USER') from dual"
            )
            connected_pdb, connected_user = cursor.fetchone()

    return {
        "ok": True,
        "operation": "course account provisioned and verified",
        "container": container,
        "pdb": str(connected_pdb),
        "user": str(connected_user),
        "tablespace": tablespace_name,
        "dsn": settings.ora_dsn,
        "password_exposed": False,
        "scheduler_privilege_enabled": enable_scheduler,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--container",
        default="erpa-custom-oracle-26ai",
        help="local Oracle Docker container name",
    )
    parser.add_argument(
        "--pdb", default="FREEPDB1", help="target pluggable database"
    )
    parser.add_argument(
        "--tablespace",
        default="ERPA_DATA",
        help="permanent tablespace used by the local course image",
    )
    parser.add_argument(
        "--enable-scheduler",
        action="store_true",
        help="also grant CREATE JOB in this schema so its ontology refresh job can run",
    )
    args = parser.parse_args()
    try:
        result = provision(
            docker_container=args.container,
            pdb=args.pdb,
            tablespace=args.tablespace,
            enable_scheduler=args.enable_scheduler,
        )
    except Exception as exc:
        print(json.dumps({"ok": False, "error": str(exc), "password_exposed": False}))
        raise SystemExit(1) from None
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
