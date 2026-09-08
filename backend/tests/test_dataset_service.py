"""Regression tests for strict Dataset Version service response projections."""

from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any, cast

from sqlalchemy.orm import Session

from app.dataset.service import _case_record


class _ScalarRows:
    """Return deterministic boundary-link IDs without requiring PostGIS."""

    def all(self) -> list[int]:
        return [47, 49]


class _CaseSession:
    """Provide the scalar-query surface used by the calculation-case projector."""

    def scalars(self, _statement: Any) -> _ScalarRows:
        return _ScalarRows()


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
