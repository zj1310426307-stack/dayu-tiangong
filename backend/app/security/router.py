"""Trusted principal, role binding, review, and audit HTTP endpoints."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.common.http import commit_or_conflict, not_found
from app.database.session import get_database_session
from app.gis.models import DatasetVersion
from app.security import service
from app.security.auth import (
    AuthenticatedPrincipal,
    get_authenticated_principal,
    require_permission,
)
from app.security.models import DatasetReview, IdentityPrincipal, SecurityAuditEvent
from app.security.schemas import (
    CurrentPrincipalRecord,
    DatasetReviewDecisionRequest,
    DatasetReviewRecord,
    DatasetReviewRequest,
    RoleBindingRecord,
    RoleBindingRequest,
    SecurityAuditRecord,
)


router = APIRouter(prefix="/api/v1", tags=["security"])
SessionDependency = Annotated[Session, Depends(get_database_session)]
PrincipalDependency = Annotated[AuthenticatedPrincipal, Depends(get_authenticated_principal)]
SecurityAdminDependency = Annotated[
    AuthenticatedPrincipal, Depends(require_permission("security.roles.manage"))
]
EngineerDependency = Annotated[
    AuthenticatedPrincipal, Depends(require_permission("dataset.submit_review"))
]
ReviewerDependency = Annotated[
    AuthenticatedPrincipal, Depends(require_permission("dataset.approve"))
]
AuditReaderDependency = Annotated[AuthenticatedPrincipal, Depends(require_permission("audit.read"))]


@router.get("/auth/me", response_model=CurrentPrincipalRecord, summary="Get trusted current user")
def read_current_principal(principal: PrincipalDependency) -> CurrentPrincipalRecord:
    """Return verified identity and local role/permission resolution."""

    return CurrentPrincipalRecord(
        authenticated=True,
        id=principal.id,
        issuer=principal.issuer,
        subject=principal.subject,
        display_name=principal.display_name,
        email=principal.email,
        authentication_method=principal.authentication_method,
        roles=list(principal.roles),
        permissions=sorted(principal.permissions),
    )


@router.post(
    "/auth/principals/{principal_id}/roles",
    response_model=RoleBindingRecord,
    summary="Grant a server-owned role",
)
def grant_role(
    principal_id: int,
    payload: RoleBindingRequest,
    session: SessionDependency,
    actor: SecurityAdminDependency,
) -> RoleBindingRecord:
    """Grant a local role; token role/group claims are never consulted."""

    target = session.get(IdentityPrincipal, principal_id)
    if target is None:
        raise not_found("principal")
    try:
        binding = commit_or_conflict(
            session, lambda: service.grant_role(session, target, payload.role, actor)
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return RoleBindingRecord.model_validate(binding, from_attributes=True)


@router.delete(
    "/auth/principals/{principal_id}/roles/{role}",
    response_model=RoleBindingRecord,
    summary="Revoke a server-owned role",
)
def revoke_role(
    principal_id: int,
    role: str,
    session: SessionDependency,
    actor: SecurityAdminDependency,
) -> RoleBindingRecord:
    """Deactivate rather than delete authorization history."""

    target = session.get(IdentityPrincipal, principal_id)
    if target is None:
        raise not_found("principal")
    try:
        binding = commit_or_conflict(
            session, lambda: service.revoke_role(session, target, role, actor)
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return RoleBindingRecord.model_validate(binding, from_attributes=True)


@router.post(
    "/model-data/dataset-versions/{version_id}/submit-review",
    summary="Submit current graph for engineering review",
)
def submit_review(
    version_id: int,
    payload: DatasetReviewRequest,
    session: SessionDependency,
    principal: EngineerDependency,
) -> dict[str, object]:
    """Submit only a graph with matching current QA evidence."""

    version = session.get(DatasetVersion, version_id)
    if version is None:
        raise not_found("Dataset Version")
    try:
        entity = commit_or_conflict(
            session,
            lambda: service.submit_dataset_review(session, version, principal, payload.comment),
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {
        "id": entity.id,
        "status": entity.status,
        "engineering_content_hash": entity.engineering_content_hash,
    }


@router.post(
    "/model-data/dataset-versions/{version_id}/review",
    response_model=DatasetReviewRecord,
    summary="Record a hash-bound engineering review decision",
)
def decide_review(
    version_id: int,
    payload: DatasetReviewDecisionRequest,
    session: SessionDependency,
    principal: ReviewerDependency,
) -> DatasetReviewRecord:
    """Use the authenticated reviewer; no client reviewer name is accepted."""

    version = session.get(DatasetVersion, version_id)
    if version is None:
        raise not_found("Dataset Version")
    try:
        review = commit_or_conflict(
            session,
            lambda: service.decide_dataset_review(
                session, version, principal, payload.action, payload.comment
            ),
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return DatasetReviewRecord.model_validate(review, from_attributes=True)


@router.get(
    "/model-data/dataset-versions/{version_id}/reviews",
    response_model=list[DatasetReviewRecord],
    summary="List immutable dataset reviews",
)
def list_reviews(
    version_id: int,
    session: SessionDependency,
    _: AuditReaderDependency,
) -> list[DatasetReviewRecord]:
    """Return review evidence in decision order."""

    items = session.scalars(
        select(DatasetReview)
        .where(DatasetReview.dataset_version_id == version_id)
        .order_by(DatasetReview.id)
    ).all()
    return [DatasetReviewRecord.model_validate(item, from_attributes=True) for item in items]


@router.get("/auth/audit", response_model=list[SecurityAuditRecord], summary="Read security audit")
def read_security_audit(
    session: SessionDependency,
    _: AuditReaderDependency,
    limit: int = Query(default=100, ge=1, le=1000),
) -> list[SecurityAuditRecord]:
    """Read token-free append-only audit snapshots."""

    events = session.scalars(
        select(SecurityAuditEvent).order_by(SecurityAuditEvent.id.desc()).limit(limit)
    ).all()
    return [SecurityAuditRecord.model_validate(item, from_attributes=True) for item in events]


__all__ = ["router"]
