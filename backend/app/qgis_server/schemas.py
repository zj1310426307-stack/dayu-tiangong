"""Public contracts for the private QGIS Server runtime boundary."""

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict


class HealthEvidence(BaseModel):
    """Report one independently verifiable runtime condition."""

    model_config = ConfigDict(extra="forbid")
    passed: bool
    evidence: str


class QgisServerHealthResponse(BaseModel):
    """Keep process, project, database, WMS, and isolation evidence separate."""

    model_config = ConfigDict(extra="forbid")
    status: Literal["healthy", "degraded"]
    process: HealthEvidence
    project_valid: HealthEvidence
    manifest_revision: str | None
    database_read: HealthEvidence
    wms_capabilities: HealthEvidence
    dataset_version_isolation: HealthEvidence
    details: dict[str, Any]
