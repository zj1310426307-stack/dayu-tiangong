"""Stable canonical hashing for staging generations and authoritative GIS versions."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
import hashlib
import json
import math
from typing import Any, Iterable


EXCLUDED_VOLATILE_FIELDS = {
    "id",
    "created_at",
    "updated_at",
    "created_time",
    "quality_status",
}


def _normalize(value: Any) -> Any:
    """Normalize database and Python values into deterministic JSON primitives."""

    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("Canonical GIS content cannot contain non-finite floats.")
        # float.hex() preserves the exact IEEE-754 value, including changes
        # below twelve decimal digits, across Python/PostgreSQL row ordering.
        # Canonicalize signed zero because it is not a business distinction.
        return {"__float64__": 0.0.hex() if value == 0.0 else value.hex()}
    if isinstance(value, dict):
        return {str(key): _normalize(value[key]) for key in sorted(value)}
    if isinstance(value, (list, tuple)):
        return [_normalize(item) for item in value]
    return value


def canonical_sha256(
    rows: Iterable[dict[str, Any]], *, exclude: set[str] | None = None
) -> str:
    """Hash row-order-independent business content using canonical UTF-8 JSON."""

    omitted = EXCLUDED_VOLATILE_FIELDS | (exclude or set())
    canonical_rows = [
        _normalize({key: value for key, value in row.items() if key not in omitted})
        for row in rows
    ]
    canonical_rows.sort(
        key=lambda item: json.dumps(
            item, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        )
    )
    payload = json.dumps(
        canonical_rows, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()
