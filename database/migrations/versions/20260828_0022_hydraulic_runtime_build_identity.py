"""Add runtime build identity and bounded queued-delivery telemetry.

Revision ID: 20260828_0022
Revises: 20260828_0021
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "20260828_0022"
down_revision: str | None = "20260828_0021"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add RC2 identity without inventing verified provenance for historical rows."""

    op.add_column(
        "simulation_task",
        sa.Column("solver_build_id", sa.String(length=96), nullable=True),
    )
    op.add_column(
        "simulation_task",
        sa.Column("build_mode", sa.String(length=16), nullable=True),
    )
    op.add_column(
        "simulation_task",
        sa.Column(
            "build_verified",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )
    op.add_column(
        "simulation_task",
        sa.Column(
            "delivery_attempt_count",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
    )
    op.add_column(
        "simulation_task",
        sa.Column("last_delivery_time", sa.DateTime(timezone=True), nullable=True),
    )
    op.execute(
        """
        UPDATE simulation_task
           SET delivery_attempt_count = CASE WHEN queue_job_id IS NULL THEN 0 ELSE 1 END,
               last_delivery_time = CASE
                 WHEN status = 'queued' THEN COALESCE(queued_time, created_time)
                 ELSE NULL
               END,
               build_verified = false
        """
    )
    op.create_check_constraint(
        "ck_simulation_task_build_mode",
        "simulation_task",
        "build_mode IS NULL OR build_mode IN ('development','ci','release')",
    )
    op.drop_constraint(
        "ck_simulation_task_counters_nonnegative",
        "simulation_task",
        type_="check",
    )
    op.create_check_constraint(
        "ck_simulation_task_counters_nonnegative",
        "simulation_task",
        "retry_count >= 0 AND execution_attempt_count >= 0 "
        "AND manual_retry_count >= 0 AND infrastructure_retry_count >= 0 "
        "AND numerical_retry_count >= 0 AND delivery_attempt_count >= 0 "
        "AND accepted_step_count >= 0 AND cfl_reduction_count >= 0 "
        "AND positivity_retry_count >= 0 AND event_refinement_count >= 0 "
        "AND gate_solver_retry_count >= 0 AND pump_solver_retry_count >= 0 "
        "AND minimum_dt_failure_count >= 0",
    )
    op.create_index(
        "ix_simulation_task_queued_delivery_recovery",
        "simulation_task",
        ["status", "last_delivery_time"],
        unique=False,
    )


def downgrade() -> None:
    """Return to the RC1 schema while leaving older task identity untouched."""

    op.drop_index(
        "ix_simulation_task_queued_delivery_recovery",
        table_name="simulation_task",
    )
    op.drop_constraint(
        "ck_simulation_task_counters_nonnegative",
        "simulation_task",
        type_="check",
    )
    op.create_check_constraint(
        "ck_simulation_task_counters_nonnegative",
        "simulation_task",
        "retry_count >= 0 AND execution_attempt_count >= 0 "
        "AND manual_retry_count >= 0 AND infrastructure_retry_count >= 0 "
        "AND numerical_retry_count >= 0 AND accepted_step_count >= 0 "
        "AND cfl_reduction_count >= 0 AND positivity_retry_count >= 0 "
        "AND event_refinement_count >= 0 AND gate_solver_retry_count >= 0 "
        "AND pump_solver_retry_count >= 0 AND minimum_dt_failure_count >= 0",
    )
    op.drop_constraint(
        "ck_simulation_task_build_mode",
        "simulation_task",
        type_="check",
    )
    op.drop_column("simulation_task", "last_delivery_time")
    op.drop_column("simulation_task", "delivery_attempt_count")
    op.drop_column("simulation_task", "build_verified")
    op.drop_column("simulation_task", "build_mode")
    op.drop_column("simulation_task", "solver_build_id")
