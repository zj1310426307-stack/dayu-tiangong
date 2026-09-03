"""Versioned solver capability registry and pre-runtime compatibility gate."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

from model.hydraulic_1d.contracts import Hydraulic1DModel
from model.hydraulic_1d.errors import Hydraulic1DValidationError


CAPABILITY_MANIFEST = Path(__file__).with_name("hydraulic_engine_capabilities.yaml")


class CapabilityStatus(StrEnum):
    """Express evidence strength without reducing support to a permanent boolean."""

    VERIFIED_NATIVE = "VERIFIED_NATIVE"
    VERIFIED_EQUIVALENT = "VERIFIED_EQUIVALENT"
    EXPERIMENTAL = "EXPERIMENTAL"
    UNVERIFIED = "UNVERIFIED"
    UNSUPPORTED = "UNSUPPORTED"


class CapabilityExecutionPolicy(StrEnum):
    """Separate production acceptance from explicitly synthetic development runs."""

    PRODUCTION = "PRODUCTION"
    SYNTHETIC_NUMERICAL_ONLY = "SYNTHETIC_NUMERICAL_ONLY"


@dataclass(frozen=True, slots=True)
class SolverCapability:
    """Represent one version-bound capability and its acceptance evidence."""

    engine: str
    engine_version: str
    adapter_version: str
    feature: str
    status: CapabilityStatus
    reason: str
    benchmark_ids: tuple[str, ...]
    verified_at: str | None = None
    synthetic_status: str = "NOT_ACCEPTED"
    production_eligible: bool = False
    evidence_class: str = "NONE"
    supported_subset: tuple[str, ...] = ()
    unsupported_subset: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, object]:
        """Return the stable public/API representation."""

        return {
            "engine": self.engine,
            "engine_version": self.engine_version,
            "adapter_version": self.adapter_version,
            "feature": self.feature,
            "status": self.status.value,
            "production_status": self.status.value,
            "synthetic_status": self.synthetic_status,
            "production_eligible": self.production_eligible,
            "reason": self.reason,
            "benchmark_ids": list(self.benchmark_ids),
            "accepted_cases": list(self.benchmark_ids),
            "evidence_class": self.evidence_class,
            "supported_subset": list(self.supported_subset),
            "unsupported_subset": list(self.unsupported_subset),
            "verified_at": self.verified_at,
        }


@lru_cache(maxsize=1)
def capability_registry_payload() -> dict[str, Any]:
    """Load and validate the source-controlled manifest once per process."""

    payload = yaml.safe_load(CAPABILITY_MANIFEST.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise RuntimeError("hydraulic capability manifest must be an object")
    if payload.get("schema_version") != "dayu.hydraulic-engine-capabilities.v2":
        raise RuntimeError("unsupported hydraulic capability manifest schema")
    engines = payload.get("engines")
    if not isinstance(engines, list) or not engines:
        raise RuntimeError("hydraulic capability manifest requires engines")
    return payload


@lru_cache(maxsize=None)
def capabilities_for(engine: str, engine_version: str) -> tuple[SolverCapability, ...]:
    """Return one engine/version matrix and reject duplicate feature rows."""

    match = next(
        (
            item
            for item in capability_registry_payload()["engines"]
            if item.get("engine") == engine
            and item.get("engine_version") == engine_version
        ),
        None,
    )
    if match is None:
        return ()
    result: list[SolverCapability] = []
    seen: set[str] = set()
    for item in match.get("capabilities", []):
        feature = str(item.get("feature", "")).strip().upper()
        if not feature or feature in seen:
            raise RuntimeError("capability features must be non-empty and unique")
        seen.add(feature)
        production_status = CapabilityStatus(
            str(item.get("production_status", item.get("status")))
        )
        benchmark_ids = tuple(
            str(value)
            for value in item.get("accepted_cases", item.get("benchmark_ids", []))
        )
        synthetic_status = str(item.get("synthetic_status", "NOT_ACCEPTED"))
        if synthetic_status not in {"ACCEPTED", "PARTIAL", "NOT_ACCEPTED"}:
            raise RuntimeError("unsupported synthetic capability status")
        production_eligible = bool(
            item.get(
                "production_eligible",
                production_status
                in {
                    CapabilityStatus.VERIFIED_NATIVE,
                    CapabilityStatus.VERIFIED_EQUIVALENT,
                },
            )
        )
        if production_eligible and production_status not in {
            CapabilityStatus.VERIFIED_NATIVE,
            CapabilityStatus.VERIFIED_EQUIVALENT,
        }:
            raise RuntimeError("production eligibility requires a verified production status")
        if synthetic_status == "ACCEPTED" and not benchmark_ids:
            raise RuntimeError("accepted synthetic capability requires accepted cases")
        result.append(
            SolverCapability(
                engine=engine,
                engine_version=engine_version,
                adapter_version=str(match["adapter_version"]),
                feature=feature,
                status=production_status,
                reason=str(item.get("reason", "")),
                benchmark_ids=benchmark_ids,
                verified_at=(
                    str(item["verified_at"]) if item.get("verified_at") else None
                ),
                synthetic_status=synthetic_status,
                production_eligible=production_eligible,
                evidence_class=str(item.get("evidence_class", "NONE")),
                supported_subset=tuple(
                    str(value) for value in item.get("supported_subset", [])
                ),
                unsupported_subset=tuple(
                    str(value) for value in item.get("unsupported_subset", [])
                ),
            )
        )
    return tuple(result)


def required_capabilities(model: Hydraulic1DModel) -> tuple[str, ...]:
    """Derive model requirements without importing an engine adapter."""

    required = {"UNSTEADY_1D"}
    if len(model.branches) > 1:
        required.add("BRANCHED_NETWORK")
    if any(item.location == "lateral" for item in model.boundaries):
        required.add("LATERAL_INFLOW")
    upstream = sum(item.location == "upstream" for item in model.boundaries)
    if upstream > 1 and any(item.location == "lateral" for item in model.boundaries):
        required.add("COMBINED_BOUNDARIES")
    required.update(
        item.kind.upper() for item in model.structures if item.status == "active"
    )
    if any(item.node_type == "storage_connection" for item in model.nodes):
        required.add("CASIER")
    return tuple(sorted(required))


def capability_status_allowed(
    status: CapabilityStatus,
    *,
    execution_policy: CapabilityExecutionPolicy = CapabilityExecutionPolicy.PRODUCTION,
    development_mode: bool = False,
    production_mode: bool = True,
) -> bool:
    """Apply one fail-closed status gate without weakening production semantics."""

    verified = {
        CapabilityStatus.VERIFIED_NATIVE,
        CapabilityStatus.VERIFIED_EQUIVALENT,
    }
    if production_mode:
        return status in verified
    if (
        development_mode
        and execution_policy == CapabilityExecutionPolicy.SYNTHETIC_NUMERICAL_ONLY
    ):
        return status in verified | {CapabilityStatus.EXPERIMENTAL}
    return False


def compatibility_report(
    model: Hydraulic1DModel,
    *,
    engine: str,
    engine_version: str,
    execution_policy: CapabilityExecutionPolicy = CapabilityExecutionPolicy.PRODUCTION,
    development_mode: bool = False,
    production_mode: bool = True,
) -> dict[str, object]:
    """Report every incompatible feature so clients can block before submission."""

    matrix = {item.feature: item for item in capabilities_for(engine, engine_version)}
    required = required_capabilities(model)
    issues: list[dict[str, object]] = []
    for feature in required:
        capability = matrix.get(feature)
        if capability is None:
            issues.append(
                {
                    "feature": feature,
                    "status": CapabilityStatus.UNSUPPORTED.value,
                    "reason": "feature is absent from the versioned capability registry",
                    "structure_ids": [],
                }
            )
            continue
        if not capability_status_allowed(
            capability.status,
            execution_policy=execution_policy,
            development_mode=development_mode,
            production_mode=production_mode,
        ):
            issues.append(
                {
                    "feature": feature,
                    "status": capability.status.value,
                    "reason": capability.reason,
                    "structure_ids": [
                        item.id
                        for item in model.structures
                        if item.kind.upper() == feature and item.status == "active"
                    ],
                }
            )
    return {
        "engine": engine,
        "engine_version": engine_version,
        "execution_policy": execution_policy.value,
        "development_mode": development_mode,
        "production_mode": production_mode,
        "required_features": list(required),
        "compatible": not issues,
        "issues": issues,
    }


def enforce_compatibility(
    model: Hydraulic1DModel,
    *,
    engine: str,
    engine_version: str,
    execution_policy: CapabilityExecutionPolicy = CapabilityExecutionPolicy.PRODUCTION,
    development_mode: bool = False,
    production_mode: bool = True,
) -> None:
    """Fail closed with feature, structure, engine, and reason before runtime starts."""

    report = compatibility_report(
        model,
        engine=engine,
        engine_version=engine_version,
        execution_policy=execution_policy,
        development_mode=development_mode,
        production_mode=production_mode,
    )
    if report["compatible"]:
        return
    descriptions = [
        (
            f"{item['feature']}={item['status']}"
            f" structures={item['structure_ids']}: {item['reason']}"
        )
        for item in report["issues"]  # type: ignore[union-attr]
    ]
    raise Hydraulic1DValidationError(
        "MODEL_ENGINE_INCOMPATIBLE",
        f"{engine} {engine_version} cannot run model; " + "; ".join(descriptions),
        field_path="capabilities",
    )
