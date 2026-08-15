"""Verify offline GIS governance hashing, state, schema, and OpenAPI contracts."""

from __future__ import annotations

from copy import deepcopy
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.gis_governance.errors import GovernanceError
from app.gis_governance.hashing import canonical_sha256
from app.gis_governance.schemas import (
    BatchCreate,
    BatchRecord,
    BatchStageRequest,
    PublicationRecord,
    ReviewDecisionRequest,
    ValidationIssueRecord,
    ValidationRunRecord,
)
from app.gis_governance.state import ALLOWED_TRANSITIONS, require_transition
from app.main import app


client = TestClient(app)


def _business_rows() -> list[dict[str, object]]:
    """Return representative staging content including volatile and nested values."""

    return [
        {
            "id": 20,
            "code": "R-002",
            "name": "支流",
            "length": Decimal("1250.500"),
            "geometry": {
                "type": "LineString",
                "coordinates": [[113.2, 23.1], [113.3, 23.2]],
            },
            "quality_status": "pending",
            "updated_at": datetime(2026, 8, 14, 1, tzinfo=UTC),
        },
        {
            "id": 10,
            "code": "R-001",
            "name": "干流",
            "length": 2500.0,
            "source_payload": {"survey": {"team": "A", "year": 2026}},
            "created_at": datetime(2026, 8, 14, 0, tzinfo=UTC),
        },
    ]


def _batch_payload() -> dict[str, object]:
    """Build one valid creation request shared by schema boundary tests."""

    return {
        "entity_type": "river",
        "source_filename": "rivers.gpkg",
        "source_format": "GPKG",
        "source_size": 1024,
        "source_hash_sha256": "A" * 64,
        "source_crs": "EPSG:4490",
        "target_crs": "EPSG:4490",
        "mapping_version": "river-v1",
        "operator": "pytest",
    }


def test_canonical_hash_is_independent_of_row_order_and_volatile_fields() -> None:
    """Equivalent business content must hash identically despite storage ordering."""

    first = _business_rows()
    reordered = [deepcopy(first[1]), deepcopy(first[0])]
    reordered[0]["id"] = 999
    reordered[0]["created_at"] = datetime(2030, 1, 1, tzinfo=UTC)
    reordered[1]["quality_status"] = "passed"
    reordered[1]["updated_at"] = datetime(2030, 1, 2, tzinfo=UTC)

    assert canonical_sha256(first) == canonical_sha256(reordered)
    assert len(canonical_sha256(first)) == 64


def test_canonical_hash_changes_when_authoritative_business_content_changes() -> None:
    """Any authoritative attribute change must invalidate validation and approval hashes."""

    original = _business_rows()
    changed = deepcopy(original)
    changed[0]["length"] = Decimal("1250.501")

    assert canonical_sha256(original) != canonical_sha256(changed)


def test_canonical_hash_preserves_low_order_float_changes() -> None:
    """IEEE-754-distinct values must never collapse at a display precision."""

    assert canonical_sha256([{"value": 1.0000000000001}]) != canonical_sha256(
        [{"value": 1.0000000000002}]
    )


@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf")])
def test_canonical_hash_rejects_non_finite_numbers(value: float) -> None:
    """NaN and infinities have no portable authoritative GIS meaning."""

    with pytest.raises(ValueError, match="non-finite"):
        canonical_sha256([{"value": value}])


@pytest.mark.parametrize(
    ("current", "target"),
    [
        ("created", "staged"),
        ("staged", "validating"),
        ("validating", "validation_failed"),
        ("validation_failed", "validating"),
        ("validating", "validated"),
        ("validated", "in_review"),
        ("in_review", "changes_requested"),
        ("changes_requested", "staged"),
        ("in_review", "rejected"),
        ("in_review", "approved"),
        ("approved", "promoting"),
        ("promoting", "promoted"),
        ("promoted", "published"),
    ],
)
def test_state_machine_accepts_declared_lifecycle_transitions(
    current: str, target: str
) -> None:
    """Every documented forward, repair, or revalidation transition must be accepted."""

    assert target in ALLOWED_TRANSITIONS[current]
    require_transition(current, target)


@pytest.mark.parametrize(
    ("current", "target"),
    [
        ("created", "promoting"),
        ("validation_failed", "approved"),
        ("validated", "promoted"),
        ("rejected", "promoting"),
        ("published", "staged"),
        ("unknown", "staged"),
    ],
)
def test_state_machine_rejects_undeclared_jumps(current: str, target: str) -> None:
    """Invalid jumps must fail with a stable machine-readable conflict contract."""

    with pytest.raises(GovernanceError) as captured:
        require_transition(current, target)

    error = captured.value
    assert error.code == "INVALID_BATCH_TRANSITION"
    assert error.status_code == 409
    assert error.context == {"current": current, "target": target}
    assert error.detail()["message"]


@pytest.mark.parametrize("batch_status", sorted(ALLOWED_TRANSITIONS))
def test_pydantic_batch_status_and_provenance_contract(batch_status: str) -> None:
    """Creation provenance is strict and every declared lifecycle state is serializable."""

    created = BatchCreate.model_validate(_batch_payload())
    assert created.source_hash_sha256 == "a" * 64
    assert created.target_crs == "EPSG:4490"

    record_payload = _batch_payload() | {
        "id": 1,
        "batch_code": "c9326f1b-12de-44aa-8297-cf64afc3d600",
        "status": batch_status,
        "created_at": datetime(2026, 8, 14, tzinfo=UTC),
        "updated_at": datetime(2026, 8, 14, tzinfo=UTC),
    }
    assert BatchRecord.model_validate(record_payload).status == batch_status

    with pytest.raises(ValidationError):
        BatchRecord.model_validate(record_payload | {"status": "deleted"})
    with pytest.raises(ValidationError):
        BatchCreate.model_validate(_batch_payload() | {"target_crs": "EPSG:3857"})
    with pytest.raises(ValidationError):
        BatchCreate.model_validate(_batch_payload() | {"unexpected": True})


def test_raw_standardization_completion_requires_an_explicit_stage_declaration() -> None:
    """Raw landing and typed standardization remain separate auditable facts."""

    ordinary = BatchStageRequest.model_validate({"actor": "qgis-editor"})
    standardized = BatchStageRequest.model_validate(
        {"actor": "mapping-service", "standardization_completed": True}
    )
    assert ordinary.standardization_completed is False
    assert standardized.standardization_completed is True


@pytest.mark.parametrize("run_status", ["running", "passed", "failed"])
def test_pydantic_validation_run_status_domain(run_status: str) -> None:
    """Validation execution state remains separate from the batch lifecycle state."""

    payload = {
        "id": 1,
        "batch_id": 2,
        "ruleset_version": "gis-opt1.1",
        "status": run_status,
        "staging_content_hash": "a" * 64,
        "started_at": datetime(2026, 8, 14, tzinfo=UTC),
        "summary_json": {"errors": 0},
    }
    assert ValidationRunRecord.model_validate(payload).status == run_status
    with pytest.raises(ValidationError):
        ValidationRunRecord.model_validate(payload | {"status": "approved"})


@pytest.mark.parametrize("decision", ["approve", "reject", "request_changes"])
def test_pydantic_review_decision_domain(decision: str) -> None:
    """Human review requests accept only explicit append-only decision values."""

    parsed = ReviewDecisionRequest.model_validate(
        {"reviewer": "reviewer-a", "decision": decision, "comment": "checked"}
    )
    assert parsed.decision == decision


def test_pydantic_review_decision_rejects_unknown_value() -> None:
    """An ambiguous review action must not enter the service layer."""

    with pytest.raises(ValidationError):
        ReviewDecisionRequest.model_validate(
            {"reviewer": "reviewer-a", "decision": "pass"}
        )


@pytest.mark.parametrize("severity", ["error", "warning", "info"])
def test_pydantic_validation_issue_severity_domain(severity: str) -> None:
    """Persisted findings expose the three documented severity levels only."""

    issue = ValidationIssueRecord.model_validate(
        {
            "id": 1,
            "validation_run_id": 2,
            "batch_id": 3,
            "entity_type": "river",
            "feature_ref": "R-001",
            "rule_code": "GEOMETRY_SRID",
            "severity": severity,
            "message": "checked",
            "details_json": {},
            "created_at": datetime(2026, 8, 14, tzinfo=UTC),
        }
    )
    assert issue.severity == severity


def test_pydantic_validation_issue_rejects_unknown_severity() -> None:
    """Unranked findings must fail at the transport boundary."""

    with pytest.raises(ValidationError):
        ValidationIssueRecord.model_validate(
            {
                "id": 1,
                "validation_run_id": 2,
                "batch_id": 3,
                "entity_type": "river",
                "rule_code": "UNKNOWN",
                "severity": "critical",
                "message": "invalid",
                "details_json": {},
                "created_at": datetime(2026, 8, 14, tzinfo=UTC),
            }
        )


def test_pydantic_publication_status_domain() -> None:
    """Publication state remains distinct from batch validation and review state."""

    payload = {
        "id": 1,
        "dataset_version_id": 2,
        "publication_status": "published",
        "published_by": "publisher",
        "published_at": datetime(2026, 8, 14, tzinfo=UTC),
        "manifest_json": {"geoserver": ["river"]},
        "created_at": datetime(2026, 8, 14, tzinfo=UTC),
    }
    assert PublicationRecord.model_validate(payload).publication_status == "published"
    with pytest.raises(ValidationError):
        PublicationRecord.model_validate(payload | {"publication_status": "approved"})


def test_openapi_exposes_complete_gis_governance_control_plane() -> None:
    """The API schema must expose each query and mutation required by the workflow."""

    response = client.get("/openapi.json")
    assert response.status_code == 200
    paths = response.json()["paths"]
    expected_methods = {
        "/api/v1/gis-governance/batches": {"get", "post"},
        "/api/v1/gis-governance/batches/{batch_id}": {"get"},
        "/api/v1/gis-governance/batches/{batch_id}/stage": {"post"},
        "/api/v1/gis-governance/batches/{batch_id}/validate": {"post"},
        "/api/v1/gis-governance/batches/{batch_id}/validation": {"get"},
        "/api/v1/gis-governance/batches/{batch_id}/issues": {"get"},
        "/api/v1/gis-governance/batches/{batch_id}/submit-review": {"post"},
        "/api/v1/gis-governance/batches/{batch_id}/review": {"post"},
        "/api/v1/gis-governance/batches/{batch_id}/diff": {"get"},
        "/api/v1/gis-governance/batches/{batch_id}/promote": {"post"},
        "/api/v1/gis-governance/publications": {"get"},
        "/api/v1/gis-governance/versions/{version_id}/publish": {"post"},
        "/api/v1/gis-governance/versions/{version_id}/retire": {"post"},
    }
    missing = {
        path: methods
        for path, methods in expected_methods.items()
        if path not in paths or not methods.issubset(paths[path])
    }
    assert missing == {}
