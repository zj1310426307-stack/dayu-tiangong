"""Strong native platform contract for ``dayu.model-input.v4``."""

from __future__ import annotations

from typing import Annotated, Any, Literal, Mapping, Self

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, ValidationError, model_validator

from model.api.v4_lite import (
    BySectionInitialState,
    CoordinateReference,
    DatasetVersionIdentity,
    HydraulicExternalPumpInput,
    InitialState,
    V4LiteBoundary,
    V4LiteRiver,
    V4LiteSection,
    V4LiteSolver,
    V4LiteStructures,
)
from model.core.errors import HydraulicInputError
from model.provenance import CANONICALIZATION_ID
from model.solver.registry import (
    D1_CAPABILITY,
    D1_CAPABILITY_ID,
    D1_KNOWN_LIMITATIONS,
    D1_RUNTIME_ADAPTER_ID,
    D1_SOLVER_ID,
    MODEL_INPUT_V4,
    registry_hash,
    resolve_solver,
)


NonBlankText = Annotated[str, StringConstraints(strict=True, min_length=1)]
Sha256 = Annotated[str, StringConstraints(strict=True, pattern=r"^[0-9a-f]{64}$")]
PositiveId = Annotated[int, Field(strict=True, gt=0)]


class StrictPlatformModel(BaseModel):
    """Keep the platform snapshot immutable and reject unregistered fields."""

    model_config = ConfigDict(extra="forbid", frozen=True)


class SolverSelection(StrictPlatformModel):
    """Select the only D2 native v4 solver/capability/adapter tuple."""

    solver_id: Literal[D1_SOLVER_ID]
    capability_id: Literal[D1_CAPABILITY_ID]
    runtime_adapter_id: Literal[D1_RUNTIME_ADAPTER_ID]


class SimulationCaseIdentity(StrictPlatformModel):
    """Identify the authoritative case without copying mutable case contents."""

    id: PositiveId
    name: NonBlankText


class HydraulicNetworkIdentity(StrictPlatformModel):
    """Identify the single hydraulic Network that owns the D1 Branch."""

    id: PositiveId
    code: NonBlankText


class HydraulicReachIdentity(StrictPlatformModel):
    """Freeze one ordered reach inside the single supported Branch."""

    id: PositiveId
    branch_id: PositiveId
    reach_code: NonBlankText
    start_chainage_m: Annotated[float, Field(ge=0.0)]
    end_chainage_m: Annotated[float, Field(gt=0.0)]

    @model_validator(mode="after")
    def validate_chainage(self) -> Self:
        """Require a positive, directed reach interval."""

        if self.end_chainage_m <= self.start_chainage_m:
            raise ValueError("reach end_chainage_m must exceed start_chainage_m")
        return self


class ProfileIdentity(StrictPlatformModel):
    """Repeat the authoritative Profile identity independently of runtime geometry."""

    id: PositiveId
    cross_section_id: PositiveId
    profile_hash: Sha256
    profile_hash_trust: Literal["persisted/import-validated"] = (
        "persisted/import-validated"
    )


class ControlPlanIdentity(StrictPlatformModel):
    """Bind Gate/Pump commands to one immutable Dispatch Plan snapshot."""

    id: PositiveId
    frozen_snapshot_hash: Sha256
    policy_id: Literal["d1-gate-pump-control-v1"]


class ValidationPolicy(StrictPlatformModel):
    """Freeze the D1 validation policy separately from numerical settings."""

    validation_policy_version: Literal["v4-lite-7"]
    capability_id: Literal[D1_CAPABILITY_ID]
    water_balance_tolerance: Annotated[float, Field(strict=True, gt=0.0, le=1.0e-10)]


class PlatformProvenance(StrictPlatformModel):
    """Freeze non-recursive engine, registry, and canonicalization identities."""

    engine_version: NonBlankText
    engine_commit: NonBlankText
    canonicalization_id: Literal[CANONICALIZATION_ID]
    registry_hash: Sha256


class ModelInputV4(StrictPlatformModel):
    """Authoritative D2 platform input projected only through the registered D1 adapter."""

    schema_version: Literal[MODEL_INPUT_V4]
    solver_selection: SolverSelection
    dataset_version: DatasetVersionIdentity
    simulation_case: SimulationCaseIdentity
    coordinate_reference: CoordinateReference
    network: HydraulicNetworkIdentity
    branches: tuple[V4LiteRiver, ...] = Field(min_length=1, max_length=1)
    reaches: tuple[HydraulicReachIdentity, ...] = Field(min_length=1)
    cross_sections: tuple[V4LiteSection, ...] = Field(min_length=3)
    cross_section_profiles: tuple[ProfileIdentity, ...] = Field(min_length=3)
    initial_state: InitialState
    boundaries: V4LiteBoundary
    structures: V4LiteStructures
    control_plan: ControlPlanIdentity
    numerical_policy: V4LiteSolver
    validation: ValidationPolicy
    provenance: PlatformProvenance
    capability_scope: tuple[NonBlankText, ...] = Field(
        default_factory=lambda: D1_CAPABILITY.scope,
        min_length=1,
    )
    capability_exclusions: tuple[NonBlankText, ...] = Field(
        default_factory=lambda: D1_CAPABILITY.exclusions,
        min_length=1,
    )
    case_notes: tuple[NonBlankText, ...] = ()
    known_limitations: tuple[NonBlankText, ...] = Field(
        default_factory=lambda: D1_KNOWN_LIMITATIONS,
        min_length=1,
    )

    @model_validator(mode="after")
    def validate_native_d1_scope(self) -> Self:
        """Close cross-object identities before a runtime projection can be produced."""

        resolve_solver(
            self.schema_version,
            solver_id=self.solver_selection.solver_id,
            capability_id=self.solver_selection.capability_id,
            runtime_adapter_id=self.solver_selection.runtime_adapter_id,
        )
        if self.provenance.registry_hash != registry_hash():
            raise ValueError("platform solver registry hash does not match this runtime")
        if self.validation.capability_id != self.solver_selection.capability_id:
            raise ValueError("validation capability does not match solver selection")
        if self.validation.water_balance_tolerance != self.numerical_policy.water_balance_tolerance:
            raise ValueError("validation and numerical water-balance tolerances disagree")
        if self.capability_scope != D1_CAPABILITY.scope:
            raise ValueError("capability scope does not match the solver registry")
        if self.capability_exclusions != D1_CAPABILITY.exclusions:
            raise ValueError("capability exclusions do not match the solver registry")
        if self.known_limitations != D1_KNOWN_LIMITATIONS:
            raise ValueError("known limitations do not match the solver registry")
        branch = self.branches[0]
        if branch.network_id != self.network.id:
            raise ValueError("Branch does not belong to the selected hydraulic Network")
        if any(item.branch_id != branch.branch_id for item in self.reaches):
            raise ValueError("all reaches must belong to the single D1 Branch")
        if any(item.branch_id != branch.branch_id for item in self.cross_sections):
            raise ValueError("all cross sections must belong to the single D1 Branch")
        section_ids = {item.section_id for item in self.cross_sections}
        if len(section_ids) != len(self.cross_sections):
            raise ValueError("cross-section identities must be unique")
        profile_pairs = {
            (item.cross_section_id, item.id, item.profile_hash)
            for item in self.cross_section_profiles
        }
        section_pairs = {
            (item.section_id, item.profile_id, item.profile_hash)
            for item in self.cross_sections
        }
        if profile_pairs != section_pairs:
            raise ValueError("Profile identities do not match cross-section geometry")
        if not isinstance(self.initial_state, BySectionInitialState):
            raise ValueError("native D1 v4 requires an explicit by-section initial state")
        if len(self.structures.gates) != 1 or len(self.structures.pumps) != 1:
            raise ValueError("native D1 v4 requires exactly one Gate and one Pump")
        if not isinstance(self.structures.pumps[0], HydraulicExternalPumpInput):
            raise ValueError("native D1 v4 requires one hydraulic external Q-H Pump")
        return self


def parse_model_input_v4(payload: Mapping[str, Any]) -> ModelInputV4:
    """Parse one untrusted JSON-like platform snapshot with actionable failure text."""

    if not isinstance(payload, Mapping):
        raise HydraulicInputError("dayu.model-input.v4 payload must be an object")
    try:
        return ModelInputV4.model_validate(payload)
    except ValidationError as exc:
        raise HydraulicInputError(
            f"dayu.model-input.v4 validation failed: {exc}"
        ) from exc
