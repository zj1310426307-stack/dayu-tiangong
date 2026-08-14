"""Verify that API and worker runtime use a non-owner database login."""

from __future__ import annotations

import os

import psycopg
import pytest
from sqlalchemy import text

from app.database.session import SessionLocal
from database.bootstrap_app import _identifier


requires_postgis = pytest.mark.skipif(
    os.getenv("RUN_POSTGIS_TESTS") != "1",
    reason="requires migrated PostGIS and application role bootstrap",
)


def test_app_bootstrap_rejects_unsafe_identifiers() -> None:
    """Keep environment-controlled role names out of raw SQL identifiers."""

    assert _identifier("dayu_backend", "role") == "dayu_backend"
    with pytest.raises(ValueError, match="unsupported characters"):
        _identifier("dayu_backend;DROP ROLE dayu", "role")


@requires_postgis
def test_backend_role_is_non_owner_inheriting_publisher() -> None:
    """Prove the runtime identity is restricted and receives publisher membership."""

    app_role = os.getenv("BACKEND_DB_USER") or os.getenv("POSTGRES_USER", "dayu_backend")
    publisher = os.getenv("QGIS_PUBLISHER_DB_USER", "dayu_publisher")
    with SessionLocal() as session:
        role = session.execute(
            text(
                "SELECT rolcanlogin, rolsuper, rolcreatedb, rolcreaterole, "
                "rolinherit, rolreplication, rolbypassrls FROM pg_roles WHERE rolname=:role"
            ),
            {"role": app_role},
        ).one()
        assert role.rolcanlogin is True
        assert role.rolinherit is True
        assert not any(
            (role.rolsuper, role.rolcreatedb, role.rolcreaterole, role.rolreplication, role.rolbypassrls)
        )
        assert session.scalar(
            text(
                "SELECT pg_has_role(:app_role, :publisher, 'MEMBER')"
            ),
            {"app_role": app_role, "publisher": publisher},
        ) is True
        assert session.scalar(
            text("SELECT has_schema_privilege(:role, 'public', 'CREATE')"),
            {"role": app_role},
        ) is False
        assert session.scalar(
            text("SELECT has_schema_privilege(:role, 'imports', 'CREATE')"),
            {"role": app_role},
        ) is True


@requires_postgis
def test_backend_login_can_run_application_dml_but_not_public_ddl() -> None:
    """Exercise the deployed login and roll back the harmless DML probe."""

    password = os.getenv("BACKEND_DB_PASSWORD") or os.getenv("POSTGRES_PASSWORD")
    if not password:
        pytest.fail("BACKEND_DB_PASSWORD is required for the live permission test")
    app_role = os.getenv("BACKEND_DB_USER") or os.getenv("POSTGRES_USER", "dayu_backend")
    with psycopg.connect(
        host=os.getenv("POSTGRES_VERIFY_HOST", "127.0.0.1"),
        port=int(os.getenv("POSTGRES_VERIFY_PORT", "5432")),
        dbname=os.getenv("POSTGRES_DB", "dayu_tiangong"),
        user=app_role,
        password=password,
        connect_timeout=5,
    ) as connection:
        with connection.cursor() as cursor:
            cursor.execute("SELECT count(*) FROM publish.river")
            assert cursor.fetchone()[0] >= 0
            cursor.execute("UPDATE public.river SET name=name WHERE false")
            connection.rollback()
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                cursor.execute("CREATE TABLE public.backend_permission_probe (id integer)")
            connection.rollback()
