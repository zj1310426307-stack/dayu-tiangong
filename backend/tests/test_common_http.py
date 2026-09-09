"""Stable HTTP conflict details for database constraints."""

from types import SimpleNamespace
from unittest.mock import MagicMock

from sqlalchemy.exc import IntegrityError

from app.common.http import _integrity_conflict_detail


def test_integrity_conflict_detail_names_constraint_and_table() -> None:
    """Foreign-key failures should identify the blocking relation for operators."""

    original = SimpleNamespace(
        diag=SimpleNamespace(
            constraint_name="fk_hydraulic_reach_upstream_node_version",
            table_name="reach",
        )
    )
    detail = _integrity_conflict_detail(IntegrityError("DELETE", {}, original))

    assert "reach" in detail
    assert "fk_hydraulic_reach_upstream_node_version" in detail


def test_integrity_conflict_detail_has_safe_fallback() -> None:
    """Drivers without structured diagnostics still receive actionable text."""

    original = MagicMock()
    original.diag = None

    assert "请先处理引用记录" in _integrity_conflict_detail(
        IntegrityError("WRITE", {}, original)
    )
