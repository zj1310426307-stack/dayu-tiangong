"""创建 Phase 1 GIS 空间基线。

修订号：20260811_0001
上一修订：无
创建时间：2026-08-11
"""

from collections.abc import Sequence

from alembic import op
from geoalchemy2 import Geometry
import sqlalchemy as sa


revision: str = "20260811_0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """启用 PostGIS 并创建四类空间对象、约束和索引。"""

    op.execute("CREATE EXTENSION IF NOT EXISTS postgis")

    op.create_table(
        "river",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("code", sa.String(length=64), nullable=False),
        sa.Column("length", sa.Float(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column(
            "geometry",
            Geometry(geometry_type="LINESTRING", srid=4326, spatial_index=False),
            nullable=False,
        ),
        sa.Column(
            "created_time",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("length >= 0", name="ck_river_length_nonnegative"),
        sa.PrimaryKeyConstraint("id", name="pk_river"),
        sa.UniqueConstraint("code", name="uq_river_code"),
        sa.UniqueConstraint("name", name="uq_river_name"),
    )
    op.create_index("ix_river_geometry_gist", "river", ["geometry"], postgresql_using="gist")

    op.create_table(
        "cross_section",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("river_id", sa.Integer(), nullable=False),
        sa.Column("station", sa.Float(), nullable=False),
        sa.Column("elevation_points", sa.JSON(), nullable=False),
        sa.Column("roughness", sa.Float(), nullable=True),
        sa.Column(
            "geometry",
            Geometry(geometry_type="POINT", srid=4326, spatial_index=False),
            nullable=False,
        ),
        sa.Column(
            "created_time",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("station >= 0", name="ck_cross_section_station_nonnegative"),
        sa.CheckConstraint(
            "roughness IS NULL OR roughness > 0",
            name="ck_cross_section_roughness_positive",
        ),
        sa.ForeignKeyConstraint(
            ["river_id"], ["river.id"], name="fk_cross_section_river_id", ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name="pk_cross_section"),
        sa.UniqueConstraint("river_id", "station", name="uq_cross_section_river_station"),
    )
    op.create_index(
        "ix_cross_section_geometry_gist",
        "cross_section",
        ["geometry"],
        postgresql_using="gist",
    )
    op.create_index("ix_cross_section_river_id", "cross_section", ["river_id"])

    op.create_table(
        "gate",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("river_id", sa.Integer(), nullable=False),
        sa.Column("gate_type", sa.String(length=32), nullable=False),
        sa.Column("width", sa.Float(), nullable=False),
        sa.Column("height", sa.Float(), nullable=False),
        sa.Column(
            "status", sa.String(length=24), server_default=sa.text("'offline'"), nullable=False
        ),
        sa.Column(
            "geometry",
            Geometry(geometry_type="POINT", srid=4326, spatial_index=False),
            nullable=False,
        ),
        sa.Column(
            "created_time",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("width > 0", name="ck_gate_width_positive"),
        sa.CheckConstraint("height > 0", name="ck_gate_height_positive"),
        sa.CheckConstraint(
            "status IN ('online', 'offline', 'maintenance', 'fault')",
            name="ck_gate_status",
        ),
        sa.ForeignKeyConstraint(
            ["river_id"], ["river.id"], name="fk_gate_river_id", ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id", name="pk_gate"),
        sa.UniqueConstraint("name", name="uq_gate_name"),
    )
    op.create_index("ix_gate_geometry_gist", "gate", ["geometry"], postgresql_using="gist")
    op.create_index("ix_gate_river_id", "gate", ["river_id"])

    op.create_table(
        "pump",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("river_id", sa.Integer(), nullable=False),
        sa.Column("capacity", sa.Float(), nullable=False),
        sa.Column("power", sa.Float(), nullable=False),
        sa.Column(
            "status", sa.String(length=24), server_default=sa.text("'offline'"), nullable=False
        ),
        sa.Column(
            "geometry",
            Geometry(geometry_type="POINT", srid=4326, spatial_index=False),
            nullable=False,
        ),
        sa.Column(
            "created_time",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("capacity >= 0", name="ck_pump_capacity_nonnegative"),
        sa.CheckConstraint("power >= 0", name="ck_pump_power_nonnegative"),
        sa.CheckConstraint(
            "status IN ('online', 'offline', 'maintenance', 'fault')",
            name="ck_pump_status",
        ),
        sa.ForeignKeyConstraint(
            ["river_id"], ["river.id"], name="fk_pump_river_id", ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id", name="pk_pump"),
        sa.UniqueConstraint("name", name="uq_pump_name"),
    )
    op.create_index("ix_pump_geometry_gist", "pump", ["geometry"], postgresql_using="gist")
    op.create_index("ix_pump_river_id", "pump", ["river_id"])


def downgrade() -> None:
    """按依赖顺序移除 Phase 1 业务表，保留共享 PostGIS 扩展。"""

    op.drop_table("pump")
    op.drop_table("gate")
    op.drop_table("cross_section")
    op.drop_table("river")
