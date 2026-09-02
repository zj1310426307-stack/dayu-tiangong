"""Add immutable controlled-hydraulic preview identities.

Revision ID: 20260902_0028
Revises: 20260902_0027
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "20260902_0028"
down_revision: str | None = "20260902_0027"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Extend existing plan, task, and run tables without rewriting v2 snapshots."""

    op.add_column(
        "dispatch_plan",
        sa.Column(
            "snapshot_target",
            sa.String(length=16),
            nullable=False,
            server_default="static_v2",
        ),
    )
    op.add_column(
        "dispatch_plan",
        sa.Column("cloned_from_plan_id", sa.Integer(), nullable=True),
    )
    op.create_check_constraint(
        "ck_dispatch_plan_snapshot_target",
        "dispatch_plan",
        "snapshot_target IN ('static_v2', 'hydraulic_v3')",
    )
    op.create_foreign_key(
        "fk_dispatch_plan_cloned_from_plan",
        "dispatch_plan",
        "dispatch_plan",
        ["cloned_from_plan_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_index(
        "ix_dispatch_plan_cloned_from_plan_id",
        "dispatch_plan",
        ["cloned_from_plan_id"],
    )

    op.add_column(
        "simulation_task",
        sa.Column(
            "task_kind",
            sa.String(length=32),
            nullable=False,
            server_default="standard_1d",
        ),
    )
    op.add_column(
        "simulation_task",
        sa.Column("evidence_class", sa.String(length=48), nullable=True),
    )
    op.create_check_constraint(
        "ck_simulation_task_kind",
        "simulation_task",
        "task_kind IN ('standard_1d','controlled_hydraulic_preview')",
    )

    op.add_column(
        "dispatch_run",
        sa.Column(
            "run_mode",
            sa.String(length=24),
            nullable=False,
            server_default="legacy",
        ),
    )
    op.add_column(
        "dispatch_run",
        sa.Column("evidence_class", sa.String(length=48), nullable=True),
    )
    op.add_column(
        "dispatch_run",
        sa.Column("engine_id", sa.String(length=64), nullable=True),
    )
    op.add_column(
        "dispatch_run",
        sa.Column("control_runtime", sa.String(length=64), nullable=True),
    )
    op.add_column(
        "dispatch_run",
        sa.Column("compiled_artifact_hash", sa.String(length=64), nullable=True),
    )
    op.add_column(
        "dispatch_run",
        sa.Column("runtime_provenance", sa.JSON(), nullable=True),
    )
    op.add_column(
        "dispatch_run",
        sa.Column("result_contract", sa.JSON(), nullable=True),
    )
    op.create_check_constraint(
        "ck_dispatch_run_mode",
        "dispatch_run",
        "run_mode IN ('legacy','hydraulic_preview','production')",
    )


def downgrade() -> None:
    """Remove only Development Hydraulic Preview metadata."""

    op.drop_constraint("ck_dispatch_run_mode", "dispatch_run", type_="check")
    op.drop_column("dispatch_run", "result_contract")
    op.drop_column("dispatch_run", "runtime_provenance")
    op.drop_column("dispatch_run", "compiled_artifact_hash")
    op.drop_column("dispatch_run", "control_runtime")
    op.drop_column("dispatch_run", "engine_id")
    op.drop_column("dispatch_run", "evidence_class")
    op.drop_column("dispatch_run", "run_mode")

    op.drop_constraint("ck_simulation_task_kind", "simulation_task", type_="check")
    op.drop_column("simulation_task", "evidence_class")
    op.drop_column("simulation_task", "task_kind")

    op.drop_index("ix_dispatch_plan_cloned_from_plan_id", table_name="dispatch_plan")
    op.drop_constraint(
        "fk_dispatch_plan_cloned_from_plan", "dispatch_plan", type_="foreignkey"
    )
    op.drop_constraint(
        "ck_dispatch_plan_snapshot_target", "dispatch_plan", type_="check"
    )
    op.drop_column("dispatch_plan", "cloned_from_plan_id")
    op.drop_column("dispatch_plan", "snapshot_target")
