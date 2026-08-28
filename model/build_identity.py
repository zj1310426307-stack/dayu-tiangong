"""Authoritative runtime build identity for task creation and execution."""

from __future__ import annotations

from dataclasses import dataclass
import json
from os import environ
import platform
from re import fullmatch
import sys
from typing import Final, Mapping

from model.provenance import snapshot_hash


ENGINE_VERSION: Final = "dayu-hydraulic-4.0.0"
BUILD_IDENTITY_SCHEMA: Final = "dayu.runtime-build.v1"
SOLVER_BUILD_ID_PREFIX: Final = "dayu.solver-build.v1:"
DEVELOPMENT_COMMIT_SENTINEL: Final = "development-unverified"
BUILD_MODES: Final = ("development", "ci", "release")


class BuildIdentityError(ValueError):
    """Reject an invalid or unverifiable runtime build configuration."""


class RuntimeBuildMismatchError(BuildIdentityError):
    """Reject execution when a Worker differs from the task's frozen build."""


@dataclass(frozen=True, slots=True)
class RuntimeBuildIdentity:
    """Bind product version, immutable code revision, Registry, and build mode."""

    engine_version: str
    engine_commit: str
    solver_build_id: str
    build_mode: str
    verified: bool

    def provenance(self) -> dict[str, str | bool]:
        """Return the canonical JSON-shaped fields persisted with tasks/results."""

        return {
            "engine_version": self.engine_version,
            "engine_commit": self.engine_commit,
            "solver_build_id": self.solver_build_id,
            "build_mode": self.build_mode,
            "build_verified": self.verified,
            "unverified_build": not self.verified,
            "build_identity_schema": BUILD_IDENTITY_SCHEMA,
        }


def is_git_sha(value: object) -> bool:
    """Return whether a value is one lowercase immutable 40-character Git SHA."""

    return isinstance(value, str) and fullmatch(r"[0-9a-f]{40}", value) is not None


def solver_build_id(
    *,
    engine_version: str,
    engine_commit: str,
    registry_hash: str,
) -> str:
    """Derive a deterministic solver build ID without host/process/time inputs."""

    payload = {
        "schema_version": BUILD_IDENTITY_SCHEMA,
        "engine_version": engine_version,
        "engine_commit": engine_commit,
        "registry_hash": registry_hash,
    }
    return f"{SOLVER_BUILD_ID_PREFIX}{snapshot_hash(payload)}"


def current_runtime_build_identity(
    environment: Mapping[str, str] | None = None,
) -> RuntimeBuildIdentity:
    """Resolve and validate the one identity of the currently executing process.

    CI and release modes fail closed unless ``ENGINE_COMMIT`` is an immutable SHA.
    Development may run without a repository by using an explicit unverified sentinel;
    callers cannot set ``verified`` independently.
    """

    from model.solver.registry import registry_hash

    source = environ if environment is None else environment
    mode = source.get("DAYU_BUILD_MODE", "development").strip().lower()
    if mode not in BUILD_MODES:
        raise BuildIdentityError(
            f"DAYU_BUILD_MODE must be one of {', '.join(BUILD_MODES)}"
        )
    version = source.get("DAYU_ENGINE_VERSION", ENGINE_VERSION).strip()
    if not version:
        raise BuildIdentityError("DAYU_ENGINE_VERSION must not be blank")
    configured_commit = source.get("ENGINE_COMMIT", "").strip()
    valid_commit = is_git_sha(configured_commit)
    if mode in {"ci", "release"} and not valid_commit:
        raise BuildIdentityError(
            f"{mode} runtime requires ENGINE_COMMIT as a lowercase 40-character Git SHA"
        )
    commit = configured_commit if valid_commit else DEVELOPMENT_COMMIT_SENTINEL
    return RuntimeBuildIdentity(
        engine_version=version,
        engine_commit=commit,
        solver_build_id=solver_build_id(
            engine_version=version,
            engine_commit=commit,
            registry_hash=registry_hash(),
        ),
        build_mode=mode,
        verified=valid_commit and mode in {"ci", "release"},
    )


def assert_runtime_build_matches(
    *,
    expected_engine_version: object,
    expected_engine_commit: object,
    expected_solver_build_id: object,
    expected_build_mode: object,
    expected_verified: object,
    expected_registry_hash: object,
    actual: RuntimeBuildIdentity | None = None,
) -> RuntimeBuildIdentity:
    """Fail closed when the executing process differs from frozen task identity."""

    from model.solver.registry import registry_hash

    worker = actual or current_runtime_build_identity()
    comparisons = {
        "engine_version": (expected_engine_version, worker.engine_version),
        "engine_commit": (expected_engine_commit, worker.engine_commit),
        "solver_build_id": (expected_solver_build_id, worker.solver_build_id),
        "build_mode": (expected_build_mode, worker.build_mode),
        "build_verified": (expected_verified, worker.verified),
        "registry_hash": (expected_registry_hash, registry_hash()),
    }
    mismatches = [
        f"{field}: expected={expected!r}, actual={observed!r}"
        for field, (expected, observed) in comparisons.items()
        if expected != observed
    ]
    if mismatches:
        raise RuntimeBuildMismatchError(
            "D2_RUNTIME_BUILD_MISMATCH: " + "; ".join(mismatches)
        )
    return worker


def runtime_build_diagnostic() -> dict[str, object]:
    """Return a machine-readable release diagnostic without mutable host paths."""

    from model.solver.registry import registry_hash

    identity = current_runtime_build_identity()
    return {
        **identity.provenance(),
        "verified": identity.verified,
        "registry_hash": registry_hash(),
        "python_version": platform.python_version(),
        "platform": platform.platform(),
        "python": {
            "implementation": platform.python_implementation(),
            "version": platform.python_version(),
            "major_minor": f"{sys.version_info.major}.{sys.version_info.minor}",
        },
        "platform_details": {
            "system": platform.system(),
            "machine": platform.machine(),
        },
    }


def _main() -> None:
    print(json.dumps(runtime_build_diagnostic(), indent=2, sort_keys=True))


if __name__ == "__main__":
    _main()


__all__ = [
    "BUILD_IDENTITY_SCHEMA",
    "BUILD_MODES",
    "BuildIdentityError",
    "DEVELOPMENT_COMMIT_SENTINEL",
    "ENGINE_VERSION",
    "RuntimeBuildIdentity",
    "RuntimeBuildMismatchError",
    "assert_runtime_build_matches",
    "current_runtime_build_identity",
    "is_git_sha",
    "runtime_build_diagnostic",
    "solver_build_id",
]
