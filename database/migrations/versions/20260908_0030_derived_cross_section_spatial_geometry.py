"""Add reproducible branch-derived cross-section spatial geometry.

Revision ID: 20260908_0030
Revises: 20260903_0029
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from geoalchemy2 import Geometry


revision: str = "20260908_0030"
down_revision: str | None = "20260903_0029"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add only derived/evidence columns; raw profile columns remain untouched."""

    op.add_column("cross_section", sa.Column("derived_location", Geometry("POINT", srid=4490), nullable=True), schema="hydraulic")
    op.add_column("cross_section", sa.Column("derived_axis", Geometry("LINESTRING", srid=4490), nullable=True), schema="hydraulic")
    op.add_column("cross_section", sa.Column("branch_intersection_station", sa.Float(), nullable=True), schema="hydraulic")
    op.add_column("cross_section", sa.Column("anchor_source", sa.String(24), nullable=False, server_default="MIDPOINT_FALLBACK"), schema="hydraulic")
    op.add_column("cross_section", sa.Column("review_status", sa.String(24), nullable=False, server_default="NEEDS_REVIEW"), schema="hydraulic")
    op.add_column("cross_section", sa.Column("spatial_geometry_source", sa.String(24), nullable=False, server_default="UNAVAILABLE"), schema="hydraulic")
    op.add_column("cross_section", sa.Column("spatial_geometry_status", sa.String(24), nullable=False, server_default="UNAVAILABLE"), schema="hydraulic")
    op.add_column("cross_section", sa.Column("hydraulic_ready", sa.Boolean(), nullable=False, server_default=sa.true()), schema="hydraulic")
    op.create_check_constraint("ck_hydraulic_cross_section_anchor_source", "cross_section", "anchor_source IN ('MEASURED','MANUAL','MARKER_2_DERIVED','MIDPOINT_FALLBACK')", schema="hydraulic")
    op.create_check_constraint("ck_hydraulic_cross_section_review_status", "cross_section", "review_status IN ('REVIEWED','NEEDS_REVIEW')", schema="hydraulic")
    op.create_check_constraint("ck_hydraulic_cross_section_spatial_source", "cross_section", "spatial_geometry_source IN ('SURVEY_XY','DERIVED_FROM_BRANCH','UNAVAILABLE')", schema="hydraulic")
    op.create_check_constraint("ck_hydraulic_cross_section_spatial_status", "cross_section", "spatial_geometry_status IN ('SURVEY','DERIVED','UNAVAILABLE')", schema="hydraulic")
    op.add_column("cross_section_point", sa.Column("derived_geometry", Geometry("POINT", srid=4490), nullable=True), schema="hydraulic")
    op.drop_constraint("ck_hydraulic_cross_section_point_marker", "cross_section_point", schema="hydraulic", type_="check")
    op.create_check_constraint(
        "ck_hydraulic_cross_section_point_marker",
        "cross_section_point",
        "marker_type IN ('none','left_bank','right_bank','left_levee','right_levee','low_flow_left','low_flow_right','thalweg','main_channel')",
        schema="hydraulic",
    )


def downgrade() -> None:
    """Remove derived geometry while preserving all survey and hydraulic data."""

    op.drop_column("cross_section_point", "derived_geometry", schema="hydraulic")
    op.drop_constraint("ck_hydraulic_cross_section_point_marker", "cross_section_point", schema="hydraulic", type_="check")
    op.create_check_constraint(
        "ck_hydraulic_cross_section_point_marker",
        "cross_section_point",
        "marker_type IN ('none','left_bank','right_bank','left_levee','right_levee','low_flow_left','low_flow_right','thalweg')",
        schema="hydraulic",
    )
    for name in (
        "ck_hydraulic_cross_section_spatial_status",
        "ck_hydraulic_cross_section_spatial_source",
        "ck_hydraulic_cross_section_review_status",
        "ck_hydraulic_cross_section_anchor_source",
    ):
        op.drop_constraint(name, "cross_section", schema="hydraulic", type_="check")
    for name in (
        "hydraulic_ready", "spatial_geometry_status", "spatial_geometry_source",
        "review_status", "anchor_source", "branch_intersection_station",
        "derived_axis", "derived_location",
    ):
        op.drop_column("cross_section", name, schema="hydraulic")
