"""Bind new dispatch actions directly to unified hydraulic structures.

Revision ID: 20260910_0035
Revises: 20260909_0034
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "20260910_0035"
down_revision: str | None = "20260909_0034"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "dispatch_action",
        sa.Column("hydraulic_structure_id", sa.Integer(), nullable=True),
    )
    op.create_foreign_key(
        "fk_dispatch_action_hydraulic_structure",
        "dispatch_action",
        "structure",
        ["hydraulic_structure_id"],
        ["id"],
        referent_schema="hydraulic",
        ondelete="RESTRICT",
    )
    op.drop_constraint("ck_dispatch_action_structure_command_asset", "dispatch_action", type_="check")
    op.drop_constraint("ck_dispatch_action_single_asset", "dispatch_action", type_="check")
    op.create_check_constraint(
        "ck_dispatch_action_structure_command_asset",
        "dispatch_action",
        "(structure_type = 'gate' AND (gate_id IS NOT NULL OR hydraulic_structure_id IS NOT NULL) "
        "AND pump_id IS NULL AND command_type IN ('gate_opening_m', 'gate_opening_ratio')) OR "
        "(structure_type = 'pump' AND (pump_id IS NOT NULL OR hydraulic_structure_id IS NOT NULL) "
        "AND gate_id IS NULL AND command_type IN ('pump_enabled', 'pump_unit_count', 'pump_target_flow'))",
    )
    op.create_check_constraint(
        "ck_dispatch_action_single_asset",
        "dispatch_action",
        "(gate_id IS NOT NULL AND pump_id IS NULL AND hydraulic_structure_id IS NULL) OR "
        "(gate_id IS NULL AND pump_id IS NOT NULL AND hydraulic_structure_id IS NULL) OR "
        "(gate_id IS NULL AND pump_id IS NULL AND hydraulic_structure_id IS NOT NULL)",
    )
    op.create_index(
        "uq_dispatch_action_hydraulic_structure_time",
        "dispatch_action",
        ["plan_id", "time_seconds", "hydraulic_structure_id"],
        unique=True,
        postgresql_where=sa.text("hydraulic_structure_id IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("uq_dispatch_action_hydraulic_structure_time", table_name="dispatch_action")
    op.drop_constraint("ck_dispatch_action_structure_command_asset", "dispatch_action", type_="check")
    op.drop_constraint("ck_dispatch_action_single_asset", "dispatch_action", type_="check")
    op.create_check_constraint(
        "ck_dispatch_action_structure_command_asset", "dispatch_action",
        "(structure_type = 'gate' AND gate_id IS NOT NULL AND pump_id IS NULL AND command_type IN ('gate_opening_m', 'gate_opening_ratio')) OR "
        "(structure_type = 'pump' AND pump_id IS NOT NULL AND gate_id IS NULL AND command_type IN ('pump_enabled', 'pump_unit_count', 'pump_target_flow'))",
    )
    op.create_check_constraint(
        "ck_dispatch_action_single_asset", "dispatch_action",
        "(gate_id IS NOT NULL AND pump_id IS NULL) OR (gate_id IS NULL AND pump_id IS NOT NULL)",
    )
    op.drop_constraint("fk_dispatch_action_hydraulic_structure", "dispatch_action", type_="foreignkey")
    op.drop_column("dispatch_action", "hydraulic_structure_id")
