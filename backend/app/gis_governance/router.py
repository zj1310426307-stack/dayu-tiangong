"""Thin FastAPI boundary for the controlled GIS production workflow."""

from typing import Annotated, Callable, TypeVar

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.database.session import get_database_session
from app.gis_governance import service
from app.gis_governance.errors import GovernanceError
from app.gis_governance.schemas import (
    BatchCreate,
    BatchDiff,
    BatchRecord,
    BatchStageRequest,
    PromotedVersionRecord,
    PromoteRequest,
    PublicationRecord,
    PublishRequest,
    ReviewDecisionRequest,
    ReviewRecord,
    ReviewSubmitRequest,
    RetireRequest,
    ValidationIssueRecord,
    ValidationRunRecord,
)


router = APIRouter(prefix="/api/v1/gis-governance", tags=["gis-governance"])
SessionDependency = Annotated[Session, Depends(get_database_session)]
T = TypeVar("T")


def _commit(session: Session, action: Callable[[], T]) -> T:
    """Commit one governance transaction and expose structured domain errors."""

    try:
        result = action()
        session.commit()
        return result
    except GovernanceError as exc:
        session.rollback()
        raise HTTPException(status_code=exc.status_code, detail=exc.detail()) from exc
    except IntegrityError as exc:
        session.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "GOVERNANCE_CONFLICT",
                "message": "Governance data violates an identity or reference constraint.",
                "context": {},
            },
        ) from exc


def _read(action: Callable[[], T]) -> T:
    """Map a read-side domain error without creating a transaction boundary."""

    try:
        return action()
    except GovernanceError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail()) from exc


@router.post("/batches", response_model=BatchRecord, status_code=201)
def create_batch(payload: BatchCreate, session: SessionDependency) -> BatchRecord:
    """Register source provenance before any authoritative promotion."""

    return _commit(session, lambda: service.create_batch(session, payload))


@router.get("/batches", response_model=list[BatchRecord])
def read_batches(session: SessionDependency) -> list[BatchRecord]:
    """List governance batches."""

    return service.list_batches(session)


@router.get("/batches/{batch_id}", response_model=BatchRecord)
def read_batch(batch_id: int, session: SessionDependency) -> BatchRecord:
    """Read one governance batch."""

    return _read(lambda: service.get_batch(session, batch_id))


@router.post("/batches/{batch_id}/stage", response_model=BatchRecord)
def stage_batch(
    batch_id: int, payload: BatchStageRequest, session: SessionDependency
) -> BatchRecord:
    """Declare QGIS/raw edits ready for platform validation."""

    return _commit(
        session,
        lambda: service.stage_batch(
            session,
            batch_id,
            payload.note,
            payload.actor,
            payload.standardization_completed,
        ),
    )


@router.post("/batches/{batch_id}/validate", response_model=ValidationRunRecord)
def validate_batch(batch_id: int, session: SessionDependency) -> ValidationRunRecord:
    """Persist the current authoritative validation generation."""

    return _commit(session, lambda: service.run_batch_validation(session, batch_id))


@router.get("/batches/{batch_id}/validation", response_model=ValidationRunRecord)
def read_validation(batch_id: int, session: SessionDependency) -> ValidationRunRecord:
    """Read the newest validation generation."""

    return _read(lambda: service.get_latest_validation(session, batch_id))


@router.get("/batches/{batch_id}/issues", response_model=list[ValidationIssueRecord])
def read_issues(batch_id: int, session: SessionDependency) -> list[ValidationIssueRecord]:
    """Read persistent feature-level findings."""

    return service.list_issues(session, batch_id)


@router.post("/batches/{batch_id}/submit-review", response_model=BatchRecord)
def submit_review(
    batch_id: int, payload: ReviewSubmitRequest, session: SessionDependency
) -> BatchRecord:
    """Bind the current validated content to a human review request."""

    return _commit(
        session, lambda: service.submit_review(session, batch_id, payload.actor)
    )


@router.post("/batches/{batch_id}/review", response_model=ReviewRecord)
def review_batch(
    batch_id: int, payload: ReviewDecisionRequest, session: SessionDependency
) -> ReviewRecord:
    """Append an approval, rejection, or request-for-changes decision."""

    return _commit(session, lambda: service.review_batch(session, batch_id, payload))


@router.get("/batches/{batch_id}/diff", response_model=BatchDiff)
def read_diff(batch_id: int, session: SessionDependency) -> BatchDiff:
    """Compare natural keys against the immutable parent version."""

    return _read(lambda: service.batch_diff(session, batch_id))


@router.post("/batches/{batch_id}/promote", response_model=PromotedVersionRecord)
def promote_batch(
    batch_id: int, payload: PromoteRequest, session: SessionDependency
) -> PromotedVersionRecord:
    """Atomically create one authoritative version from an approved batch."""

    return _commit(session, lambda: service.promote_batch(session, batch_id, payload))


@router.get("/publications", response_model=list[PublicationRecord])
def read_publications(session: SessionDependency) -> list[PublicationRecord]:
    """List publication audit records."""

    return service.list_publications(session)


@router.post("/versions/{version_id}/publish", response_model=PublicationRecord)
def publish_version(
    version_id: int, payload: PublishRequest, session: SessionDependency
) -> PublicationRecord:
    """Activate publish views and persist a service manifest."""

    return _commit(session, lambda: service.publish_version(session, version_id, payload))


@router.post("/versions/{version_id}/retire", response_model=PromotedVersionRecord)
def retire_version(
    version_id: int, payload: RetireRequest, session: SessionDependency
) -> PromotedVersionRecord:
    """Retire a publication while preserving the immutable historical version."""

    return _commit(session, lambda: service.retire_version(session, version_id, payload))
