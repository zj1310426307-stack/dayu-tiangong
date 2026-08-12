"""对纯 JSON 模型快照执行确定性规范化和 SHA-256 计算。"""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Mapping, Sequence
from datetime import date, datetime, timezone
from typing import Any


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
    """返回排序键、紧凑分隔符和 UTF-8 直出的规范 JSON。"""

    return json.dumps(
        _normalise(snapshot),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def snapshot_hash(snapshot: Mapping[str, Any]) -> str:
    """计算规范化快照的十六进制 SHA-256。"""

    return hashlib.sha256(canonical_json(snapshot).encode("utf-8")).hexdigest()
