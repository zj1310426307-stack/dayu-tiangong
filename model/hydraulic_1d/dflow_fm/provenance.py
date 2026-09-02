"""Strict provenance manifest for the reviewed D-Flow FM runtime suite."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime
from hashlib import sha256
from json import JSONDecodeError, dumps, loads
from pathlib import Path
from re import fullmatch
from typing import Any, Mapping

from model.hydraulic_1d.dflow_fm.config import (
    DFLOW_NATIVE_VERSION,
    DIMR_NATIVE_VERSION,
    DFLOW_RUNTIME_BLOCKED,
    DFLOW_UPSTREAM_COMMIT,
    DFLOW_UPSTREAM_TAG,
    FBC_NATIVE_VERSION,
    HYDROLIB_CORE_UPSTREAM_COMMIT,
    HYDROLIB_CORE_UPSTREAM_TAG,
    HYDROLIB_CORE_VERSION,
)


PROVENANCE_SCHEMA = "dayu.dflow-runtime-provenance.v1"
PROVENANCE_COMPONENTS = ("dflowfm", "dimr", "fbc", "hydrolib_core")


class DFlowProvenanceUnavailable(ValueError):
    """Reject absent, incomplete, or non-reviewed runtime provenance."""

    code = DFLOW_RUNTIME_BLOCKED

    def __init__(self, message: str) -> None:
        """Prefix every manifest failure with the stable blocked-state token."""

        super().__init__(f"{self.code}: {message}")


def _required_text(payload: Mapping[str, Any], field: str, *, component: str) -> str:
    """Read a required one-line string and identify its component on failure."""

    value = payload.get(field)
    if (
        not isinstance(value, str)
        or not value.strip()
        or any(character in value for character in ("\x00", "\r", "\n"))
    ):
        raise DFlowProvenanceUnavailable(
            f"{component}.{field} is required and must be a single-line string"
        )
    return value.strip()


def _required_sha256(payload: Mapping[str, Any], field: str, *, component: str) -> str:
    """Read a required lowercase SHA-256 identity."""

    value = _required_text(payload, field, component=component).lower()
    if fullmatch(r"[0-9a-f]{64}", value) is None:
        raise DFlowProvenanceUnavailable(
            f"{component}.{field} must be a SHA-256 digest"
        )
    return value


def _required_commit(payload: Mapping[str, Any], *, component: str) -> str:
    """Read a full Git commit rather than an ambiguous abbreviated revision."""

    value = _required_text(payload, "upstream_commit", component=component).lower()
    if fullmatch(r"[0-9a-f]{40}", value) is None:
        raise DFlowProvenanceUnavailable(
            f"{component}.upstream_commit must be a full 40-character Git commit"
        )
    return value


def _required_timestamp(payload: Mapping[str, Any], *, component: str) -> str:
    """Require a timezone-aware ISO-8601 build timestamp."""

    value = _required_text(payload, "build_timestamp", component=component)
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise DFlowProvenanceUnavailable(
            f"{component}.build_timestamp must be ISO-8601"
        ) from exc
    if parsed.tzinfo is None:
        raise DFlowProvenanceUnavailable(
            f"{component}.build_timestamp must include a timezone"
        )
    return value


@dataclass(frozen=True, slots=True)
class DFlowComponentProvenance:
    """Identify one binary/library and the exact source manifest that built it."""

    version: str
    upstream_tag: str
    upstream_commit: str
    binary_sha256: str
    source_manifest: str
    platform: str
    architecture: str
    build_timestamp: str

    @property
    def source_manifest_sha256(self) -> str:
        """Expose the manifest field's digest semantics without duplicating JSON."""

        return self.source_manifest

    @classmethod
    def from_mapping(
        cls,
        payload: Mapping[str, Any],
        *,
        component: str,
    ) -> "DFlowComponentProvenance":
        """Parse every mandatory identity field; no field has an implicit default."""

        source_field = (
            "source_manifest"
            if "source_manifest" in payload
            else "source_manifest_sha256"
        )
        return cls(
            version=_required_text(payload, "version", component=component),
            upstream_tag=_required_text(payload, "upstream_tag", component=component),
            upstream_commit=_required_commit(payload, component=component),
            binary_sha256=_required_sha256(
                payload, "binary_sha256", component=component
            ),
            source_manifest=_required_sha256(
                payload, source_field, component=component
            ),
            platform=_required_text(payload, "platform", component=component).lower(),
            architecture=_required_text(
                payload, "architecture", component=component
            ).lower(),
            build_timestamp=_required_timestamp(payload, component=component),
        )


@dataclass(frozen=True, slots=True)
class DFlowRuntimeProvenance:
    """Bind D-Flow FM, DIMR, FBC/D-RTC, and HYDROLIB-core as one runtime."""

    dflowfm: DFlowComponentProvenance
    dimr: DFlowComponentProvenance
    fbc: DFlowComponentProvenance
    hydrolib_core: DFlowComponentProvenance
    schema_version: str = PROVENANCE_SCHEMA

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any]) -> "DFlowRuntimeProvenance":
        """Load and audit a complete manifest against the selected official release."""

        if payload.get("schema_version") != PROVENANCE_SCHEMA:
            raise DFlowProvenanceUnavailable(
                f"schema_version must be {PROVENANCE_SCHEMA}"
            )
        parsed: dict[str, DFlowComponentProvenance] = {}
        for component in PROVENANCE_COMPONENTS:
            component_payload = payload.get(component)
            if not isinstance(component_payload, Mapping):
                raise DFlowProvenanceUnavailable(
                    f"component {component} is missing from the provenance manifest"
                )
            parsed[component] = DFlowComponentProvenance.from_mapping(
                component_payload,
                component=component,
            )
        provenance = cls(**parsed)  # type: ignore[arg-type]
        provenance._verify_reviewed_release()
        return provenance

    def _verify_reviewed_release(self) -> None:
        """Reject drift from the audited DIMRset tag/commit and mixed platforms."""

        suite = (self.dflowfm, self.dimr, self.fbc)
        for name, component in zip(("dflowfm", "dimr", "fbc"), suite, strict=True):
            if component.upstream_tag != DFLOW_UPSTREAM_TAG:
                raise DFlowProvenanceUnavailable(
                    f"{name}.upstream_tag must be {DFLOW_UPSTREAM_TAG}"
                )
            if component.upstream_commit != DFLOW_UPSTREAM_COMMIT:
                raise DFlowProvenanceUnavailable(
                    f"{name}.upstream_commit must be {DFLOW_UPSTREAM_COMMIT}"
                )
        required_native_versions = {
            "dflowfm": DFLOW_NATIVE_VERSION,
            "dimr": DIMR_NATIVE_VERSION,
            "fbc": FBC_NATIVE_VERSION,
        }
        for name, component in zip(("dflowfm", "dimr", "fbc"), suite, strict=True):
            required_version = required_native_versions[name]
            if component.version != required_version:
                raise DFlowProvenanceUnavailable(
                    f"{name}.version must be {required_version}"
                )
        if self.hydrolib_core.version != HYDROLIB_CORE_VERSION:
            raise DFlowProvenanceUnavailable(
                f"hydrolib_core.version must be {HYDROLIB_CORE_VERSION}"
            )
        if self.hydrolib_core.upstream_tag != HYDROLIB_CORE_UPSTREAM_TAG:
            raise DFlowProvenanceUnavailable(
                f"hydrolib_core.upstream_tag must be {HYDROLIB_CORE_UPSTREAM_TAG}"
            )
        if self.hydrolib_core.upstream_commit != HYDROLIB_CORE_UPSTREAM_COMMIT:
            raise DFlowProvenanceUnavailable(
                f"hydrolib_core.upstream_commit must be {HYDROLIB_CORE_UPSTREAM_COMMIT}"
            )
        platforms = {
            (component.platform, component.architecture)
            for component in (self.dflowfm, self.dimr, self.fbc, self.hydrolib_core)
        }
        if len(platforms) != 1:
            raise DFlowProvenanceUnavailable(
                "all runtime components must name the same platform and architecture"
            )
        source_manifests = {
            component.source_manifest
            for component in (self.dflowfm, self.dimr, self.fbc)
        }
        if len(source_manifests) != 1:
            raise DFlowProvenanceUnavailable(
                "dflowfm, dimr, and fbc must share one reviewed source manifest"
            )

    def as_metadata(self) -> dict[str, Any]:
        """Return stable JSON-safe fields for result evidence and OCI comparison."""

        return asdict(self)

    def canonical_sha256(self) -> str:
        """Fingerprint the complete normalized manifest for image-label binding."""

        encoded = dumps(
            self.as_metadata(),
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("ascii")
        return sha256(encoded).hexdigest()


def load_dflow_provenance(path: Path | None) -> DFlowRuntimeProvenance:
    """Load one local reviewed manifest, failing closed on absence or unsafe indirection."""

    if path is None:
        raise DFlowProvenanceUnavailable("DFLOW_PROVENANCE_FILE is not configured")
    if path.is_symlink() or not path.is_file():
        raise DFlowProvenanceUnavailable(
            f"runtime provenance file is absent or unsafe: {path.name}"
        )
    try:
        payload = loads(path.read_text(encoding="utf-8", errors="strict"))
    except (OSError, UnicodeError, JSONDecodeError) as exc:
        raise DFlowProvenanceUnavailable(
            f"runtime provenance file cannot be read: {exc}"
        ) from exc
    if not isinstance(payload, Mapping):
        raise DFlowProvenanceUnavailable("runtime provenance must be a JSON object")
    return DFlowRuntimeProvenance.from_mapping(payload)


__all__ = [
    "PROVENANCE_COMPONENTS",
    "PROVENANCE_SCHEMA",
    "DFlowComponentProvenance",
    "DFlowProvenanceUnavailable",
    "DFlowRuntimeProvenance",
    "load_dflow_provenance",
]
