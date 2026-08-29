"""Add the native v4 task, result, artifact, and shadow persistence boundary.

Revision ID: 20260828_0020
Revises: 20260818_0019
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "20260828_0020"
down_revision: str | None = "20260818_0019"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _add_authoritative_v4_bindings() -> None:
    """Add nullable D2 bindings so every legacy row remains valid and unchanged."""

    op.add_column("simulation_case", sa.Column("v4_configuration", sa.JSON(), nullable=True))
    op.add_column("boundary_condition", sa.Column("hydraulic_node_id", sa.Integer(), nullable=True))
    op.create_foreign_key(
        "fk_boundary_d2_hydraulic_node_version",
        "boundary_condition",
        "node",
        ["hydraulic_node_id", "dataset_version_id"],
        ["id", "dataset_version_id"],
        referent_schema="hydraulic",
        ondelete="RESTRICT",
    )
    for name in ("hydraulic_upstream_section_id", "hydraulic_downstream_section_id"):
        op.add_column("gate", sa.Column(name, sa.Integer(), nullable=True))
    op.create_foreign_key(
        "fk_gate_d2_upstream_section_version",
        "gate",
        "cross_section",
        ["hydraulic_upstream_section_id", "dataset_version_id"],
        ["id", "dataset_version_id"],
        referent_schema="hydraulic",
        ondelete="RESTRICT",
    )
    op.create_foreign_key(
        "fk_gate_d2_downstream_section_version",
        "gate",
        "cross_section",
        ["hydraulic_downstream_section_id", "dataset_version_id"],
        ["id", "dataset_version_id"],
        referent_schema="hydraulic",
        ondelete="RESTRICT",
    )
    op.add_column("pump", sa.Column("hydraulic_section_id", sa.Integer(), nullable=True))
    op.create_foreign_key(
        "fk_pump_d2_section_version",
        "pump",
        "cross_section",
        ["hydraulic_section_id", "dataset_version_id"],
        ["id", "dataset_version_id"],
        referent_schema="hydraulic",
        ondelete="RESTRICT",
    )
    for name, type_ in (
        ("curve_policy_id", sa.String(length=64)),
        ("curve_unit", sa.String(length=32)),
        ("curve_source_revision", sa.String(length=64)),
        ("curve_hash", sa.String(length=64)),
        ("system_loss", sa.JSON()),
        ("outlet_stage", sa.JSON()),
    ):
        op.add_column("pump", sa.Column(name, type_, nullable=True))


def _add_task_columns() -> None:
    """Add solver/provenance/lifecycle fields while preserving existing task rows."""

    op.create_table(
        "simulation_task_group",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("case_id", sa.Integer(), nullable=False),
        sa.Column("group_type", sa.String(length=16), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False, server_default="pending"),
        sa.Column("created_time", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("group_type IN ('shadow')", name="ck_simulation_task_group_type"),
        sa.ForeignKeyConstraint(["case_id"], ["simulation_case.id"], ondelete="RESTRICT"),
    )
    op.create_index("ix_simulation_task_group_case_id", "simulation_task_group", ["case_id"])

    nullable_strings = (
        ("solver_id", 96),
        ("capability_id", 96),
        ("runtime_adapter_id", 96),
        ("result_schema_version", 48),
        ("execution_mode", 16),
        ("execution_phase", 32),
        ("runtime_projection_hash", 64),
        ("mesh_hash", 64),
        ("solver_policy_hash", 64),
        ("validation_policy_hash", 64),
        ("registry_hash", 64),
        ("artifact_status", 16),
        ("group_role", 16),
    )
    for name, length in nullable_strings:
        op.add_column("simulation_task", sa.Column(name, sa.String(length=length), nullable=True))
    op.add_column("simulation_task", sa.Column("comparison_group_id", sa.Integer(), nullable=True))
    op.create_foreign_key(
        "fk_simulation_task_comparison_group",
        "simulation_task",
        "simulation_task_group",
        ["comparison_group_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.add_column("simulation_task", sa.Column("last_event", sa.JSON(), nullable=True))
    for name in (
        "accepted_step_count",
        "cfl_reduction_count",
        "positivity_retry_count",
        "event_refinement_count",
        "gate_solver_retry_count",
        "pump_solver_retry_count",
        "minimum_dt_failure_count",
    ):
        op.add_column(
            "simulation_task",
            sa.Column(name, sa.Integer(), nullable=False, server_default="0"),
        )
    op.create_check_constraint(
        "ck_simulation_task_execution_mode",
        "simulation_task",
        "execution_mode IS NULL OR execution_mode IN ('validation','shadow')",
    )
    op.create_check_constraint(
        "ck_simulation_task_group_role",
        "simulation_task",
        "group_role IS NULL OR group_role IN ('legacy-v3','native-v4')",
    )
    op.create_check_constraint(
        "ck_simulation_task_artifact_status",
        "simulation_task",
        "artifact_status IS NULL OR artifact_status IN "
        "('none','preparing','prepared','published','failed')",
    )


def _create_v4_result_tables() -> None:
    """Create authoritative v4 output tables and deterministic artifact metadata."""

    op.create_table(
        "hydraulic_task_section_result",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("task_id", sa.Integer(), nullable=False),
        sa.Column("dataset_version_id", sa.Integer(), nullable=False),
        sa.Column("hydraulic_cross_section_id", sa.Integer(), nullable=False),
        sa.Column("section_code", sa.String(length=64), nullable=False),
        sa.Column("branch_id", sa.Integer(), nullable=False),
        sa.Column("chainage_m", sa.Float(), nullable=False),
        sa.Column("time_seconds", sa.Float(), nullable=False),
        sa.Column("water_level_m", sa.Float(), nullable=False),
        sa.Column("flow_m3s", sa.Float(), nullable=False),
        sa.Column("velocity_m_s", sa.Float(), nullable=False),
        sa.Column("control_volume_m3", sa.Float(), nullable=False),
        sa.ForeignKeyConstraint(["task_id"], ["simulation_task.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["dataset_version_id"], ["dataset_version.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["hydraulic_cross_section_id", "dataset_version_id"],
            ["hydraulic.cross_section.id", "hydraulic.cross_section.dataset_version_id"],
            name="fk_d2_section_result_section_version",
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint(
            "task_id", "hydraulic_cross_section_id", "time_seconds",
            name="uq_d2_section_result_task_section_time",
        ),
    )
    op.create_index(
        "ix_d2_section_result_task_time",
        "hydraulic_task_section_result",
        ["task_id", "time_seconds"],
    )

    op.create_table(
        "hydraulic_task_gate_result",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("task_id", sa.Integer(), nullable=False),
        sa.Column("dataset_version_id", sa.Integer(), nullable=False),
        sa.Column("canonical_gate_id", sa.Integer(), nullable=False),
        sa.Column("time_seconds", sa.Float(), nullable=False),
        sa.Column("opening_m", sa.Float(), nullable=False),
        sa.Column("flow_m3s", sa.Float(), nullable=False),
        sa.Column("upstream_stage_m", sa.Float(), nullable=False),
        sa.Column("downstream_stage_m", sa.Float(), nullable=False),
        sa.Column("head_loss_m", sa.Float(), nullable=True),
        sa.Column("reaction_force_per_density", sa.Float(), nullable=True),
        sa.Column("regime", sa.String(length=48), nullable=True),
        sa.ForeignKeyConstraint(["task_id"], ["simulation_task.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["dataset_version_id"], ["dataset_version.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["canonical_gate_id"], ["gate.id"], ondelete="RESTRICT"),
        sa.UniqueConstraint(
            "task_id", "canonical_gate_id", "time_seconds",
            name="uq_d2_gate_result_task_gate_time",
        ),
    )
    op.create_index("ix_d2_gate_result_task_time", "hydraulic_task_gate_result", ["task_id", "time_seconds"])

    op.create_table(
        "hydraulic_task_pump_result",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("task_id", sa.Integer(), nullable=False),
        sa.Column("dataset_version_id", sa.Integer(), nullable=False),
        sa.Column("canonical_pump_id", sa.Integer(), nullable=False),
        sa.Column("time_seconds", sa.Float(), nullable=False),
        sa.Column("control_state", sa.String(length=16), nullable=False),
        sa.Column("running_units", sa.Integer(), nullable=False),
        sa.Column("flow_m3s", sa.Float(), nullable=False),
        sa.Column("source_stage_m", sa.Float(), nullable=False),
        sa.Column("outlet_stage_m", sa.Float(), nullable=False),
        sa.Column("pump_head_m", sa.Float(), nullable=False),
        sa.Column("system_head_m", sa.Float(), nullable=False),
        sa.Column("efficiency", sa.Float(), nullable=False),
        sa.Column("input_power_kw", sa.Float(), nullable=False),
        sa.Column("cumulative_energy_kwh", sa.Float(), nullable=False),
        sa.Column("iterations", sa.Integer(), nullable=False),
        sa.Column("regime", sa.String(length=48), nullable=True),
        sa.ForeignKeyConstraint(["task_id"], ["simulation_task.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["dataset_version_id"], ["dataset_version.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["canonical_pump_id"], ["pump.id"], ondelete="RESTRICT"),
        sa.UniqueConstraint(
            "task_id", "canonical_pump_id", "time_seconds",
            name="uq_d2_pump_result_task_pump_time",
        ),
    )
    op.create_index("ix_d2_pump_result_task_time", "hydraulic_task_pump_result", ["task_id", "time_seconds"])

    op.create_table(
        "hydraulic_task_control_event",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("task_id", sa.Integer(), nullable=False),
        sa.Column("time_seconds", sa.Float(), nullable=False),
        sa.Column("structure_type", sa.String(length=16), nullable=False),
        sa.Column("canonical_structure_id", sa.Integer(), nullable=False),
        sa.Column("event_type", sa.String(length=32), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("pre_state_json", sa.JSON(), nullable=True),
        sa.Column("post_command_json", sa.JSON(), nullable=True),
        sa.ForeignKeyConstraint(["task_id"], ["simulation_task.id"], ondelete="CASCADE"),
        sa.UniqueConstraint(
            "task_id", "time_seconds", "structure_type", "canonical_structure_id", "event_type",
            name="uq_d2_control_event_identity",
        ),
    )
    op.create_index("ix_d2_control_event_task_time", "hydraulic_task_control_event", ["task_id", "time_seconds"])

    op.create_table(
        "hydraulic_task_artifact",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("task_id", sa.Integer(), nullable=False),
        sa.Column("artifact_type", sa.String(length=48), nullable=False),
        sa.Column("storage_key", sa.Text(), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("record_count", sa.Integer(), nullable=False),
        sa.Column("media_type", sa.String(length=96), nullable=False),
        sa.Column("schema_version", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("metadata_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("created_time", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("published_time", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("status IN ('prepared','published','failed')", name="ck_d2_artifact_status"),
        sa.CheckConstraint("length(sha256) = 64", name="ck_d2_artifact_sha256"),
        sa.CheckConstraint("size_bytes >= 0", name="ck_d2_artifact_size"),
        sa.CheckConstraint("record_count >= 0", name="ck_d2_artifact_record_count"),
        sa.ForeignKeyConstraint(["task_id"], ["simulation_task.id"], ondelete="CASCADE"),
        sa.UniqueConstraint(
            "task_id", "artifact_type", "schema_version",
            name="uq_d2_artifact_task_type_schema",
        ),
    )
    op.create_index("ix_d2_artifact_task_status", "hydraulic_task_artifact", ["task_id", "status"])


def upgrade() -> None:
    """Install the additive D2 platform boundary without touching legacy values."""

    _add_authoritative_v4_bindings()
    _add_task_columns()
    _create_v4_result_tables()


def downgrade() -> None:
    """Remove D2-only structures while leaving all legacy task/result data intact."""

    for table in (
        "hydraulic_task_artifact",
        "hydraulic_task_control_event",
        "hydraulic_task_pump_result",
        "hydraulic_task_gate_result",
        "hydraulic_task_section_result",
    ):
        op.drop_table(table)

    for constraint in (
        "ck_simulation_task_artifact_status",
        "ck_simulation_task_group_role",
        "ck_simulation_task_execution_mode",
    ):
        op.drop_constraint(constraint, "simulation_task", type_="check")
    op.drop_constraint(
        "fk_simulation_task_comparison_group", "simulation_task", type_="foreignkey"
    )
    for name in (
        "minimum_dt_failure_count",
        "pump_solver_retry_count",
        "gate_solver_retry_count",
        "event_refinement_count",
        "positivity_retry_count",
        "cfl_reduction_count",
        "accepted_step_count",
        "last_event",
        "group_role",
        "comparison_group_id",
        "artifact_status",
        "registry_hash",
        "validation_policy_hash",
        "solver_policy_hash",
        "mesh_hash",
        "runtime_projection_hash",
        "execution_phase",
        "execution_mode",
        "result_schema_version",
        "runtime_adapter_id",
        "capability_id",
        "solver_id",
    ):
        op.drop_column("simulation_task", name)
    op.drop_index("ix_simulation_task_group_case_id", table_name="simulation_task_group")
    op.drop_table("simulation_task_group")

    op.drop_constraint("fk_pump_d2_section_version", "pump", type_="foreignkey")
    for name in (
        "outlet_stage",
        "system_loss",
        "curve_hash",
        "curve_source_revision",
        "curve_unit",
        "curve_policy_id",
        "hydraulic_section_id",
    ):
        op.drop_column("pump", name)
    op.drop_constraint("fk_gate_d2_downstream_section_version", "gate", type_="foreignkey")
    op.drop_constraint("fk_gate_d2_upstream_section_version", "gate", type_="foreignkey")
    op.drop_column("gate", "hydraulic_downstream_section_id")
    op.drop_column("gate", "hydraulic_upstream_section_id")
    op.drop_constraint(
        "fk_boundary_d2_hydraulic_node_version", "boundary_condition", type_="foreignkey"
    )
    op.drop_column("boundary_condition", "hydraulic_node_id")
    op.drop_column("simulation_case", "v4_configuration")

