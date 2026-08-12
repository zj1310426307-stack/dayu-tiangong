"""Add Phase 1C versioned map annotations.

Revision ID: 20260813_0008
Revises: 20260812_0007
"""

from collections.abc import Sequence

from alembic import op
import geoalchemy2
import sqlalchemy as sa


revision: str = "20260813_0008"
down_revision: str | None = "20260812_0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create one indexed annotation table and derive baseline labels from authoritative GIS rows."""

    op.create_table(
        "map_annotation",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("dataset_version_id", sa.Integer(), nullable=False),
        sa.Column("annotation_type", sa.String(length=32), nullable=False),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("text", sa.String(length=256), nullable=False),
        sa.Column("description", sa.Text()),
        sa.Column("longitude", sa.Float(), nullable=False),
        sa.Column("latitude", sa.Float(), nullable=False),
        sa.Column("rotation", sa.Float(), nullable=False, server_default="0"),
        sa.Column("font_size", sa.Integer(), nullable=False, server_default="14"),
        sa.Column("color", sa.String(length=16), nullable=False, server_default="#E8F7FF"),
        sa.Column("visible_scale_min", sa.Float(), nullable=False, server_default="0"),
        sa.Column("visible_scale_max", sa.Float(), nullable=False, server_default="500000"),
        sa.Column("related_type", sa.String(length=32)),
        sa.Column("related_id", sa.Integer()),
        sa.Column(
            "geometry",
            geoalchemy2.Geometry("POINT", srid=4490, spatial_index=False),
            nullable=False,
        ),
        sa.Column(
            "created_time",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint("longitude BETWEEN -180 AND 180", name="ck_map_annotation_longitude"),
        sa.CheckConstraint("latitude BETWEEN -90 AND 90", name="ck_map_annotation_latitude"),
        sa.CheckConstraint("rotation >= 0 AND rotation < 360", name="ck_map_annotation_rotation"),
        sa.CheckConstraint("font_size BETWEEN 8 AND 72", name="ck_map_annotation_font_size"),
        sa.CheckConstraint(
            "ST_Equals(geometry, ST_SetSRID(ST_MakePoint(longitude, latitude), 4490))",
            name="ck_map_annotation_coordinate_geometry",
        ),
        sa.CheckConstraint(
            "visible_scale_min >= 0 AND visible_scale_max >= visible_scale_min",
            name="ck_map_annotation_visible_scale",
        ),
        sa.CheckConstraint(
            "annotation_type IN ('river', 'gate', 'pump', 'cross_section', "
            "'hydrology_station', 'dispatch_event', 'parameter', 'place')",
            name="ck_map_annotation_type",
        ),
        sa.CheckConstraint(
            "related_type IS NULL OR related_type IN "
            "('river', 'gate', 'pump', 'cross_section', 'hydrology_station', 'dispatch_event')",
            name="ck_map_annotation_related_type",
        ),
        sa.ForeignKeyConstraint(
            ["dataset_version_id"], ["dataset_version.id"], ondelete="CASCADE",
            name="fk_map_annotation_dataset_version_id",
        ),
        sa.UniqueConstraint(
            "dataset_version_id", "annotation_type", "name", "related_type", "related_id",
            name="uq_map_annotation_version_related_name",
        ),
    )
    op.create_index(
        "ix_map_annotation_geometry_gist", "map_annotation", ["geometry"],
        postgresql_using="gist",
    )
    op.create_index(
        "ix_map_annotation_dataset_type", "map_annotation",
        ["dataset_version_id", "annotation_type"],
    )
    op.create_index(
        "ix_map_annotation_related", "map_annotation", ["related_type", "related_id"]
    )

    op.execute(
        """
        INSERT INTO map_annotation (
            dataset_version_id, annotation_type, name, text, description,
            longitude, latitude, rotation, font_size, color,
            visible_scale_min, visible_scale_max, related_type, related_id, geometry
        )
        SELECT dataset_version_id, 'river', 'river-' || id, name,
               '河道名称（由权威河道几何派生）', ST_X(ST_LineInterpolatePoint(geometry, 0.5)),
               ST_Y(ST_LineInterpolatePoint(geometry, 0.5)),
               MOD((DEGREES(ST_Azimuth(ST_StartPoint(geometry), ST_EndPoint(geometry))) + 360)::numeric, 360)::double precision,
               18, '#72F1E2', 40000, 500000, 'river', id,
               ST_LineInterpolatePoint(geometry, 0.5)
        FROM river
        UNION ALL
        SELECT dataset_version_id, 'gate', 'gate-' || id, name,
               '闸门名称', ST_X(geometry), ST_Y(geometry), 0, 15, '#FFD166',
               0, 120000, 'gate', id, geometry
        FROM gate
        UNION ALL
        SELECT dataset_version_id, 'pump', 'pump-' || id, name,
               '泵站名称', ST_X(geometry), ST_Y(geometry), 0, 15, '#6CC7FF',
               0, 120000, 'pump', id, geometry
        FROM pump
        UNION ALL
        SELECT dataset_version_id, 'cross_section', 'cross-section-' || id,
               COALESCE(NULLIF(section_name, ''), section_code), '横断面名称',
               ST_X(geometry), ST_Y(geometry), 0, 12, '#CBB9FF',
               0, 65000, 'cross_section', id, geometry
        FROM cross_section
        """
    )


def downgrade() -> None:
    """Remove Phase 1C annotations without touching source river-network data."""

    op.drop_index("ix_map_annotation_related", table_name="map_annotation")
    op.drop_index("ix_map_annotation_dataset_type", table_name="map_annotation")
    op.drop_index("ix_map_annotation_geometry_gist", table_name="map_annotation")
    op.drop_table("map_annotation")
