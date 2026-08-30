"""Add authoritative Cross Section bed elevation identity.

Revision ID: 20260829_0023
Revises: 20260828_0022
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "20260829_0023"
down_revision: str | None = "20260828_0022"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add nullable authority fields without inferring historical beds from Profiles."""

    op.add_column(
        "cross_section",
        sa.Column("bed_elevation_m", sa.Float(), nullable=True),
        schema="hydraulic",
    )
    op.add_column(
        "cross_section",
        sa.Column(
            "bed_elevation_source",
            sa.String(length=16),
            nullable=False,
            server_default="unconfirmed",
        ),
        schema="hydraulic",
    )
    op.add_column(
        "cross_section",
        sa.Column("bed_elevation_confirmed_by", sa.String(length=128), nullable=True),
        schema="hydraulic",
    )
    op.add_column(
        "cross_section",
        sa.Column(
            "bed_elevation_confirmed_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        schema="hydraulic",
    )
    op.create_check_constraint(
        "ck_hydraulic_cross_section_bed_source",
        "cross_section",
        "bed_elevation_source IN ('unconfirmed','surveyed','design','synthetic')",
        schema="hydraulic",
    )
    op.create_check_constraint(
        "ck_hydraulic_cross_section_bed_authority",
        "cross_section",
        "(bed_elevation_source = 'unconfirmed' "
        "AND bed_elevation_m IS NULL "
        "AND bed_elevation_confirmed_by IS NULL "
        "AND bed_elevation_confirmed_at IS NULL) OR "
        "(bed_elevation_source IN ('surveyed','design','synthetic') "
        "AND bed_elevation_m IS NOT NULL "
        "AND bed_elevation_confirmed_by IS NOT NULL "
        "AND bed_elevation_confirmed_at IS NOT NULL)",
        schema="hydraulic",
    )


def downgrade() -> None:
    """Remove only the additive D3A-2 bed authority fields."""

    op.drop_constraint(
        "ck_hydraulic_cross_section_bed_authority",
        "cross_section",
        type_="check",
        schema="hydraulic",
    )
    op.drop_constraint(
        "ck_hydraulic_cross_section_bed_source",
        "cross_section",
        type_="check",
        schema="hydraulic",
    )
    op.drop_column("cross_section", "bed_elevation_confirmed_at", schema="hydraulic")
    op.drop_column("cross_section", "bed_elevation_confirmed_by", schema="hydraulic")
    op.drop_column("cross_section", "bed_elevation_source", schema="hydraulic")
    op.drop_column("cross_section", "bed_elevation_m", schema="hydraulic")
