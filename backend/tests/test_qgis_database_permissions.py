"""Verify GIS-OPT-1 database roles against a migrated local PostGIS instance."""

from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import MagicMock

import psycopg
import pytest
from sqlalchemy import text

from app.database.session import SessionLocal
from database.bootstrap_qgis import _identifier, _revoke_role_memberships


requires_postgis = pytest.mark.skipif(
    os.getenv("RUN_POSTGIS_TESTS") != "1",
    reason="requires migrated PostGIS and the QGIS role bootstrap",
)
REPOSITORY_ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(autouse=True)
def require_live_role_passwords() -> None:
    """Fail clearly instead of silently skipping live permission probes."""

    if os.getenv("RUN_POSTGIS_TESTS") != "1":
        return
    missing = [
        name
        for name in ("QGIS_EDITOR_DB_PASSWORD", "QGIS_REVIEWER_DB_PASSWORD")
        if not os.getenv(name)
    ]
    if missing:
        pytest.fail(f"missing required live-test secrets: {', '.join(missing)}")


def _role(name: str, fallback: str) -> str:
    """Return a validated role name from the live-test environment."""

    return _identifier(os.getenv(name, fallback), name)


def _role_connection(user: str, password_variable: str) -> psycopg.Connection:
    """Connect to the Compose-exposed database as one restricted login."""

    return psycopg.connect(
        host=os.getenv("POSTGRES_VERIFY_HOST", "127.0.0.1"),
        port=int(os.getenv("POSTGRES_VERIFY_PORT", "5432")),
        dbname=os.getenv("POSTGRES_DB", "dayu_tiangong"),
        user=user,
        password=os.environ[password_variable],
        connect_timeout=5,
    )


def test_qgis_bootstrap_rejects_unsafe_role_identifiers() -> None:
    """Prevent environment-controlled role names from becoming SQL identifiers."""

    assert _identifier("dayu_qgis_editor", "role") == "dayu_qgis_editor"
    with pytest.raises(ValueError, match="safe PostgreSQL identifier"):
        _identifier("dayu; DROP ROLE dayu", "role")


def test_qgis_bootstrap_revokes_role_memberships_in_both_directions() -> None:
    """Reset both inherited privileges and logins able to SET ROLE to the target."""

    cursor = MagicMock()
    cursor.fetchall.side_effect = [
        [("unexpected_parent",)],
        [("unexpected_member",)],
    ]

    _revoke_role_memberships(cursor, "dayu_publisher")

    calls = cursor.execute.call_args_list
    assert len(calls) == 4
    assert "WHERE member =" in calls[0].args[0]
    assert calls[0].args[1] == ("dayu_publisher",)
    assert "REVOKE" in str(calls[1].args[0])
    assert "WHERE roleid =" in calls[2].args[0]
    assert calls[2].args[1] == ("dayu_publisher",)
    assert "REVOKE" in str(calls[3].args[0])


def test_geoserver_source_keeps_basic_wfs_without_transactions() -> None:
    """Keep the source-controlled GeoServer service level explicitly read-only."""

    source = (REPOSITORY_ROOT / "geoserver" / "bootstrap.py").read_text(encoding="utf-8")
    assert "<serviceLevel>BASIC</serviceLevel>" in source
    assert "TRANSACTIONAL" not in source


@requires_postgis
def test_qgis_role_attributes_and_exact_privilege_matrix() -> None:
    """Prove editor, reviewer, and publisher privileges are separated by ownership."""

    editor = _role("QGIS_EDITOR_DB_USER", "dayu_qgis_editor")
    reviewer = _role("QGIS_REVIEWER_DB_USER", "dayu_qgis_reviewer")
    publisher = _role("QGIS_PUBLISHER_DB_USER", "dayu_publisher")
    with SessionLocal() as session:
        attributes = {
            row.rolname: row
            for row in session.execute(
                text(
                    "SELECT rolname, rolcanlogin, rolsuper, rolcreatedb, rolcreaterole, "
                    "rolreplication, rolbypassrls FROM pg_roles "
                    "WHERE rolname IN (:editor, :reviewer, :publisher)"
                ),
                {"editor": editor, "reviewer": reviewer, "publisher": publisher},
            )
        }
        assert set(attributes) == {editor, reviewer, publisher}
        assert attributes[editor].rolcanlogin is True
        assert attributes[reviewer].rolcanlogin is True
        assert attributes[publisher].rolcanlogin is False
        for role in attributes.values():
            assert not any(
                (
                    role.rolsuper,
                    role.rolcreatedb,
                    role.rolcreaterole,
                    role.rolreplication,
                    role.rolbypassrls,
                )
            )

        memberships = session.execute(
            text(
                "SELECT parent.rolname AS granted_role, member.rolname AS member_role "
                "FROM pg_auth_members membership "
                "JOIN pg_roles parent ON parent.oid = membership.roleid "
                "JOIN pg_roles member ON member.oid = membership.member "
                "WHERE parent.rolname IN (:editor, :reviewer, :publisher) "
                "OR member.rolname IN (:editor, :reviewer, :publisher)"
            ),
            {"editor": editor, "reviewer": reviewer, "publisher": publisher},
        ).all()
        backend_role = _role("BACKEND_DB_USER", "dayu_backend")
        assert memberships == [(publisher, backend_role)]

        privilege_sql = text(
            "SELECT has_table_privilege(:role, :table_name, :privilege)"
        )
        column_privilege_sql = text(
            "SELECT has_column_privilege(:role, :table_name, :column_name, :privilege)"
        )

        def allowed(role: str, table_name: str, privilege: str) -> bool:
            return bool(
                session.scalar(
                    privilege_sql,
                    {"role": role, "table_name": table_name, "privilege": privilege},
                )
            )

        def column_allowed(
            role: str, table_name: str, column_name: str, privilege: str
        ) -> bool:
            return bool(
                session.scalar(
                    column_privilege_sql,
                    {
                        "role": role,
                        "table_name": table_name,
                        "column_name": column_name,
                        "privilege": privilege,
                    },
                )
            )

        assert allowed(editor, "staging_qgis.river", "SELECT")
        assert allowed(editor, "staging_qgis.river", "DELETE")
        assert column_allowed(editor, "staging_qgis.river", "name", "INSERT")
        assert column_allowed(editor, "staging_qgis.river", "name", "UPDATE")
        assert not column_allowed(
            editor, "staging_qgis.river", "quality_status", "INSERT"
        )
        assert not column_allowed(editor, "staging_qgis.river", "source_hash", "UPDATE")
        assert not column_allowed(editor, "staging_qgis.river", "created_at", "UPDATE")
        assert not column_allowed(editor, "staging_qgis.river", "operator", "UPDATE")
        assert not column_allowed(
            editor, "staging_qgis.river", "source_payload", "UPDATE"
        )
        assert allowed(editor, "public.river", "SELECT")
        assert not allowed(editor, "public.river", "UPDATE")
        assert allowed(editor, "publish.river", "SELECT")
        assert not allowed(editor, "publish.river", "INSERT")

        assert allowed(reviewer, "staging_qgis.river", "SELECT")
        assert allowed(reviewer, "public.gis_validation_issue", "SELECT")
        assert allowed(reviewer, "publish.river", "SELECT")
        assert not allowed(reviewer, "staging_qgis.river", "UPDATE")
        assert not allowed(reviewer, "public.river", "UPDATE")

        assert allowed(publisher, "staging_qgis.river", "SELECT")
        assert allowed(publisher, "public.dataset_version", "INSERT")
        assert allowed(publisher, "public.river", "INSERT")
        assert allowed(publisher, "public.river_node", "DELETE")
        assert allowed(publisher, "public.gis_publication", "UPDATE")
        assert allowed(publisher, "publish.river", "SELECT")


@requires_postgis
def test_editor_can_write_staging_but_cannot_modify_or_ddl_core() -> None:
    """Exercise database enforcement without persisting a probe row or table."""

    editor = _role("QGIS_EDITOR_DB_USER", "dayu_qgis_editor")
    with _role_connection(editor, "QGIS_EDITOR_DB_PASSWORD") as connection:
        with connection.cursor() as cursor:
            cursor.execute("SHOW default_transaction_read_only")
            assert cursor.fetchone()[0] == "off"
            cursor.execute("UPDATE staging_qgis.river SET name = name WHERE false")
            connection.rollback()

            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                cursor.execute(
                    "UPDATE staging_qgis.river SET quality_status = 'passed' WHERE false"
                )
            connection.rollback()

            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                cursor.execute("UPDATE public.river SET name = name WHERE false")
            connection.rollback()

            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                cursor.execute("CREATE TABLE public.qgis_permission_probe (id integer)")
            connection.rollback()


@requires_postgis
def test_editor_insert_uses_batch_provenance_without_system_column_grants() -> None:
    """Exercise the exact QGIS INSERT columns and authoritative provenance trigger."""

    editor = _role("QGIS_EDITOR_DB_USER", "dayu_qgis_editor")
    token = os.urandom(8).hex()
    source_hash = (token * 4)[:64]
    with SessionLocal.begin() as owner_session:
        batch_id = owner_session.scalar(
            text(
                "INSERT INTO gis_import_batch "
                "(batch_code,entity_type,source_filename,source_format,source_size,"
                "source_hash_sha256,source_crs,target_crs,mapping_version,operator,status) "
                "VALUES (:batch_code,'river','permission.gpkg','GPKG',1,:source_hash,"
                "'EPSG:4490','EPSG:4490','river-v1','permission-editor','created') "
                "RETURNING id"
            ),
            {"batch_code": f"00000000-0000-4000-8000-{token[:12]}", "source_hash": source_hash},
        )

    try:
        with _role_connection(editor, "QGIS_EDITOR_DB_PASSWORD") as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    "INSERT INTO staging_qgis.river "
                    "(batch_id,source_feature_id,operation,name,code,length,level,status,geometry) "
                    "VALUES (%s,%s,'upsert','Permission probe',%s,100,'1','active',"
                    "ST_GeomFromText('LINESTRING(111 22,111.001 22.001)',4490)) "
                    "RETURNING source_crs,target_crs,source_hash,operator,quality_status",
                    (batch_id, f"probe-{token}", f"R-{token}"),
                )
                inherited = cursor.fetchone()
                assert inherited == (
                    "EPSG:4490",
                    "EPSG:4490",
                    source_hash,
                    "permission-editor",
                    "pending",
                )
                connection.rollback()
    finally:
        with SessionLocal.begin() as owner_session:
            owner_session.execute(
                text("DELETE FROM gis_import_batch WHERE id=:batch_id"),
                {"batch_id": batch_id},
            )


@requires_postgis
def test_reviewer_and_geoserver_are_read_only_and_publish_is_visible() -> None:
    """Prove reviewer reads governance while GeoServer cannot see staging or audit data."""

    reviewer = _role("QGIS_REVIEWER_DB_USER", "dayu_qgis_reviewer")
    with _role_connection(reviewer, "QGIS_REVIEWER_DB_PASSWORD") as connection:
        with connection.cursor() as cursor:
            cursor.execute("SHOW default_transaction_read_only")
            assert cursor.fetchone()[0] == "on"
            cursor.execute("SELECT count(*) FROM gis_validation_issue")
            assert cursor.fetchone()[0] >= 0
            cursor.execute("SELECT count(*) FROM publish.river")
            assert cursor.fetchone()[0] >= 0
            with pytest.raises(psycopg.errors.ReadOnlySqlTransaction):
                cursor.execute("UPDATE staging_qgis.river SET name = name WHERE false")
            connection.rollback()

    geoserver = _role("GEOSERVER_DB_USER", "dayu_geoserver")
    with SessionLocal() as session:
        assert session.scalar(
            text("SELECT has_table_privilege(:role, 'publish.river', 'SELECT')"),
            {"role": geoserver},
        )
        assert not session.scalar(
            text("SELECT has_schema_privilege(:role, 'staging_qgis', 'USAGE')"),
            {"role": geoserver},
        )
        assert not session.scalar(
            text("SELECT has_table_privilege(:role, 'gis_import_batch', 'SELECT')"),
            {"role": geoserver},
        )
