"""Regression tests for strict Dataset Version service response projections."""

from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any, cast

from sqlalchemy.orm import Session

from app.dataset.schemas import DatasetVersionApprovalRequest, DatasetVersionCloneRequest
from app.dataset.service import (
    _case_record,
    approve_dataset_version_for_calculation,
    clone_dataset_version,
)
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


class _CloneRows:
    """Return no version-owned parameters for the clone lineage unit test."""

    def __iter__(self):
        return iter(())

    def all(self) -> list[object]:
        return []


class _CloneSession:
    """Model the small Session surface required by the lineage constructor."""

    def __init__(self) -> None:
        self.added: list[object] = []

    def add(self, entity: object) -> None:
        self.added.append(entity)

    def flush(self) -> None:
        for entity in self.added:
            if isinstance(entity, DatasetVersion) and entity.id is None:
                entity.id = 99
                entity.created_time = datetime(2026, 9, 13, tzinfo=UTC)

    def scalars(self, _statement: object) -> _CloneRows:
        return _CloneRows()


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


def test_clone_creates_writable_draft_lineage_without_certification(monkeypatch: Any) -> None:
    """A certified source creates a fresh Draft identity rather than reopening it."""

    source = DatasetVersion(
        id=78,
        version="V-APPROVED",
        name="approved source",
        creator="reviewer",
        status="approved",
        is_read_only=True,
        content_hash="a" * 64,
        reviewed_by="reviewer",
        approved_by="reviewer",
        created_time=datetime(2026, 9, 13, tzinfo=UTC),
    )
    session = _CloneSession()
    monkeypatch.setattr(
        "app.dataset.service.lock_dataset_version", lambda _session, _id: source
    )

    record = clone_dataset_version(
        cast(Session, session),
        source,
        DatasetVersionCloneRequest(
            version="V-APPROVED-DRAFT",
            name="approved source draft",
            creator="operator",
        ),
    )

    assert record.id == 99
    assert record.parent_version_id == 78
    assert record.status == "draft"
    assert record.is_read_only is False
    assert record.content_hash is None
    assert record.reviewed_by is None
    assert record.approved_by is None
    assert source.status == "approved"
    assert source.content_hash == "a" * 64


def test_approve_dataset_validates_every_case_before_freezing(monkeypatch: Any) -> None:
    """Approval must reuse the real mapper and persist one traceable content hash."""

    entity = DatasetVersion(
        id=78,
        version="gaominghe-2",
        name="Gaoming River",
        creator="web-operator",
        status="draft",
        is_read_only=False,
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


def test_approve_dataset_allows_validation_warnings_for_uncalibrated_workflow(monkeypatch: Any) -> None:
    """Warnings are retained as review information but do not block approval."""

    entity = DatasetVersion(
        id=78,
        version="gaominghe-2",
        name="Gaoming River",
        creator="web-operator",
        status="draft",
        is_read_only=False,
        created_time=datetime(2026, 9, 9, tzinfo=UTC),
    )
    validation = SimpleNamespace(
        summary=SimpleNamespace(errors=0, warnings=1, is_model_ready=True)
    )
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
        lambda _session, _case_id, _config, *, allow_draft_for_approval: None,
    )
    monkeypatch.setattr(
        "app.dataset.service.dataset_core_content_hash",
        lambda _session, _version_id: "b" * 64,
    )

    record = approve_dataset_version_for_calculation(
        cast(Session, _CaseSession()),
        entity,
        DatasetVersionApprovalRequest(reviewer="operator", reason="未率定方案，已知悉校核警告"),
    )

    assert record.status == "approved"
    assert record.content_hash == "b" * 64
