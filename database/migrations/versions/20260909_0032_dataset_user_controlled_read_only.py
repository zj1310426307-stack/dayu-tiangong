"""Separate Dataset Version workflow status from user-controlled read-only state.

Revision ID: 20260909_0032
Revises: 20260908_0031
"""

from alembic import op
import sqlalchemy as sa


revision = "20260909_0032"
down_revision = "20260908_0031"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Make every existing version editable and repair version-owned River cleanup."""

    op.add_column(
        "dataset_version",
        sa.Column("is_read_only", sa.Boolean(), nullable=False, server_default="false"),
    )
    op.drop_constraint(
        "fk_river_dataset_version_id", "river", type_="foreignkey"
    )
    op.create_foreign_key(
        "fk_river_dataset_version_id",
        "river",
        "dataset_version",
        ["dataset_version_id"],
        ["id"],
        ondelete="CASCADE",
    )


def downgrade() -> None:
    """Restore the historical status-driven schema without changing status values."""

    op.drop_constraint(
        "fk_river_dataset_version_id", "river", type_="foreignkey"
    )
    op.create_foreign_key(
        "fk_river_dataset_version_id",
        "river",
        "dataset_version",
        ["dataset_version_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.drop_column("dataset_version", "is_read_only")
