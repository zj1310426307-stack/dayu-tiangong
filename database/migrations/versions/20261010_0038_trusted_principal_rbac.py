"""Add trusted principals, local RBAC, hash-bound review, and security audit.

Revision ID: 20261010_0038
Revises: 20260928_0037
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "20261010_0038"
down_revision: str | None = "20260928_0037"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create additive identity and authorization evidence tables."""

    op.create_table(
        "identity_principal",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("issuer", sa.String(512), nullable=False),
        sa.Column("subject", sa.String(255), nullable=False),
        sa.Column("display_name", sa.String(255), nullable=False),
        sa.Column("email", sa.String(320)),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("authentication_method", sa.String(32), nullable=False),
        sa.Column(
            "first_seen_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "last_seen_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint(
            "issuer", "subject", name="uq_identity_principal_issuer_subject"
        ),
    )
    op.create_index("ix_identity_principal_active", "identity_principal", ["active"])
    op.create_table(
        "identity_role_binding",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "principal_id",
            sa.Integer(),
            sa.ForeignKey("identity_principal.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("role", sa.String(32), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "created_by_principal_id",
            sa.Integer(),
            sa.ForeignKey("identity_principal.id", ondelete="RESTRICT"),
        ),
        sa.CheckConstraint(
            "role IN ('viewer','engineer','engineering_reviewer','dataset_freezer','security_admin')",
            name="ck_identity_role_binding_role",
        ),
        sa.UniqueConstraint(
            "principal_id", "role", name="uq_identity_role_binding_principal_role"
        ),
    )
    op.create_index(
        "ix_identity_role_binding_lookup",
        "identity_role_binding",
        ["principal_id", "active", "role"],
    )
    op.create_table(
        "dataset_review",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "dataset_version_id",
            sa.Integer(),
            sa.ForeignKey("dataset_version.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("engineering_content_hash", sa.String(64), nullable=False),
        sa.Column("action", sa.String(16), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column(
            "reviewer_principal_id",
            sa.Integer(),
            sa.ForeignKey("identity_principal.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("reviewer_issuer", sa.String(512), nullable=False),
        sa.Column("reviewer_subject", sa.String(255), nullable=False),
        sa.Column("reviewer_display_name", sa.String(255), nullable=False),
        sa.Column("comment", sa.Text()),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint(
            "action IN ('approve','reject','return')", name="ck_dataset_review_action"
        ),
        sa.CheckConstraint(
            "status IN ('approved','rejected','returned')",
            name="ck_dataset_review_status",
        ),
    )
    op.create_index(
        "ix_dataset_review_current",
        "dataset_review",
        ["dataset_version_id", "status", "created_at"],
    )
    op.create_table(
        "security_audit_event",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("action", sa.String(64), nullable=False),
        sa.Column(
            "actor_principal_id",
            sa.Integer(),
            sa.ForeignKey("identity_principal.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("actor_issuer", sa.String(512), nullable=False),
        sa.Column("actor_subject", sa.String(255), nullable=False),
        sa.Column("actor_display_name", sa.String(255), nullable=False),
        sa.Column("resource_type", sa.String(64), nullable=False),
        sa.Column("resource_id", sa.String(128), nullable=False),
        sa.Column("engineering_content_hash", sa.String(64)),
        sa.Column("previous_state", sa.String(32)),
        sa.Column("new_state", sa.String(32)),
        sa.Column("request_id", sa.String(128)),
        sa.Column(
            "details_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint(
            "action IN ('AUTH_PRINCIPAL_OBSERVED','ROLE_GRANTED','ROLE_REVOKED','DATASET_REVIEW_SUBMITTED','DATASET_REVIEW_APPROVED','DATASET_REVIEW_REJECTED','DATASET_REVIEW_RETURNED','DATASET_FREEZE')",
            name="ck_security_audit_event_action",
        ),
    )
    op.create_index(
        "ix_security_audit_resource",
        "security_audit_event",
        ["resource_type", "resource_id", "created_at"],
    )
    op.create_index(
        "ix_security_audit_actor",
        "security_audit_event",
        ["actor_principal_id", "created_at"],
    )


def downgrade() -> None:
    """Remove only HYDRO-AUTH-01 additive tables in dependency order."""

    op.drop_table("security_audit_event")
    op.drop_table("dataset_review")
    op.drop_table("identity_role_binding")
    op.drop_table("identity_principal")
