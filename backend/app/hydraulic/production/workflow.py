"""Immutable production evidence and workflow state helpers."""

from __future__ import annotations

from hashlib import sha256
import json

from app.hydraulic.production.contracts import (
    AcceptanceManifest,
    AcceptanceManifestRequest,
)


def _canonical_bytes(value: object) -> bytes:
    """Serialize evidence using one stable UTF-8 canonical policy."""

    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def build_acceptance_manifest(request: AcceptanceManifestRequest) -> AcceptanceManifest:
    """Build a machine-readable artifact without claiming professional approval."""

    evidence = request.model_dump(mode="json")
    evidence["professional_approval"] = {
        "status": "REQUIRED",
        "approved_by": None,
        "note": "Software gates do not replace responsible engineer or authority approval.",
    }
    digest = sha256(_canonical_bytes(evidence)).hexdigest()
    return AcceptanceManifest(manifest_hash=digest, evidence=evidence)


__all__ = ["build_acceptance_manifest"]
