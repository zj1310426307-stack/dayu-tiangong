"""Server-side identity, authorization, review, and audit operations."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.dataset.lifecycle import lock_dataset_version
from app.dataset.real01 import build_real01_readiness
from app.gis.models import DatasetVersion
from app.hydraulic.snapshot import engineering_graph_content_hash
from app.security.models import (
    DatasetReview,
    IdentityPrincipal,
    IdentityRoleBinding,
    SecurityAuditEvent,
)
from app.security.permissions import ROLES, permissions_for_roles

if TYPE_CHECKING:
    from app.security.auth import AuthenticatedPrincipal


def _audit(
    session: Session,
    principal: AuthenticatedPrincipal,
    action: str,
    resource_type: str,
    resource_id: str,
    **values: Any,
) -> SecurityAuditEvent:
    """Append security evidence using the verified principal snapshot."""

    event = SecurityAuditEvent(
        action=action,
        actor_principal_id=principal.id,
        actor_issuer=principal.issuer,
        actor_subject=principal.subject,
        actor_display_name=principal.display_name,
        resource_type=resource_type,
        resource_id=resource_id,
        engineering_content_hash=values.get("engineering_content_hash"),
        previous_state=values.get("previous_state"),
        new_state=values.get("new_state"),
        request_id=values.get("request_id"),
        details_json=values.get("details_json", {}),
    )
    session.add(event)
    return event


def observe_principal(
    session: Session,
    *,
    issuer: str,
    subject: str,
    display_name: str,
    email: str | None,
    authentication_method: str,
) -> tuple[IdentityPrincipal, tuple[str, ...]]:
    """Upsert an IdP identity while keeping role ownership entirely local."""

    entity = session.scalar(
        select(IdentityPrincipal).where(
            IdentityPrincipal.issuer == issuer,
            IdentityPrincipal.subject == subject,
        )
    )
    created = entity is None
    if created:
        entity = IdentityPrincipal(
            issuer=issuer,
            subject=subject,
            display_name=display_name,
            email=email,
            authentication_method=authentication_method,
        )
        session.add(entity)
        session.flush()
        session.add(
            SecurityAuditEvent(
                action="AUTH_PRINCIPAL_OBSERVED",
                actor_principal_id=entity.id,
                actor_issuer=issuer,
                actor_subject=subject,
                actor_display_name=display_name,
                resource_type="principal",
                resource_id=str(entity.id),
                details_json={"authentication_method": authentication_method},
            )
        )
    else:
        entity.display_name = display_name
        entity.email = email
        entity.authentication_method = authentication_method
        entity.last_seen_at = datetime.now(UTC)
        session.flush()
    roles = tuple(
        session.scalars(
            select(IdentityRoleBinding.role)
            .where(
                IdentityRoleBinding.principal_id == entity.id,
                IdentityRoleBinding.active.is_(True),
            )
            .order_by(IdentityRoleBinding.role)
        ).all()
    )
    return entity, roles


def grant_role(
    session: Session,
    target: IdentityPrincipal,
    role: str,
    actor: AuthenticatedPrincipal,
) -> IdentityRoleBinding:
    """Activate one valid role and record who authorized the change."""

    if role not in ROLES:
        raise ValueError(f"unsupported role: {role}")
    binding = session.scalar(
        select(IdentityRoleBinding).where(
            IdentityRoleBinding.principal_id == target.id,
            IdentityRoleBinding.role == role,
        )
    )
    if binding is None:
        binding = IdentityRoleBinding(
            principal_id=target.id,
            role=role,
            active=True,
            created_by_principal_id=actor.id,
        )
        session.add(binding)
        session.flush()
    else:
        binding.active = True
        binding.created_by_principal_id = actor.id
    _audit(session, actor, "ROLE_GRANTED", "principal", str(target.id), details_json={"role": role})
    session.flush()
    return binding


def revoke_role(
    session: Session,
    target: IdentityPrincipal,
    role: str,
    actor: AuthenticatedPrincipal,
) -> IdentityRoleBinding:
    """Deactivate a binding without deleting its history."""

    binding = session.scalar(
        select(IdentityRoleBinding).where(
            IdentityRoleBinding.principal_id == target.id,
            IdentityRoleBinding.role == role,
        )
    )
    if binding is None or not binding.active:
        raise ValueError("active role binding not found")
    binding.active = False
    _audit(session, actor, "ROLE_REVOKED", "principal", str(target.id), details_json={"role": role})
    session.flush()
    return binding


def submit_dataset_review(
    session: Session,
    version: DatasetVersion,
    principal: AuthenticatedPrincipal,
    comment: str | None,
) -> DatasetVersion:
    """Move an editable graph to review only after current-hash QA passes."""

    version = lock_dataset_version(session, version.id)
    if version.status != "draft":
        raise ValueError("only draft Dataset Versions can enter review")
    readiness = build_real01_readiness(session, version)
    if not readiness.can_freeze:
        raise ValueError("current engineering graph has no matching passed QA evidence")
    previous = version.status
    version.status = "review"
    version.engineering_content_hash = readiness.engineering_content_hash
    version.change_summary = comment
    _audit(
        session,
        principal,
        "DATASET_REVIEW_SUBMITTED",
        "dataset_version",
        str(version.id),
        engineering_content_hash=readiness.engineering_content_hash,
        previous_state=previous,
        new_state="review",
    )
    session.flush()
    return version


def decide_dataset_review(
    session: Session,
    version: DatasetVersion,
    principal: AuthenticatedPrincipal,
    action: str,
    comment: str | None,
) -> DatasetReview:
    """Bind the review decision to the current graph and matching QA evidence."""

    version = lock_dataset_version(session, version.id)
    if version.status != "review":
        raise ValueError("Dataset Version must be in review")
    if action not in {"approve", "reject", "return"}:
        raise ValueError("unsupported review action")
    graph_hash = engineering_graph_content_hash(session, version.id)
    if action == "approve":
        readiness = build_real01_readiness(session, version)
        if not readiness.can_freeze or readiness.engineering_content_hash != graph_hash:
            raise ValueError("approval requires current-hash passed QA evidence")
        status = "approved"
    elif action == "reject":
        status = "rejected"
    else:
        status = "returned"
    review = DatasetReview(
        dataset_version_id=version.id,
        engineering_content_hash=graph_hash,
        action=action,
        status=status,
        reviewer_principal_id=principal.id,
        reviewer_issuer=principal.issuer,
        reviewer_subject=principal.subject,
        reviewer_display_name=principal.display_name,
        comment=comment,
    )
    session.add(review)
    now = datetime.now(UTC)
    version.reviewed_by = principal.display_name
    version.reviewed_at = now
    version.change_summary = comment
    version.status = (
        "review" if action == "approve" else ("rejected" if action == "reject" else "draft")
    )
    action_name = {
        "approve": "DATASET_REVIEW_APPROVED",
        "reject": "DATASET_REVIEW_REJECTED",
        "return": "DATASET_REVIEW_RETURNED",
    }[action]
    _audit(
        session,
        principal,
        action_name,
        "dataset_version",
        str(version.id),
        engineering_content_hash=graph_hash,
        previous_state="review",
        new_state=version.status,
    )
    session.flush()
    return review


def latest_approved_review(session: Session, version_id: int) -> DatasetReview | None:
    """Return the newest immutable approval for one Dataset Version."""

    return session.scalar(
        select(DatasetReview)
        .where(
            DatasetReview.dataset_version_id == version_id,
            DatasetReview.status == "approved",
        )
        .order_by(DatasetReview.created_at.desc(), DatasetReview.id.desc())
    )


def record_freeze_audit(
    session: Session,
    version: DatasetVersion,
    principal: AuthenticatedPrincipal,
    graph_hash: str,
    previous_state: str,
) -> None:
    """Record the final authenticated freeze decision."""

    _audit(
        session,
        principal,
        "DATASET_FREEZE",
        "dataset_version",
        str(version.id),
        engineering_content_hash=graph_hash,
        previous_state=previous_state,
        new_state="approved",
    )


def effective_permissions(roles: tuple[str, ...]) -> tuple[str, ...]:
    """Expose deterministic permissions for tests and API responses."""

    return tuple(sorted(permissions_for_roles(roles)))
