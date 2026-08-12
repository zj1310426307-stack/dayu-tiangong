"""Add Phase 3 hydraulic tasks/results and migrate all spatial data to CGCS2000.

Revision ID: 20260812_0003
Revises: 20260811_0002
Create Date: 2026-08-12
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "20260812_0003"
down_revision: str | None = "20260811_0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


SPATIAL_COLUMNS = (
    ("river", "LINESTRING", "ix_river_geometry_gist"),
    ("river_node", "POINT", "ix_river_node_geometry_gist"),
    ("river_segment", "LINESTRING", "ix_river_segment_geometry_gist"),
    ("cross_section", "POINT", "ix_cross_section_geometry_gist"),
    ("gate", "POINT", "ix_gate_geometry_gist"),
    ("pump", "POINT", "ix_pump_geometry_gist"),
)


def _transform_spatial_columns(target_srid: int) -> None:
    """Transform existing coordinates explicitly, preserving every business row."""

    for table_name, geometry_type, index_name in SPATIAL_COLUMNS:
        op.drop_index(index_name, table_name=table_name)
        op.execute(
            sa.text(
                f"ALTER TABLE {table_name} "
                f"ALTER COLUMN geometry TYPE geometry({geometry_type}, {target_srid}) "
                f"USING ST_Transform(geometry, {target_srid})"
            )
        )
        op.create_index(
            index_name,
            table_name,
            ["geometry"],
            unique=False,
            postgresql_using="gist",
        )


def upgrade() -> None:
    """Upgrade active spatial storage to EPSG:4490 and add calculation tables."""

    _transform_spatial_columns(4490)
    op.create_table(
        "simulation_task",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("case_id", sa.Integer(), nullable=False),
        sa.Column(
            "status", sa.String(length=16), server_default="pending", nullable=False
        ),
        sa.Column("progress", sa.Integer(), server_default="0", nullable=False),
        sa.Column("config", sa.JSON(), nullable=False),
        sa.Column("diagnostics", sa.JSON(), nullable=True),
        sa.Column("result_path", sa.Text(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column(
            "created_time",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("start_time", sa.DateTime(timezone=True), nullable=True),
        sa.Column("end_time", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "status IN ('pending', 'running', 'success', 'failed')",
            name="ck_simulation_task_status",
        ),
        sa.CheckConstraint(
            "progress BETWEEN 0 AND 100", name="ck_simulation_task_progress"
        ),
        sa.ForeignKeyConstraint(
            ["case_id"],
            ["simulation_case.id"],
            name="fk_simulation_task_case_id",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_simulation_task"),
    )
    op.create_index("ix_simulation_task_case_id", "simulation_task", ["case_id"])
    op.create_index("ix_simulation_task_status", "simulation_task", ["status"])

    op.create_table(
        "simulation_result",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("task_id", sa.Integer(), nullable=False),
        sa.Column("section_id", sa.Integer(), nullable=True),
        sa.Column("river_id", sa.Integer(), nullable=True),
        sa.Column("section_code", sa.String(length=64), nullable=False),
        sa.Column("station", sa.Float(), nullable=False),
        sa.Column("time_seconds", sa.Float(), nullable=False),
        sa.Column("water_level", sa.Float(), nullable=False),
        sa.Column("flow", sa.Float(), nullable=False),
        sa.Column("velocity", sa.Float(), nullable=False),
        sa.ForeignKeyConstraint(
            ["task_id"],
            ["simulation_task.id"],
            name="fk_simulation_result_task_id",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["section_id"],
            ["cross_section.id"],
            name="fk_simulation_result_section_id",
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["river_id"],
            ["river.id"],
            name="fk_simulation_result_river_id",
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_simulation_result"),
        sa.UniqueConstraint(
            "task_id",
            "section_code",
            "time_seconds",
            name="uq_simulation_result_task_section_time",
        ),
    )
    op.create_index("ix_simulation_result_task_id", "simulation_result", ["task_id"])
    op.create_index(
        "ix_simulation_result_section_id", "simulation_result", ["section_id"]
    )
    op.create_index("ix_simulation_result_river_id", "simulation_result", ["river_id"])


def downgrade() -> None:
    """Remove Phase 3 results and restore the Phase 2 EPSG:4326 spatial types."""

    op.drop_table("simulation_result")
    op.drop_table("simulation_task")
    _transform_spatial_columns(4326)
