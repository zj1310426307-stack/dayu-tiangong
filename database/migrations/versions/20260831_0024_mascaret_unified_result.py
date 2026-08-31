"""Add MASCARET-neutral case configuration and unified Section result fields.

Revision ID: 20260831_0024
Revises: 20260829_0023
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "20260831_0024"
down_revision: str | None = "20260829_0023"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add platform fields while preserving historical task and result identities."""

    op.add_column(
        "boundary_condition",
        sa.Column("branch_id", sa.Integer(), nullable=True),
    )
    op.add_column(
        "boundary_condition",
        sa.Column("chainage_m", sa.Float(), nullable=True),
    )
    op.execute(
        sa.text(
            "UPDATE boundary_condition SET boundary_type = CASE "
            "WHEN boundary_type = 'upstream_flow' THEN 'upstream_discharge' "
            "WHEN boundary_type = 'downstream_stage' THEN 'downstream_water_level' "
            "WHEN boundary_type = 'lateral_flow' THEN 'lateral_inflow' "
            "ELSE boundary_type END "
            "WHERE boundary_type IN "
            "('upstream_flow', 'downstream_stage', 'lateral_flow')"
        )
    )
    # Older lateral rows stored their location inside the series JSON. Copy only
    # values that resolve to a Branch in the same Dataset Version; unresolved
    # historical rows remain readable but intentionally fail Standard 1D readiness.
    op.execute(
        sa.text(
            "UPDATE boundary_condition AS boundary "
            "SET branch_id = branch.id, "
            "chainage_m = (boundary.\"values\" ->> 'chainage_m')::double precision "
            "FROM hydraulic.branch AS branch "
            "WHERE boundary.boundary_type = 'lateral_inflow' "
            "AND boundary.branch_id IS NULL "
            "AND boundary.\"values\" ->> 'branch_id' ~ '^[1-9][0-9]*$' "
            "AND boundary.\"values\" ->> 'chainage_m' "
            "~ '^[0-9]+([.][0-9]+)?$' "
            "AND branch.id = (boundary.\"values\" ->> 'branch_id')::integer "
            "AND branch.dataset_version_id = boundary.dataset_version_id "
            "AND (boundary.\"values\" ->> 'chainage_m')::double precision "
            "BETWEEN branch.chainage_start_m AND branch.chainage_end_m"
        )
    )
    op.create_foreign_key(
        "fk_boundary_hydraulic_branch_version",
        "boundary_condition",
        "branch",
        ["branch_id", "dataset_version_id"],
        ["id", "dataset_version_id"],
        referent_schema="hydraulic",
        ondelete="RESTRICT",
    )
    op.create_check_constraint(
        "ck_boundary_condition_chainage_nonnegative",
        "boundary_condition",
        "chainage_m IS NULL OR chainage_m >= 0",
    )
    op.add_column(
        "simulation_case",
        sa.Column("hydraulic_1d_configuration", sa.JSON(), nullable=True),
    )
    for name in ("depth_m", "flow_area_m2"):
        op.add_column(
            "hydraulic_task_section_result",
            sa.Column(name, sa.Float(), nullable=True),
        )
    for name in (
        "wet_area_m2",
        "hydraulic_radius_m",
        "top_width_m",
        "froude_number",
    ):
        op.add_column(
            "hydraulic_task_section_result",
            sa.Column(name, sa.Float(), nullable=True),
        )
    op.alter_column("hydraulic_task_section_result", "control_volume_m3", nullable=True)


def downgrade() -> None:
    """Restore the historical finite-volume shape for controlled rollback only."""

    # Unified MASCARET rows have no truthful legacy control-volume value. Remove
    # them instead of fabricating one, while retaining their task audit records.
    op.execute(
        sa.text(
            "DELETE FROM hydraulic_task_section_result AS result "
            "USING simulation_task AS task "
            "WHERE result.task_id = task.id "
            "AND task.input_schema_version = 'dayu.hydraulic-1d.input.v1'"
        )
    )
    op.execute(
        sa.text(
            "UPDATE simulation_task SET status = 'failed', progress = 100, "
            "error_message = 'MASCARET_ADAPTER_SCHEMA_DOWNGRADED', "
            "queue_job_id = NULL, active_execution_token = NULL, "
            "cancel_requested = false, result_path = NULL, "
            "execution_phase = 'finalizing', "
            "end_time = COALESCE(end_time, CURRENT_TIMESTAMP) "
            "WHERE input_schema_version = 'dayu.hydraulic-1d.input.v1' "
            "AND status IN ('pending','queued','running','cancel_requested','success')"
        )
    )
    op.execute(
        "UPDATE hydraulic_task_section_result SET control_volume_m3 = 0.0 "
        "WHERE control_volume_m3 IS NULL"
    )
    op.alter_column("hydraulic_task_section_result", "control_volume_m3", nullable=False)
    for name in (
        "froude_number",
        "top_width_m",
        "hydraulic_radius_m",
        "wet_area_m2",
        "flow_area_m2",
        "depth_m",
    ):
        op.drop_column("hydraulic_task_section_result", name)
    op.drop_column("simulation_case", "hydraulic_1d_configuration")
    # Restore the historical lateral-location representation before removing
    # the authoritative columns so a controlled rollback does not lose data.
    op.execute(
        sa.text(
            "UPDATE boundary_condition SET \"values\" = "
            "(COALESCE(\"values\"::jsonb, '{}'::jsonb) || "
            "jsonb_build_object('branch_id', branch_id, 'chainage_m', chainage_m))::json "
            "WHERE boundary_type = 'lateral_inflow' "
            "AND branch_id IS NOT NULL AND chainage_m IS NOT NULL"
        )
    )
    op.drop_constraint(
        "ck_boundary_condition_chainage_nonnegative",
        "boundary_condition",
        type_="check",
    )
    op.drop_constraint(
        "fk_boundary_hydraulic_branch_version",
        "boundary_condition",
        type_="foreignkey",
    )
    op.drop_column("boundary_condition", "chainage_m")
    op.drop_column("boundary_condition", "branch_id")
    op.execute(
        sa.text(
            "UPDATE boundary_condition SET boundary_type = CASE "
            "WHEN boundary_type = 'upstream_discharge' THEN 'upstream_flow' "
            "WHEN boundary_type = 'downstream_water_level' THEN 'downstream_stage' "
            "WHEN boundary_type = 'lateral_inflow' THEN 'lateral_flow' "
            "ELSE boundary_type END "
            "WHERE boundary_type IN "
            "('upstream_discharge', 'downstream_water_level', 'lateral_inflow')"
        )
    )
