"""Persist the complete unified engineering-graph identity for REAL-01 freezes.

Revision ID: 20260928_0037
Revises: 20260924_0036
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "20260928_0037"
down_revision: str | None = "20260924_0036"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add a full-graph identity without changing legacy GIS hash semantics."""

    op.add_column(
        "dataset_version",
        sa.Column("engineering_content_hash", sa.String(length=64), nullable=True),
    )
    op.create_index(
        "ix_dataset_version_engineering_content_hash",
        "dataset_version",
        ["engineering_content_hash"],
    )


def downgrade() -> None:
    """Remove only the additive REAL-01 identity column and its index."""

    op.drop_index("ix_dataset_version_engineering_content_hash", table_name="dataset_version")
    op.drop_column("dataset_version", "engineering_content_hash")
