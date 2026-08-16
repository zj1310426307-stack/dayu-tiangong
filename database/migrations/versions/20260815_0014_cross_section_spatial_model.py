"""Add optional cross-section spatial structures without changing the legacy contract.

Revision ID: 20260815_0014
Revises: 20260815_0013
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from geoalchemy2 import Geometry
from sqlalchemy.dialects import postgresql


revision: str = "20260815_0014"
down_revision: str | None = "20260815_0013"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _identity_columns() -> list[sa.Column]:
    return [
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("cross_section_id", sa.Integer(), nullable=False),
        sa.Column("dataset_version_id", sa.Integer(), nullable=False),
    ]


def upgrade() -> None:
    """Create additive point, axis, normalized point, and profile structures."""

    op.create_unique_constraint("uq_cross_section_id_version", "cross_section", ["id", "dataset_version_id"])
    op.create_table(
        "cross_section_location", *_identity_columns(),
        sa.Column("geometry", Geometry("POINT", srid=4490, spatial_index=False), nullable=False),
        sa.Column("survey_method", sa.String(64)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("cross_section_id", name="uq_cross_section_location_section"),
        sa.ForeignKeyConstraint(["cross_section_id", "dataset_version_id"], ["cross_section.id", "cross_section.dataset_version_id"], name="fk_cross_section_location_section_version", ondelete="CASCADE"),
    )
    op.create_index("ix_cross_section_location_geometry_gist", "cross_section_location", ["geometry"], postgresql_using="gist")
    op.create_index("ix_cross_section_location_version", "cross_section_location", ["dataset_version_id"])
    op.create_table(
        "cross_section_axis", *_identity_columns(),
        sa.Column("geometry", Geometry("LINESTRING", srid=4490, spatial_index=False), nullable=False),
        sa.Column("left_bank", Geometry("POINT", srid=4490, spatial_index=False)),
        sa.Column("right_bank", Geometry("POINT", srid=4490, spatial_index=False)),
        sa.Column("vertical_datum", sa.String(64)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("cross_section_id", name="uq_cross_section_axis_section"),
        sa.ForeignKeyConstraint(["cross_section_id", "dataset_version_id"], ["cross_section.id", "cross_section.dataset_version_id"], name="fk_cross_section_axis_section_version", ondelete="CASCADE"),
    )
    op.create_index("ix_cross_section_axis_geometry_gist", "cross_section_axis", ["geometry"], postgresql_using="gist")
    op.create_index("ix_cross_section_axis_version", "cross_section_axis", ["dataset_version_id"])
    op.create_table(
        "cross_section_point", *_identity_columns(),
        sa.Column("point_order", sa.Integer(), nullable=False),
        sa.Column("offset", sa.Float(), nullable=False),
        sa.Column("elevation", sa.Float(), nullable=False),
        sa.Column("geometry", Geometry("POINT", srid=4490, spatial_index=False)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("point_order >= 0", name="ck_cross_section_point_order"),
        sa.UniqueConstraint("cross_section_id", "point_order", name="uq_cross_section_point_order"),
        sa.ForeignKeyConstraint(["cross_section_id", "dataset_version_id"], ["cross_section.id", "cross_section.dataset_version_id"], name="fk_cross_section_point_section_version", ondelete="CASCADE"),
    )
    op.create_index("ix_cross_section_point_geometry_gist", "cross_section_point", ["geometry"], postgresql_using="gist")
    op.create_index("ix_cross_section_point_version", "cross_section_point", ["dataset_version_id"])
    op.create_table(
        "cross_section_profile", *_identity_columns(),
        sa.Column("profile", postgresql.JSONB(), nullable=False),
        sa.Column("vertical_datum", sa.String(64)),
        sa.Column("source_revision", sa.String(64)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("cross_section_id", name="uq_cross_section_profile_section"),
        sa.ForeignKeyConstraint(["cross_section_id", "dataset_version_id"], ["cross_section.id", "cross_section.dataset_version_id"], name="fk_cross_section_profile_section_version", ondelete="CASCADE"),
    )
    op.create_index("ix_cross_section_profile_version", "cross_section_profile", ["dataset_version_id"])
    op.execute("""
        CREATE VIEW publish.cross_section_spatial AS
        SELECT cs.id, cs.dataset_version_id, cs.section_code, cs.section_name,
               cs.station, cs.points, cs.geometry AS legacy_location,
               COALESCE(location.geometry, cs.geometry) AS location,
               axis.geometry AS axis, axis.left_bank, axis.right_bank,
               COALESCE(axis.vertical_datum, profile.vertical_datum) AS vertical_datum,
               profile.profile
          FROM public.cross_section AS cs
          JOIN public.dataset_version AS dv ON dv.id = cs.dataset_version_id
          LEFT JOIN public.cross_section_location AS location ON location.cross_section_id = cs.id
          LEFT JOIN public.cross_section_axis AS axis ON axis.cross_section_id = cs.id
          LEFT JOIN public.cross_section_profile AS profile ON profile.cross_section_id = cs.id
         WHERE dv.status = 'published'
    """)


def downgrade() -> None:
    """Remove only additive structures; the legacy cross_section table is untouched."""

    op.execute("DROP VIEW IF EXISTS publish.cross_section_spatial")
    op.drop_index("ix_cross_section_profile_version", table_name="cross_section_profile")
    op.drop_table("cross_section_profile")
    op.drop_index("ix_cross_section_point_version", table_name="cross_section_point")
    op.drop_index("ix_cross_section_point_geometry_gist", table_name="cross_section_point")
    op.drop_table("cross_section_point")
    op.drop_index("ix_cross_section_axis_version", table_name="cross_section_axis")
    op.drop_index("ix_cross_section_axis_geometry_gist", table_name="cross_section_axis")
    op.drop_table("cross_section_axis")
    op.drop_index("ix_cross_section_location_version", table_name="cross_section_location")
    op.drop_index("ix_cross_section_location_geometry_gist", table_name="cross_section_location")
    op.drop_table("cross_section_location")
    op.drop_constraint("uq_cross_section_id_version", "cross_section", type_="unique")
