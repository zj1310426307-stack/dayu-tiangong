"""Source-controlled acceptance gate for the pinned DIMR/FBC runtime.

The registry is evidence, not a configurable feature flag.  Acceptance binds
the exact container digest, runtime-manifest bytes, compiler version and the
small set of native synthetic cases reviewed for this release.
"""

from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


CONTROLLED_RUNTIME_ACCEPTANCE_SCHEMA = "dayu.controlled-runtime-acceptance.v2"
CONTROLLED_RUNTIME_ACCEPTANCE_FILE = (
    Path(__file__).resolve().parents[2]
    / "hydraulic_1d"
    / "dflow_fm"
    / "acceptance"
    / "DIMRset_2026.02"
    / "controlled-runtime-acceptance.json"
)
RUNTIME_PROVENANCE_FILE = (
    CONTROLLED_RUNTIME_ACCEPTANCE_FILE.parent / "runtime-provenance.json"
)


class ControlledAcceptanceCase(BaseModel):
    """One compact, hash-bound acceptance result."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    case_id: str = Field(min_length=1, max_length=64)
    status: Literal["PASS"]
    evidence_class: Literal["SYNTHETIC_NUMERICAL_ONLY"]
    artifact_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    artifact_path: str | None = Field(
        default=None,
        pattern=r"^evidence/[a-z0-9-]+\.json$",
    )


class ControlledRuntimeAcceptance(BaseModel):
    """Reviewed trust root for the only enabled D-RTC subset."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["dayu.controlled-runtime-acceptance.v2"]
    engine_id: Literal["d-flow-fm"]
    engine_version: Literal["DIMRset_2026.02"]
    runtime_manifest_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    container_image_digest: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    fbc_version: Literal["1.6.1"]
    compiler_version: Literal["dayu.drtc-compiler.v3"]
    supported_rule_subset: tuple[str, ...]
    unsupported_features: tuple[str, ...]
    official_cases: tuple[ControlledAcceptanceCase, ...]
    dayu_cases: tuple[ControlledAcceptanceCase, ...]
    verification_date: str
    evidence_class: Literal["SYNTHETIC_NUMERICAL_ONLY"]
    real_engineering_validation: Literal[False]
    real_equipment_command: Literal[False]
    plc_scada_connected: Literal[False]


def _file_sha256(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


def controlled_runtime_acceptance() -> ControlledRuntimeAcceptance:
    """Load and verify the committed acceptance registry fail closed."""

    payload = json.loads(CONTROLLED_RUNTIME_ACCEPTANCE_FILE.read_text(encoding="utf-8"))
    acceptance = ControlledRuntimeAcceptance.model_validate(payload)
    if _file_sha256(RUNTIME_PROVENANCE_FILE) != acceptance.runtime_manifest_sha256:
        raise ValueError("controlled runtime manifest hash does not match acceptance")
    official_ids = {item.case_id for item in acceptance.official_cases}
    dayu_ids = {item.case_id for item in acceptance.dayu_cases}
    if official_ids != {"OFFICIAL-DFLOW-01", "OFFICIAL-DFLOW-FBC-10"}:
        raise ValueError("controlled runtime official case set is incomplete")
    if dayu_ids != {
        "DF01",
        "DRTC-S01",
        "G01",
        "G02",
        "G03",
        "PUMP01",
        "PUMP02",
        "GP01",
        "GP02",
        "GP03",
        "L01",
    }:
        raise ValueError("controlled runtime Dayu case set is incomplete")
    for case in (*acceptance.official_cases, *acceptance.dayu_cases):
        if case.artifact_path is None:
            continue
        artifact = CONTROLLED_RUNTIME_ACCEPTANCE_FILE.parent / case.artifact_path
        if _file_sha256(artifact) != case.artifact_sha256:
            raise ValueError(f"controlled runtime artifact hash drifted: {case.case_id}")
        evidence = json.loads(artifact.read_text(encoding="utf-8"))
        if (
            evidence.get("case_id") != case.case_id
            or evidence.get("status") != "PASS"
            or evidence.get("evidence_class") != "SYNTHETIC_NUMERICAL_ONLY"
            or evidence.get("real_engineering_validation") is not False
            or evidence.get("real_equipment_command") is not False
            or evidence.get("plc_scada_connected") is not False
        ):
            raise ValueError(f"controlled runtime artifact semantics drifted: {case.case_id}")
    return acceptance


def controlled_runtime_accepted() -> bool:
    """Return false for any missing, malformed, or drifted acceptance input."""

    try:
        controlled_runtime_acceptance()
    except (OSError, ValueError, json.JSONDecodeError):
        return False
    return True


__all__ = [
    "CONTROLLED_RUNTIME_ACCEPTANCE_FILE",
    "CONTROLLED_RUNTIME_ACCEPTANCE_SCHEMA",
    "ControlledRuntimeAcceptance",
    "controlled_runtime_acceptance",
    "controlled_runtime_accepted",
]
