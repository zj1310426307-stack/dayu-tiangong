"""Prepare GeoNode metadata and asset roles in the existing PostgreSQL instance."""

from __future__ import annotations

import os
import re

import psycopg
from psycopg import sql


SAFE_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def _identifier(value: str, label: str) -> str:
    """Validate identifiers used for idempotent administrative SQL."""

    if not SAFE_IDENTIFIER.fullmatch(value):
        raise ValueError(f"{label} is not a safe PostgreSQL identifier")
    return value


def _ensure_role(cursor: psycopg.Cursor, name: str, password: str) -> None:
    """Create or rotate one non-superuser GeoNode database login."""

    role = sql.Identifier(name)
    exists = cursor.execute(
        "SELECT EXISTS (SELECT 1 FROM pg_roles WHERE rolname=%s)", (name,)
    ).fetchone()[0]
    statement = "ALTER ROLE" if exists else "CREATE ROLE"
    cursor.execute(
        sql.SQL(f"{statement} {{}} LOGIN PASSWORD {{}} NOSUPERUSER NOCREATEDB "
                "NOCREATEROLE NOINHERIT NOREPLICATION").format(role, sql.Literal(password))
    )


def main() -> None:
    """Create one metadata database and one isolated asset schema on shared PostGIS."""

    host = os.getenv("POSTGRES_HOST", "database")
    port = int(os.getenv("POSTGRES_PORT", "5432"))
    admin = _identifier(os.getenv("POSTGRES_USER", "dayu"), "POSTGRES_USER")
    spatial_database = _identifier(os.getenv("POSTGRES_DB", "dayu_tiangong"), "POSTGRES_DB")
    meta_database = _identifier(os.getenv("GEONODE_DATABASE", "dayu_geonode"), "GEONODE_DATABASE")
    meta_role = _identifier(os.getenv("GEONODE_DB_USER", "dayu_geonode"), "GEONODE_DB_USER")
    data_role = _identifier(
        os.getenv("GEONODE_DATA_DB_USER", "dayu_geonode_data"), "GEONODE_DATA_DB_USER"
    )
    admin_password = os.environ["POSTGRES_PASSWORD"]
    meta_password = os.environ["GEONODE_DB_PASSWORD"]
    data_password = os.environ["GEONODE_DATA_DB_PASSWORD"]

    control = psycopg.connect(
        host=host, port=port, dbname="postgres", user=admin,
        password=admin_password, autocommit=True,
    )
    with control, control.cursor() as cursor:
        _ensure_role(cursor, meta_role, meta_password)
        _ensure_role(cursor, data_role, data_password)
        exists = cursor.execute(
            "SELECT EXISTS (SELECT 1 FROM pg_database WHERE datname=%s)", (meta_database,)
        ).fetchone()[0]
        if not exists:
            cursor.execute(sql.SQL("CREATE DATABASE {} OWNER {}").format(
                sql.Identifier(meta_database), sql.Identifier(meta_role)
            ))

    metadata = psycopg.connect(
        host=host, port=port, dbname=meta_database, user=admin,
        password=admin_password, autocommit=True,
    )
    with metadata, metadata.cursor() as cursor:
        cursor.execute("CREATE EXTENSION IF NOT EXISTS postgis")
        cursor.execute(sql.SQL("GRANT ALL ON DATABASE {} TO {}").format(
            sql.Identifier(meta_database), sql.Identifier(meta_role)
        ))
        # PostgreSQL 15+ no longer grants CREATE on public to every role. This
        # database is dedicated to GeoNode metadata, so its owner must be able
        # to create Django migration tables in the public schema.
        cursor.execute(sql.SQL("ALTER SCHEMA public OWNER TO {}").format(
            sql.Identifier(meta_role)
        ))
        cursor.execute(sql.SQL("GRANT USAGE, CREATE ON SCHEMA public TO {}").format(
            sql.Identifier(meta_role)
        ))

    spatial = psycopg.connect(
        host=host, port=port, dbname=spatial_database, user=admin,
        password=admin_password, autocommit=True,
    )
    with spatial, spatial.cursor() as cursor:
        cursor.execute("CREATE SCHEMA IF NOT EXISTS geonode_assets")
        cursor.execute(sql.SQL("ALTER SCHEMA geonode_assets OWNER TO {}").format(
            sql.Identifier(data_role)
        ))
        cursor.execute(sql.SQL(
            "ALTER ROLE {} IN DATABASE {} SET search_path = geonode_assets, public"
        ).format(sql.Identifier(data_role), sql.Identifier(spatial_database)))
        cursor.execute(sql.SQL("GRANT USAGE ON SCHEMA public TO {}").format(
            sql.Identifier(data_role)
        ))
        cursor.execute(sql.SQL("GRANT SELECT ON ALL TABLES IN SCHEMA public TO {}").format(
            sql.Identifier(data_role)
        ))
    print(
        "GeoNode database bootstrap complete: "
        f"metadata={meta_database}, assets={spatial_database}.geonode_assets"
    )


if __name__ == "__main__":
    main()
