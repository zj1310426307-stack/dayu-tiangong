"""Run HYDRO-DATA-01 migration upgrade/downgrade in a disposable database."""

from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path
from uuid import uuid4

import psycopg
from psycopg import sql


ROOT = Path(__file__).resolve().parents[1]
DATABASE_NAME = f"dayu_hydro_verify_{uuid4().hex[:12]}"


def _connection(database: str, *, autocommit: bool = False):
    """Connect with local development settings without logging credentials."""

    return psycopg.connect(
        host=os.getenv("POSTGRES_HOST", "localhost"),
        port=int(os.getenv("POSTGRES_PORT", "5432")),
        dbname=database,
        user=os.getenv("POSTGRES_USER", "dayu"),
        password=os.getenv("POSTGRES_PASSWORD", "dayu_dev"),
        autocommit=autocommit,
    )


def _alembic(target: str) -> None:
    """Run one migration target against the disposable database."""

    environment = os.environ.copy()
    environment["POSTGRES_DB"] = DATABASE_NAME
    subprocess.run(
        [sys.executable, "-m", "alembic", "-c", "database/alembic.ini", *target.split()],
        cwd=ROOT, env=environment, check=True,
    )


def main() -> None:
    """Verify schema head, downgrade boundary, and repeatability, then always clean up."""

    if not re.fullmatch(r"dayu_hydro_verify_[0-9a-f]{12}", DATABASE_NAME):
        raise RuntimeError("refusing unsafe disposable database name")
    with _connection("postgres", autocommit=True) as admin:
        admin.execute(sql.SQL("CREATE DATABASE {} TEMPLATE template0").format(sql.Identifier(DATABASE_NAME)))
    try:
        _alembic("upgrade head")
        with _connection(DATABASE_NAME) as connection:
            version = connection.execute("SELECT version_num FROM alembic_version").fetchone()[0]
            table_count = connection.execute(
                "SELECT count(*) FROM information_schema.tables WHERE table_schema='hydraulic'"
            ).fetchone()[0]
            profile_count = connection.execute(
                "SELECT count(*) FROM hydraulic.cross_section_profile"
            ).fetchone()[0]
            if version != "20260818_0019" or table_count < 12:
                raise RuntimeError(f"unexpected migration result: {version=} {table_count=}")
            print(f"upgrade verified: version={version}, hydraulic_tables={table_count}, profiles={profile_count}")
        _alembic("downgrade 20260817_0018")
        with _connection(DATABASE_NAME) as connection:
            exists = connection.execute("SELECT to_regnamespace('hydraulic')").fetchone()[0]
            if exists is not None:
                raise RuntimeError("hydraulic schema remained after downgrade")
            print("downgrade verified: hydraulic schema removed")
        _alembic("upgrade head")
        print("repeat upgrade verified")
    finally:
        with _connection("postgres", autocommit=True) as admin:
            admin.execute(
                "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname=%s AND pid<>pg_backend_pid()",
                (DATABASE_NAME,),
            )
            admin.execute(sql.SQL("DROP DATABASE IF EXISTS {}").format(sql.Identifier(DATABASE_NAME)))
        print("disposable database removed")


if __name__ == "__main__":
    main()
