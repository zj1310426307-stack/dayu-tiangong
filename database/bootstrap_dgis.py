"""Provision the least-privilege Martin login after DGIS database migration."""

from __future__ import annotations

import os
import re

import psycopg
from psycopg import sql


SAFE_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def _identifier(value: str, label: str) -> str:
    """Reject unsafe role or database identifiers before composing SQL."""

    if not SAFE_IDENTIFIER.fullmatch(value):
        raise ValueError(f"{label} is not a safe PostgreSQL identifier")
    return value


def main() -> None:
    """Create or rotate the Martin role and grant only MVT function access."""

    admin = _identifier(os.getenv("POSTGRES_USER", "dayu"), "POSTGRES_USER")
    database = _identifier(os.getenv("POSTGRES_DB", "dayu_tiangong"), "POSTGRES_DB")
    role_name = _identifier(os.getenv("MARTIN_DB_USER", "dayu_martin"), "MARTIN_DB_USER")
    role_password = os.environ["MARTIN_DB_PASSWORD"]
    connection = psycopg.connect(
        host=os.getenv("POSTGRES_HOST", "database"),
        port=int(os.getenv("POSTGRES_PORT", "5432")),
        dbname=database,
        user=admin,
        password=os.environ["POSTGRES_PASSWORD"],
        autocommit=True,
    )
    with connection, connection.cursor() as cursor:
        role = sql.Identifier(role_name)
        exists = cursor.execute(
            "SELECT EXISTS (SELECT 1 FROM pg_roles WHERE rolname=%s)", (role_name,)
        ).fetchone()[0]
        if exists:
            cursor.execute(
                sql.SQL("ALTER ROLE {} LOGIN PASSWORD {} NOSUPERUSER NOCREATEDB "
                        "NOCREATEROLE NOINHERIT NOREPLICATION").format(
                    role, sql.Literal(role_password)
                )
            )
        else:
            cursor.execute(
                sql.SQL("CREATE ROLE {} LOGIN PASSWORD {} NOSUPERUSER NOCREATEDB "
                        "NOCREATEROLE NOINHERIT NOREPLICATION").format(
                    role, sql.Literal(role_password)
                )
            )
        cursor.execute(sql.SQL("ALTER ROLE {} SET default_transaction_read_only=on").format(role))
        cursor.execute(sql.SQL("GRANT CONNECT ON DATABASE {} TO {}").format(
            sql.Identifier(database), role
        ))
        cursor.execute(sql.SQL("GRANT USAGE ON SCHEMA tiles TO {}").format(role))
        cursor.execute(sql.SQL("GRANT EXECUTE ON ALL FUNCTIONS IN SCHEMA tiles TO {}").format(role))
        cursor.execute(sql.SQL("GRANT USAGE ON SCHEMA public TO {}").format(role))
        cursor.execute(sql.SQL(
            "GRANT SELECT ON TABLE river, road, administrative_area, place_name, gate, pump TO {}"
        ).format(role))
    print(f"DGIS bootstrap complete: martin_role={role_name}, database={database}")


if __name__ == "__main__":
    main()
