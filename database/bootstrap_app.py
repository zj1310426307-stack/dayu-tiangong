"""Provision the non-owner runtime login used by the API and worker."""

from __future__ import annotations

import os
import re

import psycopg
from psycopg import sql


def _identifier(value: str, label: str) -> str:
    """Reject unsafe PostgreSQL identifiers supplied through deployment settings."""

    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", value):
        raise ValueError(f"{label} contains unsupported characters")
    return value


def _ensure_login_role(cursor: psycopg.Cursor, role_name: str, password: str) -> None:
    """Create or rotate the application role without ownership capabilities."""

    role = sql.Identifier(role_name)
    exists = cursor.execute(
        "SELECT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = %s)",
        (role_name,),
    ).fetchone()[0]
    statement = "ALTER ROLE" if exists else "CREATE ROLE"
    cursor.execute(
        sql.SQL(
            f"{statement} {{}} WITH LOGIN PASSWORD {{}} INHERIT NOSUPERUSER "
            "NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS"
        ).format(role, sql.Literal(password))
    )
    cursor.execute(sql.SQL("ALTER ROLE {} RESET default_transaction_read_only").format(role))


def _reset_memberships(cursor: psycopg.Cursor, role_name: str) -> None:
    """Remove stale inherited roles before granting the explicit publisher group."""

    memberships = cursor.execute(
        """
        SELECT parent.rolname
          FROM pg_auth_members AS membership
          JOIN pg_roles AS parent ON parent.oid = membership.roleid
          JOIN pg_roles AS member ON member.oid = membership.member
         WHERE member.rolname = %s
        """,
        (role_name,),
    ).fetchall()
    for (parent_name,) in memberships:
        cursor.execute(
            sql.SQL("REVOKE {} FROM {}").format(
                sql.Identifier(parent_name), sql.Identifier(role_name)
            )
        )


def _configure_privileges(
    cursor: psycopg.Cursor,
    *,
    owner: str,
    database: str,
    app_role: str,
    publisher: str,
) -> None:
    """Apply the complete runtime allow-list and publisher membership."""

    role = sql.Identifier(app_role)
    owner_id = sql.Identifier(owner)
    database_id = sql.Identifier(database)
    publisher_id = sql.Identifier(publisher)
    cursor.execute(sql.SQL("REVOKE ALL ON DATABASE {} FROM {}").format(database_id, role))
    cursor.execute(sql.SQL("GRANT CONNECT ON DATABASE {} TO {}").format(database_id, role))
    for schema_name in ("public", "staging_qgis", "publish", "imports"):
        schema = sql.Identifier(schema_name)
        cursor.execute(sql.SQL("REVOKE ALL ON SCHEMA {} FROM {}").format(schema, role))
        cursor.execute(sql.SQL("GRANT USAGE ON SCHEMA {} TO {}").format(schema, role))
    cursor.execute(sql.SQL("GRANT CREATE ON SCHEMA imports TO {}").format(role))

    for schema_name in ("public", "staging_qgis", "imports"):
        schema = sql.Identifier(schema_name)
        cursor.execute(
            sql.SQL(
                "GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA {} TO {}"
            ).format(schema, role)
        )
        cursor.execute(
            sql.SQL(
                "GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA {} TO {}"
            ).format(schema, role)
        )
    cursor.execute(sql.SQL("GRANT SELECT ON ALL TABLES IN SCHEMA publish TO {}").format(role))

    for schema_name in ("public", "staging_qgis"):
        schema = sql.Identifier(schema_name)
        cursor.execute(
            sql.SQL(
                "ALTER DEFAULT PRIVILEGES FOR ROLE {} IN SCHEMA {} "
                "GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO {}"
            ).format(owner_id, schema, role)
        )
        cursor.execute(
            sql.SQL(
                "ALTER DEFAULT PRIVILEGES FOR ROLE {} IN SCHEMA {} "
                "GRANT USAGE, SELECT ON SEQUENCES TO {}"
            ).format(owner_id, schema, role)
        )
    cursor.execute(
        sql.SQL(
            "ALTER DEFAULT PRIVILEGES FOR ROLE {} IN SCHEMA publish "
            "GRANT SELECT ON TABLES TO {}"
        ).format(owner_id, role)
    )
    cursor.execute(sql.SQL("GRANT {} TO {}").format(publisher_id, role))


def main() -> None:
    """Create the application login and make it the inheriting publisher member."""

    owner = _identifier(os.getenv("POSTGRES_USER", "dayu"), "POSTGRES_USER")
    database = _identifier(os.getenv("POSTGRES_DB", "dayu_tiangong"), "POSTGRES_DB")
    app_role = _identifier(os.getenv("BACKEND_DB_USER", "dayu_backend"), "BACKEND_DB_USER")
    publisher = _identifier(
        os.getenv("QGIS_PUBLISHER_DB_USER", "dayu_publisher"),
        "QGIS_PUBLISHER_DB_USER",
    )
    if len({owner, app_role, publisher}) != 3:
        raise ValueError("owner, backend, and publisher roles must be distinct")
    password = os.environ["BACKEND_DB_PASSWORD"]
    if not password:
        raise ValueError("BACKEND_DB_PASSWORD must not be empty")

    connection = psycopg.connect(
        host=os.getenv("POSTGRES_HOST", "database"),
        port=int(os.getenv("POSTGRES_PORT", "5432")),
        dbname=database,
        user=owner,
        password=os.environ["POSTGRES_PASSWORD"],
        autocommit=True,
    )
    with connection, connection.cursor() as cursor:
        _ensure_login_role(cursor, app_role, password)
        _reset_memberships(cursor, app_role)
        _configure_privileges(
            cursor,
            owner=owner,
            database=database,
            app_role=app_role,
            publisher=publisher,
        )
    print(
        "Application bootstrap complete: "
        f"role={app_role}, publisher={publisher}, database={database}"
    )


if __name__ == "__main__":
    main()
