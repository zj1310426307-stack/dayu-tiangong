"""Persist trusted principals, local role bindings, reviews, and immutable audit evidence."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.gis.models import Base


class IdentityPrincipal(Base):
    """Represent one stable external identity by the issuer/subject pair."""

    __tablename__ = "identity_principal"
    __table_args__ = (
        UniqueConstraint("issuer", "subject", name="uq_identity_principal_issuer_subject"),
        Index("ix_identity_principal_active", "active"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    issuer: Mapped[str] = mapped_column(String(512), nullable=False)
    subject: Mapped[str] = mapped_column(String(255), nullable=False)
    display_name: Mapped[str] = mapped_column(String(255), nullable=False)
    email: Mapped[str | None] = mapped_column(String(320))
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")
    authentication_method: Mapped[str] = mapped_column(String(32), nullable=False)
    first_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class IdentityRoleBinding(Base):
    """Grant one server-owned role to a principal without trusting token claims."""

    __tablename__ = "identity_role_binding"
    __table_args__ = (
        CheckConstraint(
            "role IN ('viewer','engineer','engineering_reviewer','dataset_freezer','security_admin')",
            name="ck_identity_role_binding_role",
        ),
        UniqueConstraint("principal_id", "role", name="uq_identity_role_binding_principal_role"),
        Index("ix_identity_role_binding_lookup", "principal_id", "active", "role"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    principal_id: Mapped[int] = mapped_column(
        ForeignKey("identity_principal.id", ondelete="CASCADE"), nullable=False
    )
    role: Mapped[str] = mapped_column(String(32), nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    created_by_principal_id: Mapped[int | None] = mapped_column(
        ForeignKey("identity_principal.id", ondelete="RESTRICT")
    )


class DatasetReview(Base):
    """Bind an engineering decision to an exact Dataset engineering graph hash."""

    __tablename__ = "dataset_review"
    __table_args__ = (
        CheckConstraint("action IN ('approve','reject','return')", name="ck_dataset_review_action"),
        CheckConstraint(
            "status IN ('approved','rejected','returned')", name="ck_dataset_review_status"
        ),
        Index("ix_dataset_review_current", "dataset_version_id", "status", "created_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    dataset_version_id: Mapped[int] = mapped_column(
        ForeignKey("dataset_version.id", ondelete="RESTRICT"), nullable=False
    )
    engineering_content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    action: Mapped[str] = mapped_column(String(16), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    reviewer_principal_id: Mapped[int] = mapped_column(
        ForeignKey("identity_principal.id", ondelete="RESTRICT"), nullable=False
    )
    reviewer_issuer: Mapped[str] = mapped_column(String(512), nullable=False)
    reviewer_subject: Mapped[str] = mapped_column(String(255), nullable=False)
    reviewer_display_name: Mapped[str] = mapped_column(String(255), nullable=False)
    comment: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class SecurityAuditEvent(Base):
    """Append consequential security evidence without exposing mutation APIs."""

    __tablename__ = "security_audit_event"
    __table_args__ = (
        CheckConstraint(
            "action IN ('AUTH_PRINCIPAL_OBSERVED','ROLE_GRANTED','ROLE_REVOKED',"
            "'DATASET_REVIEW_SUBMITTED','DATASET_REVIEW_APPROVED','DATASET_REVIEW_REJECTED',"
            "'DATASET_REVIEW_RETURNED','DATASET_FREEZE')",
            name="ck_security_audit_event_action",
        ),
        Index("ix_security_audit_resource", "resource_type", "resource_id", "created_at"),
        Index("ix_security_audit_actor", "actor_principal_id", "created_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    action: Mapped[str] = mapped_column(String(64), nullable=False)
    actor_principal_id: Mapped[int] = mapped_column(
        ForeignKey("identity_principal.id", ondelete="RESTRICT"), nullable=False
    )
    actor_issuer: Mapped[str] = mapped_column(String(512), nullable=False)
    actor_subject: Mapped[str] = mapped_column(String(255), nullable=False)
    actor_display_name: Mapped[str] = mapped_column(String(255), nullable=False)
    resource_type: Mapped[str] = mapped_column(String(64), nullable=False)
    resource_id: Mapped[str] = mapped_column(String(128), nullable=False)
    engineering_content_hash: Mapped[str | None] = mapped_column(String(64))
    previous_state: Mapped[str | None] = mapped_column(String(32))
    new_state: Mapped[str | None] = mapped_column(String(32))
    request_id: Mapped[str | None] = mapped_column(String(128))
    details_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, server_default="{}")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
