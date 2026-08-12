"""Persist structure head difference and pump transfer semantics.

Revision ID: 20260812_0005
Revises: 20260812_0004
Create Date: 2026-08-12
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "20260812_0005"
down_revision: str | None = "20260812_0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add queryable hydraulic head and internal/external pump transfer type."""

    op.add_column("structure_result", sa.Column("head_difference", sa.Float(), nullable=True))
    op.add_column("structure_result", sa.Column("transfer_type", sa.String(24), nullable=True))


def downgrade() -> None:
    """Remove the two Phase 4 result detail columns."""

    op.drop_column("structure_result", "transfer_type")
    op.drop_column("structure_result", "head_difference")
