"""对纯 JSON 模型快照执行确定性规范化和 SHA-256 计算。"""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Mapping, Sequence
from datetime import date, datetime, timezone
from typing import Any

CANONICALIZATION_ID = "dayu-canonical-json-v1"


def _normalise(value: Any) -> Any:
    """递归规范化时间、浮点和集合，拒绝非有限数值。"""

    if isinstance(value, Mapping):
        return {str(key): _normalise(item) for key, item in sorted(value.items())}
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [_normalise(item) for item in value]
    if isinstance(value, datetime):
        instant = value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)
        return instant.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("快照不得包含 NaN 或 Inf")
        return 0.0 if value == 0.0 else value
    return value


def canonical_json(snapshot: Mapping[str, Any]) -> str:
    """Return the v1 canonical JSON text used by authoritative identities.

    V1 sorts mapping keys, uses compact separators, preserves Unicode code
    points without normalization, rejects non-finite numbers, normalizes
    negative zero, and appends no newline.  Authoritative numeric values must
    originate from frozen input rather than platform-dependent runtime math.
    """

    return json.dumps(
        _normalise(snapshot),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def canonical_json_bytes(snapshot: Mapping[str, Any]) -> bytes:
    """Encode canonical JSON as UTF-8 bytes with no BOM or trailing newline."""

    return canonical_json(snapshot).encode("utf-8")


def authoritative_input_hash(snapshot: Mapping[str, Any]) -> str:
    """Hash one frozen authoritative input under ``dayu-canonical-json-v1``."""

    return hashlib.sha256(canonical_json_bytes(snapshot)).hexdigest()


def snapshot_hash(snapshot: Mapping[str, Any]) -> str:
    """Return the legacy name for the authoritative input SHA-256."""

    return authoritative_input_hash(snapshot)
