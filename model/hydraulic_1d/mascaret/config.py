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
    """Freeze the supported CLI/container controls for one worker process."""

    enabled: bool
    runtime: Literal["cli", "container"]
    executable: str
    executable_sha256: str | None
    container_image: str | None
    timeout_seconds: float
    workspace_root: Path

    @classmethod
    def from_environment(
        cls,
        source: Mapping[str, str] | None = None,
    ) -> "MascaretRuntimeConfig":
        """Load only documented variables and keep host-specific paths out of source."""

        values = environ if source is None else source
        enabled = _boolean(values.get("MASCARET_ENABLED", "0"), field="MASCARET_ENABLED")
        runtime = values.get("MASCARET_RUNTIME", "cli").strip().lower()
        if runtime not in {"cli", "container"}:
            raise Hydraulic1DValidationError(
                "MASCARET_CONFIG_INVALID",
                "MASCARET_RUNTIME must be cli or container",
                field_path="MASCARET_RUNTIME",
            )
        executable = values.get("MASCARET_EXECUTABLE", "mascaret.py").strip()
        if not executable:
            raise Hydraulic1DValidationError(
                "MASCARET_CONFIG_INVALID",
                "MASCARET_EXECUTABLE must not be blank",
                field_path="MASCARET_EXECUTABLE",
            )
        executable_sha256 = values.get("MASCARET_EXECUTABLE_SHA256", "").strip().lower() or None
        if executable_sha256 is not None and fullmatch(r"[0-9a-f]{64}", executable_sha256) is None:
            raise Hydraulic1DValidationError(
                "MASCARET_CONFIG_INVALID",
                "MASCARET_EXECUTABLE_SHA256 must be a lowercase SHA-256 digest",
                field_path="MASCARET_EXECUTABLE_SHA256",
            )
        image = values.get("MASCARET_CONTAINER_IMAGE", "").strip() or None
        if runtime == "container" and image is None:
            raise Hydraulic1DValidationError(
                "MASCARET_CONFIG_INVALID",
                "container runtime requires an explicitly reviewed image",
                field_path="MASCARET_CONTAINER_IMAGE",
            )
        if enabled and runtime == "cli" and executable_sha256 is None:
            raise Hydraulic1DValidationError(
                "MASCARET_CONFIG_INVALID",
                "enabled CLI runtime requires a reviewed MASCARET_EXECUTABLE_SHA256",
                field_path="MASCARET_EXECUTABLE_SHA256",
            )
        if enabled and runtime == "container" and (
            image is None
            or fullmatch(r"[^\s@]+@sha256:[0-9a-fA-F]{64}", image) is None
        ):
            raise Hydraulic1DValidationError(
                "MASCARET_CONFIG_INVALID",
                "enabled container runtime requires an immutable image digest",
                field_path="MASCARET_CONTAINER_IMAGE",
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
        return cls(
            enabled=enabled,
            runtime=runtime,  # type: ignore[arg-type]
            executable=executable,
            executable_sha256=executable_sha256,
            container_image=image,
            timeout_seconds=timeout,
            workspace_root=root.resolve(),
        )
