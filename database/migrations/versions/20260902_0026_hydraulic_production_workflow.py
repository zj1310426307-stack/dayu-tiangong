"""Add the auditable hydraulic production workflow records.

Revision ID: 20260902_0026
Revises: 20260901_0025
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "20260902_0026"
down_revision: str | None = "20260901_0025"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create additive, solver-neutral production evidence tables."""

    op.create_table(
        "import_mapping_profile",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("dataset_version_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("profile_type", sa.String(32), nullable=False),
        sa.Column("schema_version", sa.String(32), nullable=False),
        sa.Column("mapping_json", postgresql.JSONB(), nullable=False),
        sa.Column("created_by", sa.String(128), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint(
            "profile_type IN ('engineering','boundary','observation','external_result')",
            name="ck_hydraulic_import_mapping_profile_type",
        ),
        sa.ForeignKeyConstraint(
            ["dataset_version_id"], ["dataset_version.id"], ondelete="CASCADE"
        ),
        sa.UniqueConstraint(
            "dataset_version_id", "name", name="uq_hydraulic_mapping_profile_name"
        ),
        schema="hydraulic",
    )
    op.create_index(
        "ix_hydraulic_mapping_profile_version",
        "import_mapping_profile",
        ["dataset_version_id", "profile_type"],
        schema="hydraulic",
    )

    op.create_table(
        "observation_series",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("dataset_version_id", sa.Integer(), nullable=False),
        sa.Column("series_code", sa.String(128), nullable=False),
        sa.Column("station_id", sa.String(128), nullable=False),
        sa.Column("branch_id", sa.Integer(), nullable=False),
        sa.Column("chainage_m", sa.Float(), nullable=False),
        sa.Column("variable", sa.String(24), nullable=False),
        sa.Column("unit", sa.String(16), nullable=False),
        sa.Column("vertical_datum", sa.String(64), nullable=False),
        sa.Column("time_basis", sa.String(16), nullable=False),
        sa.Column("timezone", sa.String(64)),
        sa.Column("source", sa.String(256), nullable=False),
        sa.Column("source_filename", sa.String(255), nullable=False),
        sa.Column("source_sha256", sa.String(64), nullable=False),
        sa.Column("samples_json", postgresql.JSONB(), nullable=False),
        sa.Column("mapping_profile_id", sa.Integer()),
        sa.Column(
            "imported_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint(
            "variable IN ('water_level','discharge')",
            name="ck_hydraulic_observation_variable",
        ),
        sa.CheckConstraint(
            "time_basis IN ('relative','absolute')",
            name="ck_hydraulic_observation_time_basis",
        ),
        sa.ForeignKeyConstraint(
            ["dataset_version_id"], ["dataset_version.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["branch_id", "dataset_version_id"],
            ["hydraulic.branch.id", "hydraulic.branch.dataset_version_id"],
            name="fk_hydraulic_observation_branch_version",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["mapping_profile_id"],
            ["hydraulic.import_mapping_profile.id"],
            ondelete="SET NULL",
        ),
        sa.UniqueConstraint(
            "dataset_version_id",
            "series_code",
            name="uq_hydraulic_observation_series_code",
        ),
        schema="hydraulic",
    )
    op.create_index(
        "ix_hydraulic_observation_location",
        "observation_series",
        ["dataset_version_id", "branch_id", "chainage_m"],
        schema="hydraulic",
    )

    op.create_table(
        "external_result",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("dataset_version_id", sa.Integer(), nullable=False),
        sa.Column("result_code", sa.String(128), nullable=False),
        sa.Column("external_model_name", sa.String(128), nullable=False),
        sa.Column("external_model_version", sa.String(128), nullable=False),
        sa.Column("scenario", sa.String(128), nullable=False),
        sa.Column("vertical_datum", sa.String(64), nullable=False),
        sa.Column("source_filename", sa.String(255), nullable=False),
        sa.Column("source_sha256", sa.String(64), nullable=False),
        sa.Column("mapping_json", postgresql.JSONB(), nullable=False),
        sa.Column("points_json", postgresql.JSONB(), nullable=False),
        sa.Column("provenance_json", postgresql.JSONB(), nullable=False),
        sa.Column(
            "imported_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.ForeignKeyConstraint(
            ["dataset_version_id"], ["dataset_version.id"], ondelete="CASCADE"
        ),
        sa.UniqueConstraint(
            "dataset_version_id",
            "result_code",
            name="uq_hydraulic_external_result_code",
        ),
        schema="hydraulic",
    )
    op.create_index(
        "ix_hydraulic_external_result_scenario",
        "external_result",
        ["dataset_version_id", "scenario"],
        schema="hydraulic",
    )

    op.create_table(
        "production_run",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("run_code", sa.String(64), nullable=False),
        sa.Column("dataset_version_id", sa.Integer(), nullable=False),
        sa.Column("case_id", sa.Integer(), nullable=False),
        sa.Column("task_id", sa.Integer()),
        sa.Column("qa_run_code", sa.String(64), nullable=False),
        sa.Column("model_state", sa.String(32), nullable=False),
        sa.Column("input_snapshot_hash", sa.String(64), nullable=False),
        sa.Column("input_snapshot_json", postgresql.JSONB(), nullable=False),
        sa.Column("engine_provenance_json", postgresql.JSONB(), nullable=False),
        sa.Column("runtime_provenance_json", postgresql.JSONB(), nullable=False),
        sa.Column("mass_balance_relative_error", sa.Float()),
        sa.Column("approved_by", sa.String(128)),
        sa.Column("approved_at", sa.DateTime(timezone=True)),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint(
            "model_state IN ('DRAFT','QA_PASSED','CALIBRATED','VALIDATED','PRODUCTION_APPROVED')",
            name="ck_hydraulic_production_run_model_state",
        ),
        sa.ForeignKeyConstraint(
            ["dataset_version_id"], ["dataset_version.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["case_id"], ["simulation_case.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["task_id"], ["simulation_task.id"], ondelete="RESTRICT"
        ),
        sa.UniqueConstraint("run_code", name="uq_hydraulic_production_run_code"),
        schema="hydraulic",
    )
    op.create_index(
        "ix_hydraulic_production_run_case",
        "production_run",
        ["dataset_version_id", "case_id"],
        schema="hydraulic",
    )

    op.create_table(
        "calibration_run",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("production_run_id", sa.Integer(), nullable=False),
        sa.Column("run_code", sa.String(64), nullable=False),
        sa.Column("dataset_version_id", sa.Integer(), nullable=False),
        sa.Column("case_id", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("calibration_dataset_json", postgresql.JSONB(), nullable=False),
        sa.Column("parameter_groups_json", postgresql.JSONB(), nullable=False),
        sa.Column("candidates_json", postgresql.JSONB(), nullable=False),
        sa.Column("objective_json", postgresql.JSONB(), nullable=False),
        sa.Column("selected_candidate_id", sa.String(128)),
        sa.Column("accepted_by", sa.String(128)),
        sa.Column("accepted_at", sa.DateTime(timezone=True)),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint(
            "status IN ('planned','queued','running','completed','failed','cancelled','accepted')",
            name="ck_hydraulic_calibration_run_status",
        ),
        sa.ForeignKeyConstraint(
            ["production_run_id"],
            ["hydraulic.production_run.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["dataset_version_id"], ["dataset_version.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["case_id"], ["simulation_case.id"], ondelete="RESTRICT"
        ),
        sa.UniqueConstraint("run_code", name="uq_hydraulic_calibration_run_code"),
        schema="hydraulic",
    )
    op.create_index(
        "ix_hydraulic_calibration_run_case",
        "calibration_run",
        ["dataset_version_id", "case_id"],
        schema="hydraulic",
    )

    op.create_table(
        "model_validation_assessment",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("production_run_id", sa.Integer(), nullable=False),
        sa.Column("validation_code", sa.String(64), nullable=False),
        sa.Column("dataset_version_id", sa.Integer(), nullable=False),
        sa.Column("case_id", sa.Integer(), nullable=False),
        sa.Column("calibration_run_id", sa.Integer()),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("validation_dataset_json", postgresql.JSONB(), nullable=False),
        sa.Column("independence_json", postgresql.JSONB(), nullable=False),
        sa.Column("criteria_json", postgresql.JSONB(), nullable=False),
        sa.Column("metrics_json", postgresql.JSONB(), nullable=False),
        sa.Column("evaluation_json", postgresql.JSONB(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint(
            "status IN ('planned','running','passed','failed','data_blocked')",
            name="ck_hydraulic_model_validation_status",
        ),
        sa.ForeignKeyConstraint(
            ["production_run_id"],
            ["hydraulic.production_run.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["dataset_version_id"], ["dataset_version.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["case_id"], ["simulation_case.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["calibration_run_id"],
            ["hydraulic.calibration_run.id"],
            ondelete="SET NULL",
        ),
        sa.UniqueConstraint(
            "validation_code", name="uq_hydraulic_model_validation_code"
        ),
        schema="hydraulic",
    )
    op.create_index(
        "ix_hydraulic_model_validation_case",
        "model_validation_assessment",
        ["dataset_version_id", "case_id"],
        schema="hydraulic",
    )

    op.create_table(
        "result_product",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("product_code", sa.String(64), nullable=False),
        sa.Column("production_run_id", sa.Integer(), nullable=False),
        sa.Column("schema_version", sa.String(32), nullable=False),
        sa.Column("product_hash", sa.String(64), nullable=False),
        sa.Column("payload_json", postgresql.JSONB(), nullable=False),
        sa.Column(
            "generated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.ForeignKeyConstraint(
            ["production_run_id"],
            ["hydraulic.production_run.id"],
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint(
            "product_code", name="uq_hydraulic_result_product_code"
        ),
        schema="hydraulic",
    )
    op.create_index(
        "ix_hydraulic_result_product_run",
        "result_product",
        ["production_run_id"],
        schema="hydraulic",
    )

    op.create_table(
        "production_audit_event",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("dataset_version_id", sa.Integer(), nullable=False),
        sa.Column("action", sa.String(32), nullable=False),
        sa.Column("actor", sa.String(128), nullable=False),
        sa.Column("entity_type", sa.String(64), nullable=False),
        sa.Column("entity_id", sa.String(128), nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("details_json", postgresql.JSONB(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint(
            "action IN ('IMPORT','RUN_CREATION','QA_OVERRIDE','PARAMETER_PROMOTION',"
            "'CALIBRATION_ACCEPTANCE',"
            "'VALIDATION_ACCEPTANCE','PRODUCTION_APPROVAL','EXPORT')",
            name="ck_hydraulic_production_audit_action",
        ),
        sa.ForeignKeyConstraint(
            ["dataset_version_id"], ["dataset_version.id"], ondelete="RESTRICT"
        ),
        schema="hydraulic",
    )
    op.create_index(
        "ix_hydraulic_production_audit_entity",
        "production_audit_event",
        ["entity_type", "entity_id"],
        schema="hydraulic",
    )
    _grant_runtime_roles()


def _grant_runtime_roles() -> None:
    """Apply the existing least-privilege role policy to the new evidence tables."""

    mutable_table_list = (
        "hydraulic.import_mapping_profile, hydraulic.observation_series, "
        "hydraulic.external_result, hydraulic.production_run, "
        "hydraulic.calibration_run, hydraulic.model_validation_assessment, "
        "hydraulic.result_product"
    )
    readable_table_list = f"{mutable_table_list}, hydraulic.production_audit_event"
    op.execute(
        f"""
        DO $$
        BEGIN
          IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'dayu_backend') THEN
            GRANT SELECT, INSERT, UPDATE, DELETE ON {mutable_table_list} TO dayu_backend;
            GRANT SELECT, INSERT ON hydraulic.production_audit_event TO dayu_backend;
            GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA hydraulic TO dayu_backend;
          END IF;
          IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'dayu_qgis_reviewer') THEN
            GRANT SELECT ON {readable_table_list} TO dayu_qgis_reviewer;
          END IF;
        END $$
        """
    )


def downgrade() -> None:
    """Remove only Production-04 workflow records in reverse dependency order."""

    op.drop_table("production_audit_event", schema="hydraulic")
    op.drop_table("result_product", schema="hydraulic")
    op.drop_table("model_validation_assessment", schema="hydraulic")
    op.drop_table("calibration_run", schema="hydraulic")
    op.drop_table("production_run", schema="hydraulic")
    op.drop_table("external_result", schema="hydraulic")
    op.drop_table("observation_series", schema="hydraulic")
    op.drop_table("import_mapping_profile", schema="hydraulic")
