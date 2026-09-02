"""Fail-closed configuration for the external D-Flow FM/D-RTC boundary."""

from __future__ import annotations

from dataclasses import dataclass
from math import isfinite
from os import environ
from pathlib import Path
from re import fullmatch
from typing import Literal, Mapping

from model.hydraulic_1d.errors import Hydraulic1DValidationError


DFLOW_ENGINE_ID = "d-flow-fm"
DFLOW_SUITE_VERSION = "2026.02"
DFLOW_UPSTREAM_TAG = "DIMRset_2026.02"
DFLOW_UPSTREAM_COMMIT = "5a4649830b1e5072caf019fb4850bbdefd9ad431"
DFLOW_UPSTREAM_REPOSITORY = "https://github.com/Deltares/Delft3D"
DFLOW_NATIVE_VERSION = "1.2.184"
DIMR_NATIVE_VERSION = "2.00"
FBC_NATIVE_VERSION = "1.6.1"
HYDROLIB_CORE_VERSION = "1.0.1"
HYDROLIB_CORE_UPSTREAM_TAG = "1.0.1"
HYDROLIB_CORE_UPSTREAM_COMMIT = "878d526ed028308e8778d6227a559de6ce49d297"
DFLOW_RUNTIME_BLOCKED = "DFLOW_RUNTIME_BLOCKED"

_IMAGE_BY_DIGEST = r"(?P<name>[^\s@]+)@sha256:(?P<digest>[0-9a-f]{64})"
_SHA256 = r"[0-9a-f]{64}"


def _non_blank(value: str, *, field: str) -> str:
    """Reject blank or control-character-bearing executable/config values."""

    normalized = value.strip()
    if not normalized or any(
        character in normalized for character in ("\x00", "\r", "\n")
    ):
        raise Hydraulic1DValidationError(
            "DFLOW_CONFIG_INVALID",
            f"{field} must be a non-blank single-line value",
            field_path=field,
        )
    return normalized


def _optional_sha256(value: str, *, field: str) -> str | None:
    """Normalize one optional binary digest without accepting ambiguous hashes."""

    normalized = value.strip().lower()
    if not normalized:
        return None
    if fullmatch(_SHA256, normalized) is None:
        raise Hydraulic1DValidationError(
            "DFLOW_CONFIG_INVALID",
            f"{field} must be a SHA-256 digest",
            field_path=field,
        )
    return normalized


def _immutable_image(value: str) -> str:
    """Require a named OCI image pinned by digest and reject a latest alias."""

    image = _non_blank(value, field="DFLOW_CONTAINER_IMAGE")
    matched = fullmatch(_IMAGE_BY_DIGEST, image)
    if matched is None or matched.group("name").lower().endswith(":latest"):
        raise Hydraulic1DValidationError(
            "DFLOW_CONFIG_INVALID",
            "DFLOW_CONTAINER_IMAGE must be a non-latest image@sha256:digest reference",
            field_path="DFLOW_CONTAINER_IMAGE",
        )
    return image


@dataclass(frozen=True, slots=True)
class DFlowRuntimeConfig:
    """Freeze one worker's reviewed DIMR runtime controls.

    ``disabled`` is deliberately the default. Both enabled modes execute DIMR as
    the sole top-level solver command so D-Flow FM and D-RTC remain coupled by
    the official coordinator rather than by a Python time-step loop.
    """

    runtime: Literal["disabled", "cli", "container"]
    dimr_executable: str
    dimr_executable_sha256: str | None
    docker_executable: str
    container_image: str | None
    provenance_file: Path | None
    timeout_seconds: float
    workspace_root: Path
    upstream_tag: str = DFLOW_UPSTREAM_TAG
    upstream_commit: str = DFLOW_UPSTREAM_COMMIT
    dflowfm_artifact: Path | None = None
    fbc_artifact: Path | None = None
    hydrolib_core_artifact: Path | None = None

    @property
    def mode(self) -> Literal["disabled", "cli", "container"]:
        """Expose a readable alias for callers that describe runtime as a mode."""

        return self.runtime

    @classmethod
    def from_environment(
        cls,
        source: Mapping[str, str] | None = None,
    ) -> "DFlowRuntimeConfig":
        """Load documented settings while pinning the audited upstream release."""

        values = environ if source is None else source
        runtime = values.get("DFLOW_RUNTIME", "disabled").strip().lower()
        # The task document uses ``external`` while the executable-facing
        # contract names the same mode ``cli``. Accept the former as an input
        # alias, but store and report only the canonical value.
        if runtime == "external":
            runtime = "cli"
        if runtime not in {"disabled", "cli", "container"}:
            raise Hydraulic1DValidationError(
                "DFLOW_CONFIG_INVALID",
                "DFLOW_RUNTIME must be disabled, cli, or container",
                field_path="DFLOW_RUNTIME",
            )

        dimr_executable = _non_blank(
            values.get("DFLOW_DIMR_EXECUTABLE", "dimr"),
            field="DFLOW_DIMR_EXECUTABLE",
        )
        dimr_sha256 = _optional_sha256(
            values.get("DFLOW_DIMR_EXECUTABLE_SHA256", ""),
            field="DFLOW_DIMR_EXECUTABLE_SHA256",
        )
        docker_executable = _non_blank(
            values.get("DFLOW_DOCKER_EXECUTABLE", "docker"),
            field="DFLOW_DOCKER_EXECUTABLE",
        )
        configured_image = values.get("DFLOW_CONTAINER_IMAGE", "").strip()
        container_image = (
            _immutable_image(configured_image) if configured_image else None
        )
        if runtime == "container" and container_image is None:
            raise Hydraulic1DValidationError(
                "DFLOW_CONFIG_INVALID",
                "container mode requires DFLOW_CONTAINER_IMAGE pinned by digest",
                field_path="DFLOW_CONTAINER_IMAGE",
            )

        configured_provenance = values.get("DFLOW_PROVENANCE_FILE", "").strip()
        provenance_file = (
            Path(configured_provenance).expanduser().absolute()
            if configured_provenance
            else None
        )
        component_artifacts: dict[str, Path | None] = {}
        for field, environment_name in (
            ("dflowfm_artifact", "DFLOW_DFLOWFM_ARTIFACT"),
            ("fbc_artifact", "DFLOW_FBC_ARTIFACT"),
            ("hydrolib_core_artifact", "DFLOW_HYDROLIB_CORE_ARTIFACT"),
        ):
            configured = values.get(environment_name, "").strip()
            if not configured:
                component_artifacts[field] = None
                continue
            candidate = Path(
                _non_blank(configured, field=environment_name)
            ).expanduser()
            if not candidate.is_absolute():
                raise Hydraulic1DValidationError(
                    "DFLOW_CONFIG_INVALID",
                    f"{environment_name} must be an absolute reviewed artifact path",
                    field_path=environment_name,
                )
            component_artifacts[field] = candidate.absolute()
        try:
            timeout_seconds = float(values.get("DFLOW_TIMEOUT", "3600"))
        except ValueError as exc:
            raise Hydraulic1DValidationError(
                "DFLOW_CONFIG_INVALID",
                "DFLOW_TIMEOUT must be a number of seconds",
                field_path="DFLOW_TIMEOUT",
            ) from exc
        if not isfinite(timeout_seconds) or timeout_seconds <= 0:
            raise Hydraulic1DValidationError(
                "DFLOW_CONFIG_INVALID",
                "DFLOW_TIMEOUT must be finite and positive",
                field_path="DFLOW_TIMEOUT",
            )

        repository_root = Path(__file__).resolve().parents[3]
        configured_root = values.get(
            "DFLOW_WORKSPACE_ROOT",
            values.get("HYDRAULIC_WORKSPACE_ROOT", ""),
        ).strip()
        workspace_root = (
            Path(configured_root).expanduser()
            if configured_root
            else repository_root
            / "backend"
            / "storage"
            / "hydraulic-workspaces"
            / "dflow-fm"
        ).resolve()

        upstream_tag = values.get("DFLOW_UPSTREAM_TAG", DFLOW_UPSTREAM_TAG).strip()
        upstream_commit = (
            values.get("DFLOW_UPSTREAM_COMMIT", DFLOW_UPSTREAM_COMMIT).strip().lower()
        )
        if (
            upstream_tag != DFLOW_UPSTREAM_TAG
            or upstream_commit != DFLOW_UPSTREAM_COMMIT
        ):
            raise Hydraulic1DValidationError(
                "DFLOW_VERSION_MISMATCH",
                "D-Flow runtime must match the audited DIMRset_2026.02 tag and commit",
                field_path="DFLOW_UPSTREAM_TAG/DFLOW_UPSTREAM_COMMIT",
            )

        return cls(
            runtime=runtime,  # type: ignore[arg-type]
            dimr_executable=dimr_executable,
            dimr_executable_sha256=dimr_sha256,
            docker_executable=docker_executable,
            container_image=container_image,
            provenance_file=provenance_file,
            timeout_seconds=timeout_seconds,
            workspace_root=workspace_root,
            upstream_tag=upstream_tag,
            upstream_commit=upstream_commit,
            **component_artifacts,
        )


__all__ = [
    "DFLOW_ENGINE_ID",
    "DFLOW_RUNTIME_BLOCKED",
    "DFLOW_SUITE_VERSION",
    "DFLOW_UPSTREAM_COMMIT",
    "DFLOW_UPSTREAM_REPOSITORY",
    "DFLOW_UPSTREAM_TAG",
    "HYDROLIB_CORE_VERSION",
    "HYDROLIB_CORE_UPSTREAM_COMMIT",
    "HYDROLIB_CORE_UPSTREAM_TAG",
    "DFlowRuntimeConfig",
]
