"""Environment-backed configuration for the external MASCARET runtime boundary."""

from __future__ import annotations

from dataclasses import dataclass
from math import isfinite
from os import environ
from pathlib import Path
from re import fullmatch
from typing import Literal, Mapping

from model.hydraulic_1d.errors import Hydraulic1DValidationError
from model.hydraulic_1d.registry import (
    DEFAULT_HYDRAULIC_1D_ENGINE_ID,
    DEFAULT_HYDRAULIC_1D_ENGINE_VERSION,
)


MASCARET_ENGINE_ID = DEFAULT_HYDRAULIC_1D_ENGINE_ID
MASCARET_VERSION = DEFAULT_HYDRAULIC_1D_ENGINE_VERSION
MASCARET_UPSTREAM_TAG = "v9.1.1"
MASCARET_UPSTREAM_COMMIT = "1fe3b5141f7d9c9fa8fe6d6d0316c994a39c2d95"
MASCARET_SOURCE_ARCHIVE_SHA256 = (
    "54b52798435baeb294ad3418c2fe146b5c10ef0d6e8e3e9d72d606e0f9fdb5e3"
)
MASCARET_SOURCE_TREE_SHA256 = (
    "cd116294009e08872331cab1dedc54f2321f13bbb304c863c0e06c07e17e3a6f"
)
MASCARET_RUNTIME_SKIP_REASON = "SKIPPED_MASCARET_RUNTIME_NOT_AVAILABLE"


def _boolean(value: str, *, field: str) -> bool:
    """Parse one explicit boolean and reject typo-driven runtime activation."""

    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise Hydraulic1DValidationError(
        "MASCARET_CONFIG_INVALID",
        f"{field} must be a boolean value",
        field_path=field,
    )


@dataclass(frozen=True, slots=True)
class MascaretRuntimeConfig:
    """Freeze verified external/container controls for one worker process."""

    enabled: bool
    runtime: Literal["external", "container"]
    executable: str
    executable_sha256: str | None
    data_directory: Path | None
    container_image: str | None
    upstream_tag: str
    upstream_commit: str
    build_timestamp: str | None
    timeout_seconds: float
    workspace_root: Path
    retention_class: Literal["success", "failed", "debug", "benchmark"]
    retention_max_workspaces: int

    @classmethod
    def from_environment(
        cls,
        source: Mapping[str, str] | None = None,
    ) -> "MascaretRuntimeConfig":
        """Load only documented variables and keep host-specific paths out of source."""

        values = environ if source is None else source
        enabled = _boolean(
            values.get("MASCARET_ENABLED", "0"), field="MASCARET_ENABLED"
        )
        runtime = values.get("MASCARET_RUNTIME", "external").strip().lower()
        # RESET-01 used ``cli`` before the deployment contract was finalized.
        # Keep it as a read-only compatibility alias while emitting only
        # ``external`` in current configuration and provenance.
        if runtime == "cli":
            runtime = "external"
        if runtime not in {"external", "container"}:
            raise Hydraulic1DValidationError(
                "MASCARET_CONFIG_INVALID",
                "MASCARET_RUNTIME must be external or container",
                field_path="MASCARET_RUNTIME",
            )
        executable = values.get("MASCARET_EXECUTABLE", "mascaret").strip()
        if not executable:
            raise Hydraulic1DValidationError(
                "MASCARET_CONFIG_INVALID",
                "MASCARET_EXECUTABLE must not be blank",
                field_path="MASCARET_EXECUTABLE",
            )
        executable_sha256 = (
            values.get("MASCARET_EXECUTABLE_SHA256", "").strip().lower() or None
        )
        if (
            executable_sha256 is not None
            and fullmatch(r"[0-9a-f]{64}", executable_sha256) is None
        ):
            raise Hydraulic1DValidationError(
                "MASCARET_CONFIG_INVALID",
                "MASCARET_EXECUTABLE_SHA256 must be a lowercase SHA-256 digest",
                field_path="MASCARET_EXECUTABLE_SHA256",
            )
        configured_data = values.get("MASCARET_DATA_DIR", "").strip()
        data_directory = (
            Path(configured_data).expanduser().resolve() if configured_data else None
        )
        image = values.get("MASCARET_CONTAINER_IMAGE", "").strip() or None
        if runtime == "container" and image is None:
            raise Hydraulic1DValidationError(
                "MASCARET_CONFIG_INVALID",
                "container runtime requires an explicitly reviewed image",
                field_path="MASCARET_CONTAINER_IMAGE",
            )
        if enabled and runtime == "external" and executable_sha256 is None:
            raise Hydraulic1DValidationError(
                "MASCARET_CONFIG_INVALID",
                "enabled external runtime requires a reviewed MASCARET_EXECUTABLE_SHA256",
                field_path="MASCARET_EXECUTABLE_SHA256",
            )
        if (
            enabled
            and runtime == "container"
            and (
                image is None
                or fullmatch(
                    r"(?:[^\s@]+@)?sha256:[0-9a-fA-F]{64}",
                    image,
                )
                is None
            )
        ):
            raise Hydraulic1DValidationError(
                "MASCARET_CONFIG_INVALID",
                "enabled container runtime requires an immutable image digest",
                field_path="MASCARET_CONTAINER_IMAGE",
            )
        upstream_tag = values.get(
            "MASCARET_UPSTREAM_TAG", MASCARET_UPSTREAM_TAG
        ).strip()
        upstream_commit = (
            values.get(
                "MASCARET_UPSTREAM_COMMIT",
                MASCARET_UPSTREAM_COMMIT,
            )
            .strip()
            .lower()
        )
        if enabled and upstream_tag != MASCARET_UPSTREAM_TAG:
            raise Hydraulic1DValidationError(
                "MASCARET_VERSION_MISMATCH",
                f"reviewed adapter requires upstream tag {MASCARET_UPSTREAM_TAG}",
                field_path="MASCARET_UPSTREAM_TAG",
            )
        if enabled and upstream_commit != MASCARET_UPSTREAM_COMMIT:
            raise Hydraulic1DValidationError(
                "MASCARET_VERSION_MISMATCH",
                f"reviewed adapter requires upstream commit {MASCARET_UPSTREAM_COMMIT}",
                field_path="MASCARET_UPSTREAM_COMMIT",
            )
        build_timestamp = values.get("MASCARET_BUILD_TIMESTAMP", "").strip() or None
        if enabled and build_timestamp is None:
            raise Hydraulic1DValidationError(
                "MASCARET_RUNTIME_IDENTITY_UNKNOWN",
                "enabled runtime requires MASCARET_BUILD_TIMESTAMP provenance",
                field_path="MASCARET_BUILD_TIMESTAMP",
            )
        try:
            timeout = float(values.get("MASCARET_TIMEOUT", "3600"))
        except ValueError as exc:
            raise Hydraulic1DValidationError(
                "MASCARET_CONFIG_INVALID",
                "MASCARET_TIMEOUT must be a number of seconds",
                field_path="MASCARET_TIMEOUT",
            ) from exc
        if not isfinite(timeout) or timeout <= 0.0:
            raise Hydraulic1DValidationError(
                "MASCARET_CONFIG_INVALID",
                "MASCARET_TIMEOUT must be finite and positive",
                field_path="MASCARET_TIMEOUT",
            )
        configured_root = values.get("HYDRAULIC_WORKSPACE_ROOT", "").strip()
        repository_root = Path(__file__).resolve().parents[3]
        root = (
            Path(configured_root).expanduser()
            if configured_root
            else repository_root / "backend" / "storage" / "hydraulic-workspaces"
        )
        retention = values.get("MASCARET_RETENTION_CLASS", "failed").strip().lower()
        if retention not in {"success", "failed", "debug", "benchmark"}:
            raise Hydraulic1DValidationError(
                "MASCARET_CONFIG_INVALID",
                "MASCARET_RETENTION_CLASS must be success, failed, debug, or benchmark",
                field_path="MASCARET_RETENTION_CLASS",
            )
        try:
            retention_max = int(values.get("MASCARET_RETENTION_MAX_WORKSPACES", "20"))
        except ValueError as exc:
            raise Hydraulic1DValidationError(
                "MASCARET_CONFIG_INVALID",
                "MASCARET_RETENTION_MAX_WORKSPACES must be an integer",
                field_path="MASCARET_RETENTION_MAX_WORKSPACES",
            ) from exc
        if retention_max < 1 or retention_max > 1000:
            raise Hydraulic1DValidationError(
                "MASCARET_CONFIG_INVALID",
                "MASCARET_RETENTION_MAX_WORKSPACES must be between 1 and 1000",
                field_path="MASCARET_RETENTION_MAX_WORKSPACES",
            )
        return cls(
            enabled=enabled,
            runtime=runtime,  # type: ignore[arg-type]
            executable=executable,
            executable_sha256=executable_sha256,
            data_directory=data_directory,
            container_image=image,
            upstream_tag=upstream_tag,
            upstream_commit=upstream_commit,
            build_timestamp=build_timestamp,
            timeout_seconds=timeout,
            workspace_root=root.resolve(),
            retention_class=retention,  # type: ignore[arg-type]
            retention_max_workspaces=retention_max,
        )
