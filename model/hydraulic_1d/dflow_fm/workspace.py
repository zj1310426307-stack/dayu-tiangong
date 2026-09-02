"""Per-job filesystem isolation for D-Flow FM and D-RTC native artifacts."""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from json import JSONDecodeError, dumps, loads
from pathlib import Path
from re import fullmatch
from typing import Any, Literal

from model.hydraulic_1d.errors import Hydraulic1DExecutionError


DFLOW_WORKSPACE_SCHEMA = "dayu.dflow-workspace.v1"
DFLOW_WORKSPACE_MARKER = "workspace.json"
WorkspaceArea = Literal["input", "control", "output", "logs", "metadata"]
WORKSPACE_AREAS: tuple[WorkspaceArea, ...] = (
    "input",
    "control",
    "output",
    "logs",
    "metadata",
)
_WINDOWS_RESERVED = {
    "aux",
    "clock$",
    "con",
    "nul",
    "prn",
    *(f"com{index}" for index in range(1, 10)),
    *(f"lpt{index}" for index in range(1, 10)),
}


def _safe_identifier(value: str, *, field: str) -> str:
    """Require a collision-free path component instead of sanitizing user input."""

    if (
        not isinstance(value, str)
        or fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,95}", value) is None
        or value in {".", ".."}
        or value.split(".", 1)[0].lower() in _WINDOWS_RESERVED
    ):
        raise Hydraulic1DExecutionError(
            f"{field} is not a safe workspace identifier",
            code="DFLOW_WORKSPACE_INVALID",
        )
    return value


def _ensure_plain_directory(path: Path, *, label: str) -> Path:
    """Resolve a directory only after rejecting symlink-based ownership changes."""

    if path.is_symlink() or not path.is_dir():
        raise Hydraulic1DExecutionError(
            f"{label} is absent or is a symlink",
            code="DFLOW_WORKSPACE_INVALID",
        )
    return path.resolve()


@dataclass(frozen=True, slots=True)
class DFlowJobWorkspace:
    """Own one ``simulation_id/job_id`` tree and its five native artifact areas."""

    root: Path
    path: Path
    simulation_id: str
    job_id: str

    @property
    def input_dir(self) -> Path:
        """Return the solver-input directory for this exact job."""

        return self.path / "input"

    @property
    def control_dir(self) -> Path:
        """Return the DIMR/D-RTC control directory for this exact job."""

        return self.path / "control"

    @property
    def output_dir(self) -> Path:
        """Return the solver-output directory for this exact job."""

        return self.path / "output"

    @property
    def logs_dir(self) -> Path:
        """Return the process-log directory for this exact job."""

        return self.path / "logs"

    @property
    def metadata_dir(self) -> Path:
        """Return the evidence and ownership metadata directory."""

        return self.path / "metadata"

    @property
    def marker_path(self) -> Path:
        """Return the immutable ownership marker within ``metadata``."""

        return self.metadata_dir / DFLOW_WORKSPACE_MARKER

    @property
    def owner_token(self) -> str:
        """Derive a non-secret immutable token for container ownership labels."""

        identity = f"{self.simulation_id}\x00{self.job_id}\x00{self.path.name}"
        return sha256(identity.encode("utf-8")).hexdigest()

    @classmethod
    def create(
        cls,
        root: Path,
        *,
        simulation_id: str,
        job_id: str,
    ) -> "DFlowJobWorkspace":
        """Create a non-shared job tree and prove it remains under its root."""

        simulation_id = _safe_identifier(simulation_id, field="simulation_id")
        job_id = _safe_identifier(job_id, field="job_id")
        configured_root = root.expanduser()
        if configured_root.exists() and configured_root.is_symlink():
            raise Hydraulic1DExecutionError(
                "workspace root must not be a symlink",
                code="DFLOW_WORKSPACE_INVALID",
            )
        configured_root.mkdir(parents=True, exist_ok=True)
        resolved_root = _ensure_plain_directory(configured_root, label="workspace root")

        simulation_path = resolved_root / simulation_id
        simulation_path.mkdir(mode=0o700, exist_ok=True)
        resolved_simulation = _ensure_plain_directory(
            simulation_path, label="simulation workspace"
        )
        if resolved_simulation.parent != resolved_root:
            raise Hydraulic1DExecutionError(
                "simulation workspace escaped its configured root",
                code="DFLOW_WORKSPACE_INVALID",
            )

        job_path = resolved_simulation / job_id
        try:
            job_path.mkdir(mode=0o700, exist_ok=False)
        except FileExistsError as exc:
            raise Hydraulic1DExecutionError(
                "job workspace already exists and cannot be shared",
                code="DFLOW_WORKSPACE_CONFLICT",
            ) from exc
        resolved_job = _ensure_plain_directory(job_path, label="job workspace")
        if resolved_job.parent != resolved_simulation:
            raise Hydraulic1DExecutionError(
                "job workspace escaped its simulation root",
                code="DFLOW_WORKSPACE_INVALID",
            )
        for area in WORKSPACE_AREAS:
            (resolved_job / area).mkdir(mode=0o700, exist_ok=False)

        workspace = cls(
            root=resolved_root,
            path=resolved_job,
            simulation_id=simulation_id,
            job_id=job_id,
        )
        marker: dict[str, Any] = {
            "schema_version": DFLOW_WORKSPACE_SCHEMA,
            "simulation_id": simulation_id,
            "job_id": job_id,
            "workspace_name": resolved_job.name,
            "owner_token": workspace.owner_token,
        }
        workspace.marker_path.write_text(
            dumps(marker, ensure_ascii=True, indent=2, sort_keys=True) + "\n",
            encoding="ascii",
        )
        return workspace

    @classmethod
    def open(cls, path: Path) -> "DFlowJobWorkspace":
        """Re-open a job only when its marker proves directory ownership."""

        resolved_job = _ensure_plain_directory(path, label="job workspace")
        marker_path = resolved_job / "metadata" / DFLOW_WORKSPACE_MARKER
        if marker_path.is_symlink() or not marker_path.is_file():
            raise Hydraulic1DExecutionError(
                "D-Flow workspace marker is missing or unsafe",
                code="DFLOW_WORKSPACE_INVALID",
            )
        try:
            payload = loads(marker_path.read_text(encoding="ascii", errors="strict"))
        except (OSError, UnicodeError, JSONDecodeError) as exc:
            raise Hydraulic1DExecutionError(
                f"D-Flow workspace marker cannot be read: {exc}",
                code="DFLOW_WORKSPACE_INVALID",
            ) from exc
        if not isinstance(payload, dict):
            raise Hydraulic1DExecutionError(
                "D-Flow workspace marker must be an object",
                code="DFLOW_WORKSPACE_INVALID",
            )
        simulation_id = _safe_identifier(
            payload.get("simulation_id"), field="simulation_id"
        )
        job_id = _safe_identifier(payload.get("job_id"), field="job_id")
        candidate = cls(
            root=resolved_job.parent.parent,
            path=resolved_job,
            simulation_id=simulation_id,
            job_id=job_id,
        )
        expected = {
            "schema_version": DFLOW_WORKSPACE_SCHEMA,
            "workspace_name": resolved_job.name,
            "owner_token": candidate.owner_token,
        }
        if any(payload.get(key) != value for key, value in expected.items()):
            raise Hydraulic1DExecutionError(
                "D-Flow workspace marker ownership mismatch",
                code="DFLOW_WORKSPACE_INVALID",
            )
        if resolved_job.parent.name != simulation_id or resolved_job.name != job_id:
            raise Hydraulic1DExecutionError(
                "D-Flow workspace path does not match its marker",
                code="DFLOW_WORKSPACE_INVALID",
            )
        for area in WORKSPACE_AREAS:
            _ensure_plain_directory(resolved_job / area, label=f"{area} directory")
        return candidate

    def resolve_in(self, area: WorkspaceArea, relative_path: str | Path) -> Path:
        """Resolve one artifact below an allowed area and reject path traversal."""

        if area not in WORKSPACE_AREAS:
            raise Hydraulic1DExecutionError(
                f"unknown D-Flow workspace area: {area}",
                code="DFLOW_WORKSPACE_INVALID",
            )
        relative = Path(relative_path)
        if relative.is_absolute() or any(
            part in {"", ".", ".."} for part in relative.parts
        ):
            raise Hydraulic1DExecutionError(
                "artifact path must be a non-traversing relative path",
                code="DFLOW_WORKSPACE_INVALID",
            )
        base = _ensure_plain_directory(self.path / area, label=f"{area} directory")
        candidate = (base / relative).resolve()
        if not candidate.is_relative_to(base):
            raise Hydraulic1DExecutionError(
                "artifact path escaped its D-Flow workspace area",
                code="DFLOW_WORKSPACE_INVALID",
            )
        if candidate.exists() and candidate.is_symlink():
            raise Hydraulic1DExecutionError(
                "artifact path must not be a symlink",
                code="DFLOW_WORKSPACE_INVALID",
            )
        return candidate

    def validate(self) -> "DFlowJobWorkspace":
        """Re-read the marker before every external launch to detect replacement."""

        observed = self.open(self.path)
        if observed != self:
            raise Hydraulic1DExecutionError(
                "D-Flow workspace identity changed after creation",
                code="DFLOW_WORKSPACE_INVALID",
            )
        return self


__all__ = [
    "DFLOW_WORKSPACE_MARKER",
    "DFLOW_WORKSPACE_SCHEMA",
    "WORKSPACE_AREAS",
    "DFlowJobWorkspace",
    "WorkspaceArea",
]
