"""Add Phase 5 optimization task, candidate and Pareto result tables.

Revision ID: 20260812_0006
Revises: 20260812_0005
Create Date: 2026-08-12
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "20260812_0006"
down_revision: str | None = "20260812_0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create reproducible optimization lifecycle tables and indexes."""

    op.create_table(
        "optimization_task",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("algorithm", sa.String(32), nullable=False, server_default="pso"),
        sa.Column("status", sa.String(16), nullable=False, server_default="pending"),
        sa.Column("dataset_version_id", sa.Integer(), sa.ForeignKey("dataset_version.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("simulation_case_id", sa.Integer(), sa.ForeignKey("simulation_case.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("objective_config", sa.JSON(), nullable=False),
        sa.Column("algorithm_config", sa.JSON(), nullable=False),
        sa.Column("input_snapshot", sa.JSON(), nullable=False),
        sa.Column("input_snapshot_hash", sa.String(64), nullable=False),
        sa.Column("algorithm_version", sa.String(64), nullable=False),
        sa.Column("progress", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("current_generation", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("best_score", sa.Float()),
        sa.Column("queue_job_id", sa.String(128)),
        sa.Column("worker_id", sa.String(128)),
        sa.Column("cancel_requested", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("converged", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("error_message", sa.Text()),
        sa.Column("created_time", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("start_time", sa.DateTime(timezone=True)),
        sa.Column("end_time", sa.DateTime(timezone=True)),
        sa.CheckConstraint("status IN ('pending', 'running', 'success', 'failed', 'cancelled')", name="ck_optimization_task_status"),
        sa.CheckConstraint("progress BETWEEN 0 AND 100", name="ck_optimization_task_progress"),
    )
    op.create_index("ix_optimization_task_status", "optimization_task", ["status"])
    op.create_index("ix_optimization_task_dataset_version_id", "optimization_task", ["dataset_version_id"])
    op.create_table(
        "optimization_candidate",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("task_id", sa.Integer(), sa.ForeignKey("optimization_task.id", ondelete="CASCADE"), nullable=False),
        sa.Column("generation", sa.Integer(), nullable=False),
        sa.Column("candidate_index", sa.Integer(), nullable=False),
        sa.Column("dispatch_plan", sa.JSON(), nullable=False),
        sa.Column("score", sa.Float()),
        sa.Column("objective_values", sa.JSON()),
        sa.Column("metrics", sa.JSON()),
        sa.Column("valid", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("constraint_reasons", sa.JSON(), nullable=False),
        sa.Column("simulation_task_id", sa.Integer(), sa.ForeignKey("simulation_task.id", ondelete="SET NULL")),
        sa.Column("created_time", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("task_id", "generation", "candidate_index", name="uq_optimization_candidate_slot"),
    )
    op.create_index("ix_optimization_candidate_task_id", "optimization_candidate", ["task_id"])
    op.create_index("ix_optimization_candidate_simulation_task_id", "optimization_candidate", ["simulation_task_id"])
    op.create_table(
        "optimization_result",
        sa.Column("candidate_id", sa.Integer(), sa.ForeignKey("optimization_candidate.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("task_id", sa.Integer(), sa.ForeignKey("optimization_task.id", ondelete="CASCADE"), nullable=False),
        sa.Column("pareto_level", sa.Integer(), nullable=False),
        sa.Column("rank", sa.Integer(), nullable=False),
        sa.Column("recommendation_status", sa.String(16), nullable=False),
        sa.Column("explanation", sa.JSON(), nullable=False),
        sa.CheckConstraint("recommendation_status IN ('recommended', 'pareto', 'alternative', 'rejected')", name="ck_optimization_result_recommendation_status"),
    )
    op.create_index("ix_optimization_result_task_level", "optimization_result", ["task_id", "pareto_level"])


def downgrade() -> None:
    """Remove Phase 5 optimization persistence in dependency order."""

    op.drop_table("optimization_result")
    op.drop_table("optimization_candidate")
    op.drop_table("optimization_task")
