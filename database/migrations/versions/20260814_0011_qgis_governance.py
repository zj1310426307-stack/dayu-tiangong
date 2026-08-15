"""Add the GIS-OPT-1 QGIS-controlled governance data plane.

Revision ID: 20260814_0011
Revises: 20260813_0010
"""

from collections.abc import Sequence

from alembic import op
import geoalchemy2
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "20260814_0011"
down_revision: str | None = "20260813_0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _jsonb() -> postgresql.JSONB:
    """Return the repository-standard PostgreSQL JSONB type."""

    return postgresql.JSONB(astext_type=sa.Text())


def _staging_columns() -> list[sa.Column]:
    """Return the shared provenance columns used by every typed staging table."""

    return [
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("batch_id", sa.Integer(), nullable=False),
        sa.Column("source_feature_id", sa.String(length=128), nullable=False),
        sa.Column("operation", sa.String(length=12), server_default="upsert", nullable=False),
        sa.Column("quality_status", sa.String(length=16), server_default="pending", nullable=False),
        sa.Column("source_crs", sa.String(length=64), nullable=False),
        sa.Column("target_crs", sa.String(length=64), server_default="EPSG:4490", nullable=False),
        sa.Column("source_hash", sa.String(length=64), nullable=False),
        sa.Column("operator", sa.String(length=64), nullable=False),
        sa.Column("survey_time", sa.DateTime(timezone=True)),
        sa.Column(
            "source_payload", _jsonb(), server_default=sa.text("'{}'::jsonb"), nullable=False
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    ]


def _staging_constraints(prefix: str, business_key: str) -> list[sa.Constraint]:
    """Return the lifecycle, provenance, and identity constraints for a staging table."""

    return [
        sa.CheckConstraint(
            "operation IN ('upsert','delete')", name=f"ck_qgis_{prefix}_operation"
        ),
        sa.CheckConstraint(
            "quality_status IN ('pending','passed','failed')",
            name=f"ck_qgis_{prefix}_quality_status",
        ),
        sa.CheckConstraint("target_crs = 'EPSG:4490'", name=f"ck_qgis_{prefix}_target_crs"),
        sa.ForeignKeyConstraint(
            ["batch_id"], ["gis_import_batch.id"],
            name=f"fk_qgis_{prefix}_batch_id", ondelete="CASCADE",
        ),
        sa.UniqueConstraint(
            "batch_id", "source_feature_id", name=f"uq_qgis_{prefix}_source"
        ),
        sa.UniqueConstraint("batch_id", business_key, name=f"uq_qgis_{prefix}_{business_key}"),
    ]


def _create_publish_views() -> None:
    """Expose only published core versions through stable read-only GIS views."""

    op.execute("""
        CREATE VIEW publish.river AS
        SELECT r.id, r.dataset_version_id, dv.version AS dataset_version,
               r.name, r.code, r.length, r.level, r.status, r.description,
               r.geometry, dv.content_hash, dv.published_at
          FROM public.river AS r
          JOIN public.dataset_version AS dv ON dv.id = r.dataset_version_id
         WHERE dv.status = 'published'
    """)
    op.execute("""
        CREATE VIEW publish.cross_section AS
        SELECT cs.id, cs.dataset_version_id, dv.version AS dataset_version,
               cs.river_id, r.code AS river_code, cs.section_code, cs.section_name,
               cs.station, cs.points, cs.roughness, cs.elevation_min, cs.survey_date,
               cs.geometry, dv.content_hash, dv.published_at
          FROM public.cross_section AS cs
          JOIN public.dataset_version AS dv ON dv.id = cs.dataset_version_id
          JOIN public.river AS r ON r.id = cs.river_id
         WHERE dv.status = 'published'
    """)
    op.execute("""
        CREATE VIEW publish.gate AS
        SELECT g.id, g.dataset_version_id, dv.version AS dataset_version,
               g.river_id, r.code AS river_code, g.name, g.gate_code, g.gate_type,
               g.opening_direction, g.control_mode, g.width, g.height, g.max_flow,
               g.bottom_elevation, g.station, g.crest_elevation,
               g.discharge_coefficient, g.minimum_opening, g.maximum_opening,
               g.opening_rate_limit, g.minimum_hold_seconds, g.allow_reverse_flow,
               g.status, g.geometry, dv.content_hash, dv.published_at
          FROM public.gate AS g
          JOIN public.dataset_version AS dv ON dv.id = g.dataset_version_id
          JOIN public.river AS r ON r.id = g.river_id
         WHERE dv.status = 'published'
    """)
    op.execute("""
        CREATE VIEW publish.pump AS
        SELECT p.id, p.dataset_version_id, dv.version AS dataset_version,
               p.river_id, r.code AS river_code, p.name, p.pump_code,
               p.design_flow, p.head, p.power, p.efficiency_curve, p.head_curve,
               p.transfer_type, p.unit_count, p.minimum_running_units,
               p.maximum_running_units, p.minimum_run_seconds, p.minimum_stop_seconds,
               p.maximum_starts_per_run, p.minimum_operating_head,
               p.maximum_operating_head, p.reverse_flow_protection,
               p.control_mode, p.status, p.geometry, dv.content_hash, dv.published_at
          FROM public.pump AS p
          JOIN public.dataset_version AS dv ON dv.id = p.dataset_version_id
          JOIN public.river AS r ON r.id = p.river_id
         WHERE dv.status = 'published'
    """)


def _create_staging_provenance_triggers() -> None:
    """Fill read-only QGIS provenance fields from the selected source batch."""

    op.execute("""
        CREATE FUNCTION staging_qgis.apply_batch_provenance()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        DECLARE
            source_batch public.gis_import_batch%ROWTYPE;
        BEGIN
            SELECT * INTO source_batch
              FROM public.gis_import_batch
             WHERE id = NEW.batch_id;
            IF NOT FOUND THEN
                RAISE EXCEPTION 'GIS import batch % does not exist', NEW.batch_id
                    USING ERRCODE = 'foreign_key_violation';
            END IF;
            IF source_batch.entity_type <> TG_TABLE_NAME THEN
                RAISE EXCEPTION 'GIS import batch % is for %, not %',
                    NEW.batch_id, source_batch.entity_type, TG_TABLE_NAME
                    USING ERRCODE = 'check_violation';
            END IF;

            NEW.source_crs := source_batch.source_crs;
            NEW.target_crs := source_batch.target_crs;
            NEW.source_hash := source_batch.source_hash_sha256;
            NEW.operator := source_batch.operator;
            NEW.survey_time := COALESCE(NEW.survey_time, source_batch.survey_time);
            NEW.updated_at := CURRENT_TIMESTAMP;
            RETURN NEW;
        END;
        $$
    """)
    for table_name in ("river", "cross_section", "gate", "pump"):
        op.execute(f"""
            CREATE TRIGGER trg_qgis_{table_name}_batch_provenance
            BEFORE INSERT OR UPDATE ON staging_qgis.{table_name}
            FOR EACH ROW EXECUTE FUNCTION staging_qgis.apply_batch_provenance()
        """)


def _create_staging_promotion_guards() -> None:
    """Serialize promotion with QGIS DML and reject edits after the review gate."""

    op.execute("""
        CREATE FUNCTION staging_qgis.guard_batch_edit()
        RETURNS trigger
        LANGUAGE plpgsql
        SECURITY DEFINER
        SET search_path = pg_catalog, public, staging_qgis
        AS $$
        DECLARE
            selected_batch_id integer;
            selected_status varchar(24);
        BEGIN
            IF TG_OP = 'UPDATE' AND NEW.batch_id IS DISTINCT FROM OLD.batch_id THEN
                RAISE EXCEPTION 'A staged feature cannot move between GIS import batches'
                    USING ERRCODE = 'check_violation';
            END IF;
            IF TG_OP = 'DELETE' THEN
                selected_batch_id := OLD.batch_id;
            ELSE
                selected_batch_id := NEW.batch_id;
            END IF;
            SELECT status INTO selected_status
              FROM public.gis_import_batch
             WHERE id = selected_batch_id
             FOR UPDATE;
            IF NOT FOUND AND TG_OP <> 'DELETE' THEN
                RAISE EXCEPTION 'GIS import batch % does not exist', selected_batch_id
                    USING ERRCODE = 'foreign_key_violation';
            END IF;
            IF NOT FOUND THEN
                RETURN OLD;
            END IF;
            IF selected_status NOT IN (
                'created', 'staged', 'validation_failed', 'validated', 'changes_requested'
            ) THEN
                RAISE EXCEPTION 'GIS import batch % is % and cannot be edited',
                    selected_batch_id, selected_status
                    USING ERRCODE = 'object_not_in_prerequisite_state';
            END IF;
            IF TG_OP = 'DELETE' THEN
                RETURN OLD;
            END IF;
            RETURN NEW;
        END;
        $$
    """)
    op.execute(
        "REVOKE ALL ON FUNCTION staging_qgis.guard_batch_edit() FROM PUBLIC"
    )
    for table_name in ("river", "cross_section", "gate", "pump"):
        op.execute(f"""
            CREATE TRIGGER trg_qgis_{table_name}_guard_batch_edit
            BEFORE INSERT OR UPDATE OR DELETE ON staging_qgis.{table_name}
            FOR EACH ROW EXECUTE FUNCTION staging_qgis.guard_batch_edit()
        """)


def upgrade() -> None:
    """Create governance records, typed staging tables, and published read views."""

    op.execute("CREATE SCHEMA IF NOT EXISTS staging_qgis AUTHORIZATION CURRENT_USER")
    op.execute("CREATE SCHEMA IF NOT EXISTS publish AUTHORIZATION CURRENT_USER")
    op.execute("REVOKE ALL ON SCHEMA staging_qgis FROM PUBLIC")
    op.execute("REVOKE ALL ON SCHEMA publish FROM PUBLIC")

    op.create_table(
        "gis_import_batch",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("batch_code", sa.String(length=36), nullable=False),
        sa.Column("entity_type", sa.String(length=32), nullable=False),
        sa.Column("source_filename", sa.String(length=255), nullable=False),
        sa.Column("source_format", sa.String(length=64), nullable=False),
        sa.Column("source_size", sa.BigInteger(), nullable=False),
        sa.Column("source_hash_sha256", sa.String(length=64), nullable=False),
        sa.Column("source_crs", sa.String(length=64), nullable=False),
        sa.Column("target_crs", sa.String(length=64), server_default="EPSG:4490", nullable=False),
        sa.Column("mapping_version", sa.String(length=32), nullable=False),
        sa.Column("operator", sa.String(length=64), nullable=False),
        sa.Column("survey_time", sa.DateTime(timezone=True)),
        sa.Column("status", sa.String(length=24), server_default="created", nullable=False),
        sa.Column("raw_location", sa.Text()),
        sa.Column("raw_table_name", sa.String(length=63)),
        sa.Column("metadata_json", _jsonb(), server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("notes", sa.Text()),
        sa.Column("parent_version_id", sa.Integer()),
        sa.Column("parent_content_hash", sa.String(length=64)),
        sa.Column("staging_content_hash", sa.String(length=64)),
        sa.Column("promoted_dataset_version_id", sa.Integer()),
        sa.Column("staged_by", sa.String(length=64)),
        sa.Column("staged_at", sa.DateTime(timezone=True)),
        sa.Column("review_submitted_by", sa.String(length=64)),
        sa.Column("review_submitted_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint(
            "entity_type IN ('river','cross_section','gate','pump')",
            name="ck_gis_import_batch_entity_type",
        ),
        sa.CheckConstraint(
            "status IN ('created','staged','validating','validation_failed','validated',"
            "'in_review','changes_requested','rejected','approved','promoting','promoted',"
            "'published')",
            name="ck_gis_import_batch_status",
        ),
        sa.CheckConstraint("source_size >= 0", name="ck_gis_import_batch_source_size"),
        sa.CheckConstraint(
            "source_hash_sha256 ~ '^[0-9a-f]{64}$'",
            name="ck_gis_import_batch_source_hash",
        ),
        sa.CheckConstraint("target_crs = 'EPSG:4490'", name="ck_gis_import_batch_target_crs"),
        sa.CheckConstraint(
            "(parent_version_id IS NULL AND parent_content_hash IS NULL) OR "
            "(parent_version_id IS NOT NULL AND parent_content_hash IS NOT NULL)",
            name="ck_gis_import_batch_parent_hash_pair",
        ),
        sa.ForeignKeyConstraint(
            ["parent_version_id"], ["dataset_version.id"],
            name="fk_gis_import_batch_parent_version_id", ondelete="RESTRICT",
        ),
        sa.UniqueConstraint("batch_code", name="uq_gis_import_batch_code"),
        sa.UniqueConstraint("raw_table_name", name="uq_gis_import_batch_raw_table"),
        sa.UniqueConstraint(
            "promoted_dataset_version_id", name="uq_gis_import_batch_promoted_version"
        ),
    )
    op.create_index("ix_gis_import_batch_status", "gis_import_batch", ["status"])
    op.create_index(
        "ix_gis_import_batch_parent_version_id", "gis_import_batch", ["parent_version_id"]
    )

    op.add_column(
        "dataset_version",
        sa.Column("status", sa.String(length=16), server_default="draft", nullable=False),
    )
    op.add_column("dataset_version", sa.Column("parent_version_id", sa.Integer()))
    op.add_column("dataset_version", sa.Column("source_batch_id", sa.Integer()))
    op.add_column("dataset_version", sa.Column("content_hash", sa.String(length=64)))
    op.add_column("dataset_version", sa.Column("change_summary", sa.Text()))
    op.add_column("dataset_version", sa.Column("reviewed_by", sa.String(length=64)))
    op.add_column("dataset_version", sa.Column("reviewed_at", sa.DateTime(timezone=True)))
    op.add_column("dataset_version", sa.Column("approved_by", sa.String(length=64)))
    op.add_column("dataset_version", sa.Column("approved_at", sa.DateTime(timezone=True)))
    op.add_column("dataset_version", sa.Column("published_at", sa.DateTime(timezone=True)))
    op.add_column("dataset_version", sa.Column("retired_at", sa.DateTime(timezone=True)))
    op.execute("""
        UPDATE dataset_version AS dv
           SET status = 'published', published_at = dv.created_time
         WHERE dv.status = 'draft'
           AND (
               EXISTS (SELECT 1 FROM river r WHERE r.dataset_version_id = dv.id)
               OR EXISTS (SELECT 1 FROM cross_section cs WHERE cs.dataset_version_id = dv.id)
               OR EXISTS (SELECT 1 FROM gate g WHERE g.dataset_version_id = dv.id)
               OR EXISTS (SELECT 1 FROM pump p WHERE p.dataset_version_id = dv.id)
           )
    """)
    op.create_check_constraint(
        "ck_dataset_version_status", "dataset_version",
        "status IN ('draft','review','approved','published','retired','rejected')",
    )
    op.create_foreign_key(
        "fk_dataset_version_parent_version_id", "dataset_version", "dataset_version",
        ["parent_version_id"], ["id"], ondelete="RESTRICT",
    )
    op.create_foreign_key(
        "fk_dataset_version_source_batch_id", "dataset_version", "gis_import_batch",
        ["source_batch_id"], ["id"], ondelete="RESTRICT",
    )
    op.create_unique_constraint(
        "uq_dataset_version_source_batch_id", "dataset_version", ["source_batch_id"]
    )
    op.create_foreign_key(
        "fk_gis_import_batch_promoted_dataset_version_id",
        "gis_import_batch",
        "dataset_version",
        ["promoted_dataset_version_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_index("ix_dataset_version_status", "dataset_version", ["status"])
    op.create_index("ix_dataset_version_content_hash", "dataset_version", ["content_hash"])

    op.create_table(
        "gis_validation_run",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("batch_id", sa.Integer(), nullable=False),
        sa.Column("ruleset_version", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("staging_content_hash", sa.String(length=64), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.Column("summary_json", _jsonb(), nullable=False),
        sa.CheckConstraint(
            "status IN ('running','passed','failed')", name="ck_gis_validation_run_status"
        ),
        sa.ForeignKeyConstraint(
            ["batch_id"], ["gis_import_batch.id"],
            name="fk_gis_validation_run_batch_id", ondelete="CASCADE",
        ),
        sa.UniqueConstraint(
            "batch_id", "id", name="uq_gis_validation_run_batch_id_id"
        ),
    )
    op.create_index("ix_gis_validation_run_batch_id", "gis_validation_run", ["batch_id"])

    op.create_table(
        "gis_validation_issue",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("validation_run_id", sa.Integer(), nullable=False),
        sa.Column("batch_id", sa.Integer(), nullable=False),
        sa.Column("entity_type", sa.String(length=32), nullable=False),
        sa.Column("feature_ref", sa.String(length=128)),
        sa.Column("rule_code", sa.String(length=64), nullable=False),
        sa.Column("severity", sa.String(length=16), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column(
            "geometry", geoalchemy2.Geometry("GEOMETRY", srid=4490, spatial_index=False)
        ),
        sa.Column("details_json", _jsonb(), server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("resolved_at", sa.DateTime(timezone=True)),
        sa.Column("resolution_note", sa.Text()),
        sa.CheckConstraint(
            "entity_type IN ('river','cross_section','gate','pump')",
            name="ck_gis_validation_issue_entity_type",
        ),
        sa.CheckConstraint(
            "severity IN ('error','warning','info')", name="ck_gis_validation_issue_severity"
        ),
        sa.ForeignKeyConstraint(
            ["batch_id"], ["gis_import_batch.id"],
            name="fk_gis_validation_issue_batch_id", ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["batch_id", "validation_run_id"],
            ["gis_validation_run.batch_id", "gis_validation_run.id"],
            name="fk_gis_validation_issue_batch_run", ondelete="CASCADE",
        ),
    )
    op.create_index(
        "ix_gis_validation_issue_batch_severity", "gis_validation_issue",
        ["batch_id", "severity"],
    )
    op.create_index(
        "ix_gis_validation_issue_geometry_gist", "gis_validation_issue", ["geometry"],
        postgresql_using="gist",
    )

    op.create_table(
        "gis_review",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("batch_id", sa.Integer(), nullable=False),
        sa.Column("validation_run_id", sa.Integer(), nullable=False),
        sa.Column("staging_content_hash", sa.String(length=64), nullable=False),
        sa.Column("reviewer", sa.String(length=64), nullable=False),
        sa.Column("decision", sa.String(length=24), nullable=False),
        sa.Column("comment", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint(
            "decision IN ('approve','reject','request_changes')", name="ck_gis_review_decision"
        ),
        sa.ForeignKeyConstraint(
            ["batch_id"], ["gis_import_batch.id"],
            name="fk_gis_review_batch_id", ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["batch_id", "validation_run_id"],
            ["gis_validation_run.batch_id", "gis_validation_run.id"],
            name="fk_gis_review_batch_run", ondelete="RESTRICT",
        ),
    )
    op.create_index("ix_gis_review_batch_id", "gis_review", ["batch_id"])

    op.create_table(
        "gis_publication",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("dataset_version_id", sa.Integer(), nullable=False),
        sa.Column("publication_status", sa.String(length=16), nullable=False),
        sa.Column("published_by", sa.String(length=64), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True)),
        sa.Column("previous_publication_id", sa.Integer()),
        sa.Column("manifest_json", _jsonb(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint(
            "publication_status IN ('pending','published','failed','retired')",
            name="ck_gis_publication_status",
        ),
        sa.ForeignKeyConstraint(
            ["dataset_version_id"], ["dataset_version.id"],
            name="fk_gis_publication_dataset_version_id", ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["previous_publication_id"], ["gis_publication.id"],
            name="fk_gis_publication_previous_id", ondelete="SET NULL",
        ),
        sa.UniqueConstraint(
            "dataset_version_id", name="uq_gis_publication_dataset_version_id"
        ),
    )
    op.create_index("ix_gis_publication_status", "gis_publication", ["publication_status"])
    op.execute("""
        INSERT INTO gis_publication
            (dataset_version_id, publication_status, published_by, published_at,
             manifest_json)
        SELECT dv.id, 'published', 'migration', dv.published_at,
               jsonb_build_object(
                   'legacy_backfill', true,
                   'publish_boundary', 'existing public compatibility'
               )
          FROM dataset_version AS dv
         WHERE dv.status = 'published'
        ON CONFLICT (dataset_version_id) DO NOTHING
    """)

    op.create_table(
        "river",
        *_staging_columns(),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("code", sa.String(length=64), nullable=False),
        sa.Column("length", sa.Float(), nullable=False),
        sa.Column("level", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=24), server_default="active", nullable=False),
        sa.Column("description", sa.Text()),
        sa.Column(
            "geometry", geoalchemy2.Geometry("LINESTRING", srid=4490, spatial_index=False),
            nullable=False,
        ),
        *_staging_constraints("river", "code"),
        schema="staging_qgis",
    )
    op.create_index(
        "ix_qgis_river_geometry_gist", "river", ["geometry"],
        unique=False, schema="staging_qgis", postgresql_using="gist",
    )

    op.create_table(
        "cross_section",
        *_staging_columns(),
        sa.Column("river_code", sa.String(length=64), nullable=False),
        sa.Column("section_code", sa.String(length=64), nullable=False),
        sa.Column("section_name", sa.String(length=128), nullable=False),
        sa.Column("station", sa.Float(), nullable=False),
        sa.Column("points", _jsonb(), nullable=False),
        sa.Column("roughness", sa.Float(), nullable=False),
        sa.Column("elevation_min", sa.Float(), nullable=False),
        sa.Column("survey_date", sa.Date()),
        sa.Column(
            "geometry", geoalchemy2.Geometry("POINT", srid=4490, spatial_index=False),
            nullable=False,
        ),
        *_staging_constraints("section", "section_code"),
        schema="staging_qgis",
    )
    op.create_index(
        "ix_qgis_section_geometry_gist", "cross_section", ["geometry"],
        unique=False, schema="staging_qgis", postgresql_using="gist",
    )

    op.create_table(
        "gate",
        *_staging_columns(),
        sa.Column("river_code", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("gate_code", sa.String(length=64), nullable=False),
        sa.Column("gate_type", sa.String(length=32), nullable=False),
        sa.Column("opening_direction", sa.String(length=32), nullable=False),
        sa.Column("control_mode", sa.String(length=32), nullable=False),
        sa.Column("width", sa.Float(), nullable=False),
        sa.Column("height", sa.Float(), nullable=False),
        sa.Column("max_flow", sa.Float(), nullable=False),
        sa.Column("bottom_elevation", sa.Float(), nullable=False),
        sa.Column("station", sa.Float()),
        sa.Column("crest_elevation", sa.Float()),
        sa.Column("discharge_coefficient", sa.Float()),
        sa.Column("minimum_opening", sa.Float()),
        sa.Column("maximum_opening", sa.Float()),
        sa.Column("opening_rate_limit", sa.Float()),
        sa.Column("minimum_hold_seconds", sa.Float()),
        sa.Column("allow_reverse_flow", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("status", sa.String(length=24), server_default="offline", nullable=False),
        sa.Column(
            "geometry", geoalchemy2.Geometry("POINT", srid=4490, spatial_index=False),
            nullable=False,
        ),
        *_staging_constraints("gate", "gate_code"),
        schema="staging_qgis",
    )
    op.create_index(
        "ix_qgis_gate_geometry_gist", "gate", ["geometry"],
        unique=False, schema="staging_qgis", postgresql_using="gist",
    )

    op.create_table(
        "pump",
        *_staging_columns(),
        sa.Column("river_code", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("pump_code", sa.String(length=64), nullable=False),
        sa.Column("design_flow", sa.Float(), nullable=False),
        sa.Column("head", sa.Float(), nullable=False),
        sa.Column("power", sa.Float(), nullable=False),
        sa.Column("efficiency_curve", _jsonb(), nullable=False),
        sa.Column("head_curve", _jsonb()),
        sa.Column("transfer_type", sa.String(length=24)),
        sa.Column("unit_count", sa.Integer()),
        sa.Column("minimum_running_units", sa.Integer()),
        sa.Column("maximum_running_units", sa.Integer()),
        sa.Column("minimum_run_seconds", sa.Float()),
        sa.Column("minimum_stop_seconds", sa.Float()),
        sa.Column("maximum_starts_per_run", sa.Integer()),
        sa.Column("minimum_operating_head", sa.Float()),
        sa.Column("maximum_operating_head", sa.Float()),
        sa.Column("reverse_flow_protection", sa.Boolean(), server_default="true", nullable=False),
        sa.Column("control_mode", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=24), server_default="offline", nullable=False),
        sa.Column(
            "geometry", geoalchemy2.Geometry("POINT", srid=4490, spatial_index=False),
            nullable=False,
        ),
        *_staging_constraints("pump", "pump_code"),
        schema="staging_qgis",
    )
    op.create_index(
        "ix_qgis_pump_geometry_gist", "pump", ["geometry"],
        unique=False, schema="staging_qgis", postgresql_using="gist",
    )

    _create_staging_provenance_triggers()
    _create_staging_promotion_guards()
    _create_publish_views()


def downgrade() -> None:
    """Remove only objects introduced by GIS-OPT-1, preserving all earlier DGIS data."""

    for view_name in ("pump", "gate", "cross_section", "river"):
        op.execute(f"DROP VIEW IF EXISTS publish.{view_name}")
    for table_name in ("pump", "gate", "cross_section", "river"):
        op.execute(
            f"DROP TRIGGER IF EXISTS trg_qgis_{table_name}_guard_batch_edit "
            f"ON staging_qgis.{table_name}"
        )
        op.execute(
            f"DROP TRIGGER IF EXISTS trg_qgis_{table_name}_batch_provenance "
            f"ON staging_qgis.{table_name}"
        )
    op.execute("DROP FUNCTION IF EXISTS staging_qgis.guard_batch_edit()")
    op.execute("DROP FUNCTION IF EXISTS staging_qgis.apply_batch_provenance()")
    for table_name in ("pump", "gate", "cross_section", "river"):
        op.drop_table(table_name, schema="staging_qgis")

    op.drop_table("gis_publication")
    op.drop_table("gis_review")
    op.drop_table("gis_validation_issue")
    op.drop_table("gis_validation_run")

    op.drop_constraint(
        "fk_dataset_version_source_batch_id", "dataset_version", type_="foreignkey"
    )
    op.drop_constraint(
        "uq_dataset_version_source_batch_id", "dataset_version", type_="unique"
    )
    op.drop_constraint(
        "fk_gis_import_batch_promoted_dataset_version_id",
        "gis_import_batch",
        type_="foreignkey",
    )
    op.drop_table("gis_import_batch")
    op.drop_index("ix_dataset_version_content_hash", table_name="dataset_version")
    op.drop_index("ix_dataset_version_status", table_name="dataset_version")
    op.drop_constraint(
        "fk_dataset_version_parent_version_id", "dataset_version", type_="foreignkey"
    )
    op.drop_constraint("ck_dataset_version_status", "dataset_version", type_="check")
    for column_name in (
        "retired_at", "published_at", "approved_at", "approved_by", "reviewed_at",
        "reviewed_by", "change_summary", "content_hash", "source_batch_id",
        "parent_version_id", "status",
    ):
        op.drop_column("dataset_version", column_name)

    op.execute("DROP SCHEMA IF EXISTS publish")
    op.execute("DROP SCHEMA IF EXISTS staging_qgis")
