"""Persist exact native Pump control and hydraulic audit fields.

Revision ID: 20260903_0029
Revises: 20260902_0028
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "20260903_0029"
down_revision: str | None = "20260902_0028"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add nullable audit fields without rewriting existing structure results."""

    op.add_column("structure_result", sa.Column("resolved_value", sa.Float(), nullable=True))
    op.add_column(
        "structure_result",
        sa.Column("native_applied_capacity", sa.Float(), nullable=True),
    )
    op.add_column(
        "structure_result", sa.Column("actual_discharge", sa.Float(), nullable=True)
    )
    op.add_column(
        "structure_result", sa.Column("intake_water_level", sa.Float(), nullable=True)
    )
    op.add_column(
        "structure_result", sa.Column("outlet_water_level", sa.Float(), nullable=True)
    )
    op.add_column(
        "structure_result",
        sa.Column("structure_head_difference", sa.Float(), nullable=True),
    )
    op.add_column("structure_result", sa.Column("pump_head", sa.Float(), nullable=True))
    op.add_column(
        "structure_result",
        sa.Column("pump_reduction_factor", sa.Float(), nullable=True),
    )
    op.add_column(
        "structure_result", sa.Column("pump_actual_stage", sa.Integer(), nullable=True)
    )


def downgrade() -> None:
    """Remove only Phase 07 Pump audit fields."""

    op.drop_column("structure_result", "pump_actual_stage")
    op.drop_column("structure_result", "pump_reduction_factor")
    op.drop_column("structure_result", "pump_head")
    op.drop_column("structure_result", "structure_head_difference")
    op.drop_column("structure_result", "outlet_water_level")
    op.drop_column("structure_result", "intake_water_level")
    op.drop_column("structure_result", "actual_discharge")
    op.drop_column("structure_result", "native_applied_capacity")
    op.drop_column("structure_result", "resolved_value")
