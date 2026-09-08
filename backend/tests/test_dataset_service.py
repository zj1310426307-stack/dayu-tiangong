"""Regression tests for strict Dataset Version service response projections."""

from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any, cast

from sqlalchemy.orm import Session

from app.dataset.schemas import DatasetVersionApprovalRequest
from app.dataset.service import _case_record, approve_dataset_version_for_calculation
from app.gis.models import DatasetVersion


class _ScalarRows:
    """Return deterministic boundary-link IDs without requiring PostGIS."""

    def all(self) -> list[int]:
        return [47, 49]


class _CaseSession:
    """Provide the scalar-query surface used by the calculation-case projector."""

    def scalars(self, _statement: Any) -> _ScalarRows:
        return _ScalarRows()

    def flush(self) -> None:
        return None


def test_case_record_excludes_historical_orm_only_configuration() -> None:
    """An obsolete ORM audit column must not leak into the strict API record."""

    entity = SimpleNamespace(
        id=91,
        name="P=5%",
        description=None,
        dataset_version_id=78,
        boundary_condition_id=47,
        hydraulic_1d_configuration=None,
        v4_configuration=None,
        created_time=datetime(2026, 9, 9, tzinfo=UTC),
    )

    record = _case_record(cast(Session, _CaseSession()), entity)

    assert record.id == 91
    assert record.boundary_condition_ids == [47, 49]
    assert record.hydraulic_1d_configuration is None
    assert "v4_configuration" not in record.model_dump()


def test_approve_dataset_validates_every_case_before_freezing(monkeypatch: Any) -> None:
    """Approval must reuse the real mapper and persist one traceable content hash."""

    entity = DatasetVersion(
        id=78,
        version="gaominghe-2",
        name="Gaoming River",
        creator="web-operator",
        status="draft",
        created_time=datetime(2026, 9, 9, tzinfo=UTC),
    )
    validation = SimpleNamespace(
        summary=SimpleNamespace(errors=0, warnings=0, is_model_ready=True)
    )
    mapped_cases: list[tuple[int, bool]] = []

    monkeypatch.setattr(
        "app.dataset.service.assert_dataset_version_mutable",
        lambda _session, _version_id: entity,
    )
    monkeypatch.setattr(
        "app.dataset.service.run_validation",
        lambda _session, _version_id: validation,
    )
    monkeypatch.setattr(
        "app.dataset.service.build_hydraulic_1d_model",
        lambda _session, case_id, _config, *, allow_draft_for_approval: mapped_cases.append(
            (case_id, allow_draft_for_approval)
        ),
    )
    monkeypatch.setattr(
        "app.dataset.service.dataset_core_content_hash",
        lambda _session, _version_id: "a" * 64,
    )

    record = approve_dataset_version_for_calculation(
        cast(Session, _CaseSession()),
        entity,
        DatasetVersionApprovalRequest(
            reviewer="web-operator",
            reason="Validated and frozen for Standard 1D calculation",
        ),
    )

    assert mapped_cases == [(47, True), (49, True)]
    assert record.status == "approved"
    assert record.content_hash == "a" * 64
    assert record.reviewed_by == "web-operator"
    assert record.approved_by == "web-operator"


def test_approve_dataset_rejects_validation_warnings(monkeypatch: Any) -> None:
    """Warnings remain fail closed because approval makes the dataset immutable."""

    entity = DatasetVersion(
        id=78,
        version="gaominghe-2",
        name="Gaoming River",
        creator="web-operator",
        status="draft",
        created_time=datetime(2026, 9, 9, tzinfo=UTC),
    )
    validation = SimpleNamespace(
        summary=SimpleNamespace(errors=0, warnings=1, is_model_ready=False)
    )
    monkeypatch.setattr(
        "app.dataset.service.assert_dataset_version_mutable",
        lambda _session, _version_id: entity,
    )
    monkeypatch.setattr(
        "app.dataset.service.run_validation",
        lambda _session, _version_id: validation,
    )

    try:
        approve_dataset_version_for_calculation(
            cast(Session, _CaseSession()),
            entity,
            DatasetVersionApprovalRequest(reviewer="operator", reason="premature approval"),
        )
    except ValueError as exc:
        assert "0 个错误、0 个警告" in str(exc)
    else:
        raise AssertionError("validation warnings must block approval")
