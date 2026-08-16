"""Provision least-privilege roles for the controlled QGIS production chain."""

from __future__ import annotations

import os
import re

import psycopg
from psycopg import sql


SAFE_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")

REFERENCE_TABLES = (
    "dataset_version",
    "river",
    "river_node",
    "river_segment",
    "cross_section",
    "gate",
    "pump",
    "map_annotation",
    "administrative_area",
    "road",
    "place_name",
    "water_name",
    "poi",
)
STAGING_TABLES = ("river", "cross_section", "gate", "pump")
STAGING_INSERT_COLUMNS = {
    "river": (
        "batch_id", "source_feature_id", "operation", "survey_time", "name", "code",
        "length", "level", "status", "description", "geometry",
    ),
    "cross_section": (
        "batch_id", "source_feature_id", "operation", "survey_time", "river_code",
        "section_code", "section_name", "station", "points", "roughness",
        "elevation_min", "survey_date", "geometry",
    ),
    "gate": (
        "batch_id", "source_feature_id", "operation", "survey_time", "river_code",
        "name", "gate_code", "gate_type", "opening_direction", "control_mode", "width",
        "height", "max_flow", "bottom_elevation", "station", "crest_elevation",
        "discharge_coefficient", "minimum_opening", "maximum_opening",
        "opening_rate_limit", "minimum_hold_seconds", "allow_reverse_flow", "status",
        "geometry",
    ),
    "pump": (
        "batch_id", "source_feature_id", "operation", "survey_time", "river_code",
        "name", "pump_code", "design_flow", "head", "power", "efficiency_curve",
        "head_curve", "transfer_type", "unit_count", "minimum_running_units",
        "maximum_running_units", "minimum_run_seconds", "minimum_stop_seconds",
        "maximum_starts_per_run", "minimum_operating_head", "maximum_operating_head",
        "reverse_flow_protection", "control_mode", "status", "geometry",
    ),
}
# Batch identity cannot be moved on UPDATE; the database guard enforces this as
# well.  Provenance, QC state, source payload, and system timestamps are absent.
STAGING_UPDATE_COLUMNS = {
    table_name: tuple(column for column in columns if column != "batch_id")
    for table_name, columns in STAGING_INSERT_COLUMNS.items()
}
EDITOR_GOVERNANCE_TABLES = (
    "gis_import_batch",
    "gis_validation_run",
    "gis_validation_issue",
)
REVIEWER_GOVERNANCE_TABLES = (
    *EDITOR_GOVERNANCE_TABLES,
    "gis_review",
    "gis_publication",
)
PROMOTION_CORE_TABLES = (
    "dataset_version",
    "river",
    "river_node",
    "river_segment",
    "river_connection",
    "cross_section",
    "gate",
    "pump",
)
QGIS_SERVER_RELATIONS = ("river", "cross_section", "gate", "pump")


def _identifier(value: str, label: str) -> str:
    """Reject unsafe database and role identifiers before composing SQL."""

    if not SAFE_IDENTIFIER.fullmatch(value):
        raise ValueError(f"{label} is not a safe PostgreSQL identifier")
    return value


def _identifiers(values: tuple[str, ...]) -> sql.Composed:
    """Compose a comma-separated list of trusted table identifiers."""

    return sql.SQL(", ").join(sql.Identifier(value) for value in values)


def _qualified_identifiers(schema_name: str, values: tuple[str, ...]) -> sql.Composed:
    """Compose trusted schema-qualified table identifiers correctly."""

    return sql.SQL(", ").join(sql.Identifier(schema_name, value) for value in values)


def _ensure_login_role(
    cursor: psycopg.Cursor[tuple[object, ...]], role_name: str, password: str
) -> None:
    """Create or rotate a restricted login role without inheriting other roles."""

    role = sql.Identifier(role_name)
    exists = cursor.execute(
        "SELECT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = %s)", (role_name,)
    ).fetchone()[0]
    statement = "ALTER ROLE" if exists else "CREATE ROLE"
    cursor.execute(
        sql.SQL(
            f"{statement} {{}} LOGIN PASSWORD {{}} NOSUPERUSER NOCREATEDB "
            "NOCREATEROLE NOINHERIT NOREPLICATION NOBYPASSRLS"
        ).format(role, sql.Literal(password))
    )


def _ensure_group_role(
    cursor: psycopg.Cursor[tuple[object, ...]], role_name: str
) -> None:
    """Create or normalize the publisher as a non-login service group role."""

    role = sql.Identifier(role_name)
    exists = cursor.execute(
        "SELECT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = %s)", (role_name,)
    ).fetchone()[0]
    statement = "ALTER ROLE" if exists else "CREATE ROLE"
    cursor.execute(
        sql.SQL(
            f"{statement} {{}} NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE "
            "NOINHERIT NOREPLICATION NOBYPASSRLS"
        ).format(role)
    )


def _revoke_role_memberships(
    cursor: psycopg.Cursor[tuple[object, ...]], role_name: str
) -> None:
    """Detach a governed role in both directions before applying its grants.

    An unexpected parent role could let the target acquire extra privileges,
    while an unexpected member could ``SET ROLE`` to the target's privileges.
    The QGIS roles, including the NOLOGIN publisher group, start with neither.
    """

    role = sql.Identifier(role_name)
    cursor.execute(
        "SELECT pg_catalog.pg_get_userbyid(roleid) "
        "FROM pg_catalog.pg_auth_members "
        "WHERE member = (SELECT oid FROM pg_catalog.pg_roles WHERE rolname = %s)",
        (role_name,),
    )
    for (granted_role,) in cursor.fetchall():
        cursor.execute(
            sql.SQL("REVOKE {} FROM {}").format(
                sql.Identifier(str(granted_role)), role
            )
        )

    cursor.execute(
        "SELECT pg_catalog.pg_get_userbyid(member) "
        "FROM pg_catalog.pg_auth_members "
        "WHERE roleid = (SELECT oid FROM pg_catalog.pg_roles WHERE rolname = %s)",
        (role_name,),
    )
    for (member_role,) in cursor.fetchall():
        cursor.execute(
            sql.SQL("REVOKE {} FROM {}").format(
                role, sql.Identifier(str(member_role))
            )
        )


def _reset_role_privileges(
    cursor: psycopg.Cursor[tuple[object, ...]],
    *,
    owner: str,
    database: str,
    role_name: str,
) -> None:
    """Remove direct and owner-default grants before applying the allow-list."""

    role = sql.Identifier(role_name)
    owner_role = sql.Identifier(owner)
    _revoke_role_memberships(cursor, role_name)
    cursor.execute(
        sql.SQL("REVOKE ALL ON DATABASE {} FROM {}").format(
            sql.Identifier(database), role
        )
    )
    for schema_name in ("public", "staging_qgis", "publish", "imports", "tiles"):
        schema = sql.Identifier(schema_name)
        cursor.execute(sql.SQL("REVOKE ALL ON SCHEMA {} FROM {}").format(schema, role))
        cursor.execute(
            sql.SQL("REVOKE ALL ON ALL TABLES IN SCHEMA {} FROM {}").format(
                schema, role
            )
        )
        cursor.execute(
            sql.SQL("REVOKE ALL ON ALL SEQUENCES IN SCHEMA {} FROM {}").format(
                schema, role
            )
        )
        cursor.execute(
            sql.SQL(
                "ALTER DEFAULT PRIVILEGES FOR ROLE {} IN SCHEMA {} "
                "REVOKE ALL ON TABLES FROM {}"
            ).format(owner_role, schema, role)
        )
        cursor.execute(
            sql.SQL(
                "ALTER DEFAULT PRIVILEGES FOR ROLE {} IN SCHEMA {} "
                "REVOKE ALL ON SEQUENCES FROM {}"
            ).format(owner_role, schema, role)
        )


def _grant_common_read(
    cursor: psycopg.Cursor[tuple[object, ...]], role_name: str
) -> None:
    """Grant the shared reference and published-view read surface."""

    role = sql.Identifier(role_name)
    cursor.execute(sql.SQL("GRANT USAGE ON SCHEMA public TO {}").format(role))
    cursor.execute(sql.SQL("GRANT USAGE ON SCHEMA publish TO {}").format(role))
    cursor.execute(
        sql.SQL("GRANT SELECT ON TABLE {} TO {}").format(
            _identifiers(REFERENCE_TABLES), role
        )
    )
    cursor.execute(
        sql.SQL("GRANT SELECT ON ALL TABLES IN SCHEMA publish TO {}").format(role)
    )


def _configure_editor(
    cursor: psycopg.Cursor[tuple[object, ...]],
    *,
    owner: str,
    database: str,
    role_name: str,
) -> None:
    """Allow QGIS editing only in typed staging tables."""

    role = sql.Identifier(role_name)
    cursor.execute(
        sql.SQL("ALTER ROLE {} SET default_transaction_read_only = off").format(role)
    )
    cursor.execute(
        sql.SQL("ALTER ROLE {} SET search_path = staging_qgis, publish, public").format(role)
    )
    cursor.execute(
        sql.SQL("GRANT CONNECT ON DATABASE {} TO {}").format(
            sql.Identifier(database), role
        )
    )
    _grant_common_read(cursor, role_name)
    cursor.execute(sql.SQL("GRANT USAGE ON SCHEMA staging_qgis TO {}").format(role))
    cursor.execute(
        sql.SQL("GRANT SELECT, DELETE ON TABLE {} TO {}").format(
            _qualified_identifiers("staging_qgis", STAGING_TABLES), role
        )
    )
    for table_name in STAGING_TABLES:
        cursor.execute(
            sql.SQL("GRANT INSERT ({}) ON TABLE {} TO {}").format(
                _identifiers(STAGING_INSERT_COLUMNS[table_name]),
                sql.Identifier("staging_qgis", table_name),
                role,
            )
        )
        cursor.execute(
            sql.SQL("GRANT UPDATE ({}) ON TABLE {} TO {}").format(
                _identifiers(STAGING_UPDATE_COLUMNS[table_name]),
                sql.Identifier("staging_qgis", table_name),
                role,
            )
        )
    cursor.execute(
        sql.SQL(
            "GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA staging_qgis TO {}"
        ).format(role)
    )
    cursor.execute(
        sql.SQL("GRANT SELECT ON TABLE {} TO {}").format(
            _identifiers(EDITOR_GOVERNANCE_TABLES), role
        )
    )


def _configure_reviewer(
    cursor: psycopg.Cursor[tuple[object, ...]],
    *,
    owner: str,
    database: str,
    role_name: str,
) -> None:
    """Allow reviewers to inspect staging and governance without direct writes."""

    role = sql.Identifier(role_name)
    cursor.execute(
        sql.SQL("ALTER ROLE {} SET default_transaction_read_only = on").format(role)
    )
    cursor.execute(
        sql.SQL("ALTER ROLE {} SET search_path = publish, staging_qgis, public").format(role)
    )
    cursor.execute(
        sql.SQL("GRANT CONNECT ON DATABASE {} TO {}").format(
            sql.Identifier(database), role
        )
    )
    _grant_common_read(cursor, role_name)
    cursor.execute(sql.SQL("GRANT USAGE ON SCHEMA staging_qgis TO {}").format(role))
    cursor.execute(
        sql.SQL("GRANT SELECT ON TABLE {} TO {}").format(
            _qualified_identifiers("staging_qgis", STAGING_TABLES),
            role,
        )
    )
    cursor.execute(
        sql.SQL("GRANT SELECT ON TABLE {} TO {}").format(
            _identifiers(REVIEWER_GOVERNANCE_TABLES), role
        )
    )


def _configure_publisher(
    cursor: psycopg.Cursor[tuple[object, ...]],
    *,
    owner: str,
    database: str,
    role_name: str,
) -> None:
    """Grant a non-login backend role only the promotion and publication surface."""

    role = sql.Identifier(role_name)
    cursor.execute(
        sql.SQL("GRANT CONNECT ON DATABASE {} TO {}").format(
            sql.Identifier(database), role
        )
    )
    cursor.execute(sql.SQL("GRANT USAGE ON SCHEMA public TO {}").format(role))
    cursor.execute(sql.SQL("GRANT USAGE ON SCHEMA staging_qgis TO {}").format(role))
    cursor.execute(sql.SQL("GRANT USAGE ON SCHEMA publish TO {}").format(role))
    cursor.execute(
        sql.SQL("GRANT SELECT ON TABLE {} TO {}").format(
            _qualified_identifiers("staging_qgis", STAGING_TABLES),
            role,
        )
    )
    cursor.execute(
        sql.SQL("GRANT SELECT ON TABLE {} TO {}").format(
            _identifiers(REVIEWER_GOVERNANCE_TABLES), role
        )
    )
    cursor.execute(
        sql.SQL("GRANT SELECT, INSERT, UPDATE ON TABLE {} TO {}").format(
            _identifiers(("dataset_version", "gis_import_batch", "gis_publication")),
            role,
        )
    )
    cursor.execute(
        sql.SQL("GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE {} TO {}").format(
            _identifiers(PROMOTION_CORE_TABLES[1:]), role
        )
    )
    cursor.execute(
        sql.SQL("GRANT USAGE, SELECT ON SEQUENCE {} TO {}").format(
            _identifiers(tuple(f"{name}_id_seq" for name in PROMOTION_CORE_TABLES)),
            role,
        )
    )
    cursor.execute(
        sql.SQL("GRANT USAGE, SELECT ON SEQUENCE {} TO {}").format(
            _identifiers(("gis_publication_id_seq",)), role
        )
    )
    cursor.execute(
        sql.SQL("GRANT SELECT ON ALL TABLES IN SCHEMA publish TO {}").format(role)
    )


def _configure_qgis_server(
    cursor: psycopg.Cursor[tuple[object, ...]],
    *,
    database: str,
    role_name: str,
) -> None:
    """Grant the headless renderer only the four project allow-list views."""

    role = sql.Identifier(role_name)
    cursor.execute(
        sql.SQL("ALTER ROLE {} SET default_transaction_read_only = on").format(role)
    )
    cursor.execute(
        sql.SQL("ALTER ROLE {} SET search_path = publish, public, pg_catalog").format(role)
    )
    cursor.execute(
        sql.SQL("GRANT CONNECT ON DATABASE {} TO {}").format(
            sql.Identifier(database), role
        )
    )
    cursor.execute(sql.SQL("GRANT USAGE ON SCHEMA publish TO {}").format(role))
    # QGIS' PostgreSQL provider discovers PostGIS metadata and invokes extension
    # functions by their unqualified names.  Schema USAGE does not grant access
    # to core tables, so the renderer remains constrained to the explicit views.
    cursor.execute(sql.SQL("GRANT USAGE ON SCHEMA public TO {}").format(role))
    cursor.execute(
        sql.SQL("GRANT SELECT ON TABLE {} TO {}").format(
            _qualified_identifiers("publish", QGIS_SERVER_RELATIONS), role
        )
    )


def main() -> None:
    """Create or rotate QGIS roles and reapply the complete privilege allow-list."""

    owner = _identifier(os.getenv("POSTGRES_USER", "dayu"), "POSTGRES_USER")
    database = _identifier(os.getenv("POSTGRES_DB", "dayu_tiangong"), "POSTGRES_DB")
    editor = _identifier(
        os.getenv("QGIS_EDITOR_DB_USER", "dayu_qgis_editor"), "QGIS_EDITOR_DB_USER"
    )
    reviewer = _identifier(
        os.getenv("QGIS_REVIEWER_DB_USER", "dayu_qgis_reviewer"),
        "QGIS_REVIEWER_DB_USER",
    )
    publisher = _identifier(
        os.getenv("QGIS_PUBLISHER_DB_USER", "dayu_publisher"),
        "QGIS_PUBLISHER_DB_USER",
    )
    qgis_server = _identifier(
        os.getenv("QGIS_SERVER_DB_USER", "dayu_qgis_server"),
        "QGIS_SERVER_DB_USER",
    )
    if len({owner, editor, reviewer, publisher, qgis_server}) != 5:
        raise ValueError("QGIS database roles and POSTGRES_USER must be distinct")

    connection = psycopg.connect(
        host=os.getenv("POSTGRES_HOST", "database"),
        port=int(os.getenv("POSTGRES_PORT", "5432")),
        dbname=database,
        user=owner,
        password=os.environ["POSTGRES_PASSWORD"],
        autocommit=True,
    )
    with connection, connection.cursor() as cursor:
        _ensure_login_role(cursor, editor, os.environ["QGIS_EDITOR_DB_PASSWORD"])
        _ensure_login_role(cursor, reviewer, os.environ["QGIS_REVIEWER_DB_PASSWORD"])
        _ensure_login_role(cursor, qgis_server, os.environ["QGIS_SERVER_DB_PASSWORD"])
        _ensure_group_role(cursor, publisher)
        cursor.execute("REVOKE CREATE ON SCHEMA public FROM PUBLIC")
        for role_name in (editor, reviewer, publisher, qgis_server):
            _reset_role_privileges(
                cursor, owner=owner, database=database, role_name=role_name
            )
        _configure_editor(
            cursor, owner=owner, database=database, role_name=editor
        )
        _configure_reviewer(
            cursor, owner=owner, database=database, role_name=reviewer
        )
        _configure_publisher(
            cursor, owner=owner, database=database, role_name=publisher
        )
        _configure_qgis_server(cursor, database=database, role_name=qgis_server)
    print(
        "QGIS bootstrap complete: "
        f"editor={editor}, reviewer={reviewer}, publisher={publisher}, "
        f"qgis_server={qgis_server}, database={database}"
    )


if __name__ == "__main__":
    main()
