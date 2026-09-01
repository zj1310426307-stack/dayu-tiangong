"""Isolated filesystem workspaces for external MASCARET jobs."""

from __future__ import annotations

from dataclasses import dataclass
from json import dumps, loads
from os import replace
from pathlib import Path
from re import sub
from shutil import rmtree
from time import monotonic, sleep
from typing import Any
from uuid import uuid4

from model.hydraulic_1d.errors import Hydraulic1DExecutionError


WORKSPACE_MARKER_FILENAME = ".dayu-mascaret-workspace.json"
WORKSPACE_MARKER_SCHEMA = "dayu.mascaret-workspace.v1"


def _safe_token(value: str) -> str:
    """Convert a platform identity into a bounded, non-traversing path token."""

    token = sub(r"[^A-Za-z0-9_.-]+", "-", value).strip(".-")
    # The UUID and marker carry authority; short labels keep Windows paths below
    # MAX_PATH even when the configured project workspace root is already long.
    return token[:24] or "job"


def mascaret_attempt_job_id(
    *,
    task_id: int,
    execution_attempt_count: int,
    execution_token: str,
) -> str:
    """Bind a runtime workspace identity to the exact database execution lease."""

    return f"task-{task_id}-token-{execution_token}-attempt-{execution_attempt_count}"


def _marker_path(workspace: Path) -> Path:
    """Return the marker path only for a concrete, non-symlink job directory."""

    if workspace.is_symlink() or not workspace.is_dir():
        raise Hydraulic1DExecutionError("MASCARET workspace is absent or is a symlink")
    return workspace / WORKSPACE_MARKER_FILENAME


def _write_marker(workspace: Path, payload: dict[str, Any]) -> None:
    """Atomically replace one workspace marker inside the owned directory."""

    marker = _marker_path(workspace)
    temporary = workspace / f".marker-{uuid4().hex}.tmp"
    try:
        temporary.write_text(
            dumps(payload, ensure_ascii=True, indent=2, sort_keys=True) + "\n",
            encoding="ascii",
        )
        replace(temporary, marker)
    finally:
        temporary.unlink(missing_ok=True)


def read_workspace_marker(workspace: Path) -> dict[str, Any]:
    """Read and validate the immutable ownership fields of a workspace marker."""

    marker = _marker_path(workspace)
    if marker.is_symlink() or not marker.is_file():
        raise Hydraulic1DExecutionError(
            "MASCARET workspace marker is missing or unsafe"
        )
    try:
        payload = loads(marker.read_text(encoding="ascii", errors="strict"))
    except (OSError, UnicodeError, ValueError) as exc:
        raise Hydraulic1DExecutionError(
            f"MASCARET workspace marker cannot be read: {exc}"
        ) from exc
    if not isinstance(payload, dict):
        raise Hydraulic1DExecutionError("MASCARET workspace marker must be an object")
    expected = {
        "schema_version": WORKSPACE_MARKER_SCHEMA,
        "workspace_name": workspace.name,
    }
    if any(payload.get(key) != value for key, value in expected.items()):
        raise Hydraulic1DExecutionError("MASCARET workspace marker ownership mismatch")
    if not isinstance(payload.get("job_id"), str) or not payload["job_id"]:
        raise Hydraulic1DExecutionError(
            "MASCARET workspace marker lacks a job identity"
        )
    return payload


def update_workspace_marker(workspace: Path, **changes: Any) -> dict[str, Any]:
    """Update runtime state while preserving the marker's ownership identity."""

    payload = read_workspace_marker(workspace)
    forbidden = {"schema_version", "workspace_name", "simulation_id", "job_id"}
    if forbidden.intersection(changes):
        raise Hydraulic1DExecutionError(
            "MASCARET marker ownership fields are immutable"
        )
    payload.update(changes)
    _write_marker(workspace, payload)
    return payload


def find_attempt_workspaces(root: Path, *, job_id: str) -> list[Path]:
    """Find only direct child workspaces whose validated marker names this attempt."""

    resolved_root = root.expanduser().resolve()
    if not resolved_root.is_dir():
        return []
    matches: list[Path] = []
    for child in resolved_root.iterdir():
        if child.is_symlink() or not child.is_dir():
            continue
        resolved = child.resolve()
        if resolved.parent != resolved_root:
            continue
        try:
            marker = read_workspace_marker(resolved)
        except Hydraulic1DExecutionError:
            continue
        if marker.get("job_id") == job_id:
            matches.append(resolved)
    return matches


def cleanup_verified_workspace(root: Path, workspace: Path, *, job_id: str) -> None:
    """Delete one marker-proven attempt only after runtime ownership is released."""

    resolved_root = root.expanduser().resolve()
    resolved = workspace.resolve()
    if (
        workspace.is_symlink()
        or resolved == resolved_root
        or resolved.parent != resolved_root
    ):
        raise Hydraulic1DExecutionError("refusing to remove an unverified workspace")
    marker = read_workspace_marker(resolved)
    if marker.get("job_id") != job_id:
        raise Hydraulic1DExecutionError(
            "workspace belongs to another execution attempt"
        )
    if marker.get("state") not in {"created", "released", "recovered", "retained"}:
        raise Hydraulic1DExecutionError(
            "refusing to remove a workspace whose external runtime is not released"
        )
    deadline = monotonic() + 2.0
    while True:
        try:
            rmtree(resolved)
            return
        except FileNotFoundError:
            return
        except OSError:
            # A terminated Windows process can briefly retain its current-directory
            # handle after the exact Job Object has been proven stopped. The target
            # was marker-verified above, so retry only this already-authorized path.
            if monotonic() >= deadline:
                raise
            sleep(0.05)


def prune_retained_workspaces(root: Path, *, maximum: int) -> None:
    """Bound retained diagnostics while deleting only verified released attempts."""

    resolved_root = root.expanduser().resolve()
    if not resolved_root.is_dir():
        return
    retained: list[tuple[float, Path, str]] = []
    for child in resolved_root.iterdir():
        if (
            child.is_symlink()
            or not child.is_dir()
            or child.resolve().parent != resolved_root
        ):
            continue
        try:
            marker = read_workspace_marker(child.resolve())
        except Hydraulic1DExecutionError:
            continue
        if marker.get("state") != "retained":
            continue
        retained.append((child.stat().st_mtime, child.resolve(), str(marker["job_id"])))
    retained.sort(key=lambda item: item[0], reverse=True)
    for _, path, job_id in retained[maximum:]:
        cleanup_verified_workspace(resolved_root, path, job_id=job_id)


@dataclass(frozen=True, slots=True)
class MascaretJobWorkspace:
    """Own one unique writable directory for exactly one simulation job."""

    root: Path
    path: Path

    @classmethod
    def create(
        cls, root: Path, *, simulation_id: str, job_id: str
    ) -> "MascaretJobWorkspace":
        """Create an unshared directory and prove it remains below the configured root."""

        resolved_root = root.expanduser().resolve()
        resolved_root.mkdir(parents=True, exist_ok=True)
        name = f"{_safe_token(simulation_id)}-{_safe_token(job_id)}-{uuid4().hex}"
        candidate = (resolved_root / name).resolve()
        if candidate.parent != resolved_root:
            raise Hydraulic1DExecutionError("job workspace escaped its configured root")
        candidate.mkdir(mode=0o700, exist_ok=False)
        try:
            _write_marker(
                candidate,
                {
                    "schema_version": WORKSPACE_MARKER_SCHEMA,
                    "workspace_name": candidate.name,
                    "simulation_id": simulation_id,
                    "job_id": job_id,
                    "state": "created",
                    "runtime_handle": None,
                },
            )
        except Exception:
            rmtree(candidate)
            raise
        return cls(root=resolved_root, path=candidate)

    def cleanup(self) -> None:
        """Remove only this proven job directory after execution and result parsing."""

        if self.path.exists():
            marker = read_workspace_marker(self.path)
            cleanup_verified_workspace(
                self.root,
                self.path,
                job_id=str(marker["job_id"]),
            )

    def retain(
        self,
        retention_class: str,
        *,
        error_code: str | None = None,
        error_message: str | None = None,
        maximum: int = 20,
    ) -> None:
        """Keep bounded diagnostics only after the external runtime is released."""

        marker = read_workspace_marker(self.path)
        if marker.get("state") not in {"created", "released", "recovered"}:
            raise Hydraulic1DExecutionError(
                "cannot retain a workspace whose external runtime is not released"
            )
        update_workspace_marker(
            self.path,
            state="retained",
            retention_class=retention_class,
            error_code=error_code,
            error_message=(error_message or "")[-4000:] or None,
        )
        prune_retained_workspaces(self.root, maximum=maximum)
