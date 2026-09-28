"""Freeze explicit Engine identity and execution class on hydraulic Tasks.

Revision ID: 20260924_0036
Revises: 20260910_0035
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "20260924_0036"
down_revision: str | None = "20260910_0035"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add identity fields and deterministically classify only known legacy routes."""

    op.add_column("simulation_task", sa.Column("engine_id", sa.String(length=64)))
    op.add_column(
        "simulation_task", sa.Column("execution_class", sa.String(length=16))
    )
    op.execute(
        """
        UPDATE simulation_task
        SET engine_id = CASE
            WHEN task_kind = 'controlled_hydraulic_preview'
                 AND solver_id = 'd-flow-fm-DIMRset_2026.02'
                 AND runtime_adapter_id = 'dayu-dflow-fm-adapter-v1'
              THEN 'd-flow-fm'
            WHEN input_schema_version = 'dayu.hydraulic-1d.input.v1'
                 AND solver_id = 'mascaret-v9.1.1'
                 AND runtime_adapter_id = 'dayu-mascaret-adapter-v2'
              THEN 'mascaret'
            ELSE 'legacy-unresolved'
        END,
        execution_class = CASE
            WHEN task_kind = 'controlled_hydraulic_preview'
                 AND solver_id = 'd-flow-fm-DIMRset_2026.02'
                 AND runtime_adapter_id = 'dayu-dflow-fm-adapter-v1'
              THEN 'synthetic'
            WHEN input_schema_version = 'dayu.hydraulic-1d.input.v1'
                 AND solver_id = 'mascaret-v9.1.1'
                 AND runtime_adapter_id = 'dayu-mascaret-adapter-v2'
              THEN 'production'
            ELSE 'legacy'
        END
        """
    )
    op.alter_column("simulation_task", "engine_id", nullable=False)
    op.alter_column("simulation_task", "execution_class", nullable=False)
    op.create_check_constraint(
        "ck_simulation_task_execution_class",
        "simulation_task",
        "execution_class IN ('production','pilot','synthetic','legacy')",
    )
    op.create_index("ix_simulation_task_engine_id", "simulation_task", ["engine_id"])


def downgrade() -> None:
    """Remove only the additive routing metadata, preserving Task/result history."""

    op.drop_index("ix_simulation_task_engine_id", table_name="simulation_task")
    op.drop_constraint(
        "ck_simulation_task_execution_class",
        "simulation_task",
        type_="check",
    )
    op.drop_column("simulation_task", "execution_class")
    op.drop_column("simulation_task", "engine_id")
