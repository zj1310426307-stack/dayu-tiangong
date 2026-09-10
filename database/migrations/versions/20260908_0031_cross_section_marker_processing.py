"""Add auditable marker workflow and non-destructive processed geometry.

Revision ID: 20260908_0031
Revises: 20260908_0030
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20260908_0031"
down_revision = "20260908_0030"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Add backward-compatible profile workflow fields with legacy-safe defaults."""

    columns = (
        sa.Column("marker_detection_mode", sa.String(32), nullable=False, server_default="FULL_EXTENT"),
        sa.Column("active_extent_mode", sa.String(24), nullable=False, server_default="FULL_EXTENT"),
        sa.Column("overbank_treatment", sa.String(32), nullable=False, server_default="REAL_GEOMETRY"),
        sa.Column("extension_top_elevation_m", sa.Float(), nullable=True),
        sa.Column("design_max_water_level_m", sa.Float(), nullable=True),
        sa.Column("safety_freeboard_m", sa.Float(), nullable=False, server_default="0"),
        sa.Column("marker_config_json", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("processed_geometry_json", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("processing_config_version", sa.String(64), nullable=False, server_default="dayu-marker-v1"),
    )
    for column in columns:
        op.add_column("cross_section_profile", column, schema="hydraulic")
    op.create_check_constraint(
        "ck_hydraulic_profile_marker_detection_mode", "cross_section_profile",
        "marker_detection_mode IN ('FULL_EXTENT','MIKE11_COMPATIBLE','MANUAL','GIS_ASSISTED')",
        schema="hydraulic",
    )
    op.create_check_constraint(
        "ck_hydraulic_profile_active_extent_mode", "cross_section_profile",
        "active_extent_mode IN ('FULL_EXTENT','MARKER_EXTENT')", schema="hydraulic",
    )
    op.create_check_constraint(
        "ck_hydraulic_profile_overbank_treatment", "cross_section_profile",
        "overbank_treatment IN ('REAL_GEOMETRY','VERTICAL_EXTENSION')", schema="hydraulic",
    )
    op.create_check_constraint(
        "ck_hydraulic_profile_safety_freeboard", "cross_section_profile",
        "safety_freeboard_m >= 0", schema="hydraulic",
    )


def downgrade() -> None:
    """Remove only fields introduced by this revision."""

    for name in (
        "ck_hydraulic_profile_safety_freeboard",
        "ck_hydraulic_profile_overbank_treatment",
        "ck_hydraulic_profile_active_extent_mode",
        "ck_hydraulic_profile_marker_detection_mode",
    ):
        op.drop_constraint(name, "cross_section_profile", schema="hydraulic", type_="check")
    for name in (
        "processing_config_version", "processed_geometry_json", "marker_config_json",
        "safety_freeboard_m", "design_max_water_level_m", "extension_top_elevation_m",
        "overbank_treatment", "active_extent_mode", "marker_detection_mode",
    ):
        op.drop_column("cross_section_profile", name, schema="hydraulic")
