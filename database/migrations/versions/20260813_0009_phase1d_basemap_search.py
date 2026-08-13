"""Add Phase 1D versioned basemap and offline location-search tables.

Revision ID: 20260813_0009
Revises: 20260813_0008
"""

from collections.abc import Sequence

from alembic import op
import geoalchemy2
import sqlalchemy as sa


revision: str = "20260813_0009"
down_revision: str | None = "20260813_0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _common_columns(geometry_type: str) -> list[sa.Column]:
    """Return the shared identity and geometry columns for one basemap table."""

    return [
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("dataset_version_id", sa.Integer(), nullable=False),
        sa.Column("code", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("address", sa.String(length=256)),
        sa.Column(
            "geometry",
            geoalchemy2.Geometry(geometry_type, srid=4490, spatial_index=False),
            nullable=False,
        ),
    ]


def _create_table(name: str, geometry_type: str, extra: list[sa.Column]) -> None:
    """Create one constrained, indexed, version-owned basemap table."""

    op.create_table(
        name,
        *_common_columns(geometry_type),
        *extra,
        sa.ForeignKeyConstraint(
            ["dataset_version_id"], ["dataset_version.id"], ondelete="CASCADE",
            name=f"fk_{name}_dataset_version_id",
        ),
        sa.UniqueConstraint(
            "dataset_version_id", "code", name=f"uq_{name}_version_code"
        ),
    )
    op.create_index(f"ix_{name}_geometry_gist", name, ["geometry"], postgresql_using="gist")
    op.create_index(f"ix_{name}_version_name", name, ["dataset_version_id", "name"])


def upgrade() -> None:
    """Create five basemap tables and seed deterministic Guangzhou/DEMO search data."""

    _create_table(
        "administrative_area", "POLYGON",
        [sa.Column("administrative_level", sa.String(length=32), nullable=False)],
    )
    _create_table(
        "road", "LINESTRING", [sa.Column("road_type", sa.String(length=32), nullable=False)]
    )
    _create_table(
        "place_name", "POINT",
        [
            sa.Column("place_type", sa.String(length=32), nullable=False),
            sa.Column("importance", sa.Integer(), nullable=False, server_default="50"),
        ],
    )
    _create_table(
        "water_name", "POINT", [sa.Column("water_type", sa.String(length=32), nullable=False)]
    )
    _create_table(
        "poi", "POINT", [sa.Column("category", sa.String(length=64), nullable=False)]
    )

    op.execute("""
        INSERT INTO administrative_area
            (dataset_version_id, code, name, administrative_level, address, geometry)
        SELECT id, 'CN-GD-GZ', '广州市', 'city', '广东省广州市',
               ST_GeomFromText('POLYGON((113.10 22.95,113.55 22.95,113.55 23.35,113.10 23.35,113.10 22.95))', 4490)
        FROM dataset_version
        UNION ALL
        SELECT id, 'CN-GD-GZ-TH', '天河区', 'district', '广东省广州市天河区',
               ST_GeomFromText('POLYGON((113.25 23.05,113.48 23.05,113.48 23.24,113.25 23.24,113.25 23.05))', 4490)
        FROM dataset_version
        UNION ALL
        SELECT id, 'DEMO-BASIN', 'DEMO 工程流域', 'engineering_demo', 'DEMO DATA',
               ST_GeomFromText('POLYGON((119.92 30.02,120.62 30.02,120.62 30.55,119.92 30.55,119.92 30.02))', 4490)
        FROM dataset_version;

        INSERT INTO road (dataset_version_id, code, name, road_type, address, geometry)
        SELECT id, 'GZ-TSL', '天寿路', 'urban', '广州市天河区天寿路',
               ST_GeomFromText('LINESTRING(113.3380 23.1410,113.3392 23.1465,113.3400 23.1515)', 4490)
        FROM dataset_version
        UNION ALL SELECT id, 'GZ-GYKSL', '广园快速路', 'expressway', '广州市天河区广园快速路',
               ST_GeomFromText('LINESTRING(113.2900 23.1590,113.3500 23.1610,113.4300 23.1580)', 4490)
        FROM dataset_version
        UNION ALL SELECT id, 'GZ-TYDXL', '天源路', 'arterial', '广州市天河区天源路',
               ST_GeomFromText('LINESTRING(113.3450 23.1650,113.3600 23.2050,113.3760 23.2450)', 4490)
        FROM dataset_version
        UNION ALL SELECT id, 'DEMO-RD-001', 'DEMO 防汛巡检路', 'engineering', 'DEMO 工程流域',
               ST_GeomFromText('LINESTRING(120.00 30.235,120.18 30.255,120.36 30.235,120.55 30.285)', 4490)
        FROM dataset_version;

        INSERT INTO place_name (dataset_version_id, code, name, place_type, address, importance, geometry)
        SELECT id, 'PLACE-GZ', '广州市', 'city', '广东省广州市', 100, ST_SetSRID(ST_MakePoint(113.2644,23.1291),4490)
        FROM dataset_version
        UNION ALL SELECT id, 'PLACE-TH', '天河区', 'district', '广东省广州市天河区', 90, ST_SetSRID(ST_MakePoint(113.3612,23.1247),4490)
        FROM dataset_version
        UNION ALL SELECT id, 'PLACE-DEMO', 'DEMO 河网调度区', 'engineering_demo', 'DEMO DATA', 80, ST_SetSRID(ST_MakePoint(120.27,30.27),4490)
        FROM dataset_version;

        INSERT INTO water_name (dataset_version_id, code, name, water_type, address, geometry)
        SELECT id, 'WATER-ZJ', '珠江', 'river', '广东省广州市', ST_SetSRID(ST_MakePoint(113.2700,23.1050),4490)
        FROM dataset_version
        UNION ALL SELECT id, 'WATER-SHC', '沙河涌', 'channel', '广州市天河区', ST_SetSRID(ST_MakePoint(113.3220,23.1450),4490)
        FROM dataset_version
        UNION ALL SELECT id, 'WATER-DEMO', 'DEMO 主河道水系', 'engineering_demo', 'DEMO DATA', ST_SetSRID(ST_MakePoint(120.30,30.24),4490)
        FROM dataset_version;

        INSERT INTO poi (dataset_version_id, code, name, category, address, geometry)
        SELECT id, 'POI-GZ-EAST', '广州东站', 'transport', '广州市天河区林和中路', ST_SetSRID(ST_MakePoint(113.3249,23.1503),4490)
        FROM dataset_version
        UNION ALL SELECT id, 'POI-TIANHE-SPORTS', '天河体育中心', 'public_service', '广州市天河区天河路299号', ST_SetSRID(ST_MakePoint(113.3283,23.1377),4490)
        FROM dataset_version
        UNION ALL SELECT id, 'POI-COORD-DEMO', '天寿路坐标示例点', 'demo_coordinate', '广州市天河区天寿路', ST_SetSRID(ST_MakePoint(113.3238,23.1356),4490)
        FROM dataset_version
        UNION ALL SELECT id, 'POI-DAYU-CENTER', '大禹天工调度中心', 'engineering', 'DEMO 工程流域', ST_SetSRID(ST_MakePoint(120.27,30.27),4490)
        FROM dataset_version;
    """)


def downgrade() -> None:
    """Remove Phase 1D basemap objects without touching engineering or model data."""

    for table_name in ("poi", "water_name", "place_name", "road", "administrative_area"):
        op.drop_index(f"ix_{table_name}_version_name", table_name=table_name)
        op.drop_index(f"ix_{table_name}_geometry_gist", table_name=table_name)
        op.drop_table(table_name)
