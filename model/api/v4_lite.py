"""Strict, framework-neutral contract for ``dayu.model-input.v4-lite``.

The contract is intentionally narrower than the authoritative hydraulic data
model.  It admits one confirmed Branch and only the numerical features that the
Saint-Venant MVP can execute without guessing identities, initial conditions,
boundary coverage, or structure placement.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from typing import Annotated, Any, Literal, Self

from pydantic import (
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    StringConstraints,
    ValidationError,
    field_validator,
    model_validator,
)

from model.core.errors import HydraulicInputError
from model.geometry.sections import TabulatedSectionGeometry


MODEL_INPUT_V4_LITE = "dayu.model-input.v4-lite"
V4_LITE_SOLVER_TUPLE = (
    MODEL_INPUT_V4_LITE,
    "saint-venant",
    "finite-volume-hll",
    "ssp-rk2",
)

LEGACY_V4_LITE_POLICY = (
    "absolute-prismatic-v1",
    "hydrostatic-reconstruction-v1",
    "profile-minimum-elevation-v1",
    "standard-v1",
    "zero-gradient-companion-v1",
    "nearest-section-cell-face-v1",
)
B2_STANDARD_POLICY = (
    "relative-prismatic-linear-bed-v1",
    "hydrostatic-reconstruction-v1",
    "profile-minimum-elevation-v1",
    "standard-v1",
    "subcritical-characteristic-v1",
    "nearest-section-cell-face-v1",
)
B2_UNIFORM_MANNING_POLICY = (
    "relative-prismatic-linear-bed-v1",
    "hydrostatic-reconstruction-v1",
    "profile-minimum-elevation-v1",
    "uniform-manning-reference-v1",
    "subcritical-characteristic-v1",
    "nearest-section-cell-face-v1",
)
B2_NONPRISMATIC_LAKE_POLICY = (
    "nonprismatic-section-linear-path-v1",
    "hydraulic-function-linear-face-v1",
    "profile-minimum-elevation-v1",
    "standard-v1",
    "subcritical-characteristic-v1",
    "nearest-section-cell-face-v1",
)
C1_NONPRISMATIC_MOVING_POLICY = (
    "nonprismatic-frictionless-energy-reference-v1",
    "hydraulic-function-linear-face-v1",
    "profile-minimum-elevation-v1",
    "standard-v1",
    "subcritical-characteristic-v1",
    "nearest-section-cell-face-v1",
)
C2_BRACKETED_EVENT_POLICY = (
    "absolute-prismatic-v1",
    "hydrostatic-reconstruction-v1",
    "profile-minimum-elevation-v1",
    "standard-v1",
    "subcritical-characteristic-v1",
    "nearest-section-cell-face-v1",
)
_VERSIONED_POLICY_FIELDS = frozenset(
    {
        "geometry_policy",
        "geometry_source",
        "bed_elevation_source",
        "equilibrium_policy",
        "boundary_closure",
        "boundary_spatial_support",
    }
)
_EVENT_POLICY_FIELDS = frozenset(
    {
        "structure_event_policy",
        "event_time_tolerance_seconds",
        "maximum_event_refinements",
        "control_spatial_support",
    }
)
_POLICY_RELATIVE_TOLERANCE = 1.0e-10
_POLICY_ABSOLUTE_TOLERANCE = 1.0e-12
_ENERGY_HEAD_ABSOLUTE_TOLERANCE_M = 1.0e-10
_MOVING_REFERENCE_MAXIMUM_FROUDE = 0.8
_MOVING_REFERENCE_DRY_DEPTH_FACTOR = 100.0
_MOVING_REFERENCE_MINIMUM_TRANSIT_FRACTION = 0.02
_GRAVITY_M_S2 = 9.81


def _finite_number(value: Any) -> float:
    """Accept JSON integers/floats, reject booleans, strings, NaN, and infinity."""

    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("value must be a JSON number")
    number = float(value)
    if not math.isfinite(number):
        raise ValueError("value must be finite")
    return number


def _policy_close(left: float, right: float) -> bool:
    """Compare frozen engineering values with one strict documented tolerance."""

    return math.isclose(
        left,
        right,
        rel_tol=_POLICY_RELATIVE_TOLERANCE,
        abs_tol=_POLICY_ABSOLUTE_TOLERANCE,
    )


def _absolute_stage_close(left: float, right: float) -> bool:
    """Compare absolute water levels without datum-dependent relative slack."""

    return math.isclose(
        left,
        right,
        rel_tol=0.0,
        abs_tol=_POLICY_ABSOLUTE_TOLERANCE,
    )


def _c1_reference_close(left: float, right: float) -> bool:
    """Compare a C1 reference scalar with no magnitude-relative slack."""

    tolerance = max(
        _POLICY_ABSOLUTE_TOLERANCE,
        8.0 * math.ulp(abs(left)),
        8.0 * math.ulp(abs(right)),
    )
    return math.isclose(left, right, rel_tol=0.0, abs_tol=tolerance)


def _energy_head_close(left: float, right: float) -> bool:
    """Compare energy heads with fixed tolerance plus datum-scale ULP guard."""

    tolerance = max(
        _ENERGY_HEAD_ABSOLUTE_TOLERANCE_M,
        8.0 * math.ulp(abs(left)),
        8.0 * math.ulp(abs(right)),
    )
    return math.isclose(left, right, rel_tol=0.0, abs_tol=tolerance)


def _require_policy_constant(values: tuple[float, ...], label: str) -> float:
    """Return one constant policy value or reject an inferred equilibrium."""

    if not values:
        raise ValueError(f"uniform-manning-reference-v1 requires non-empty {label}")
    reference = values[0]
    if any(not _policy_close(value, reference) for value in values[1:]):
        raise ValueError(f"uniform-manning-reference-v1 requires constant {label}")
    return reference


def _require_scope_constant(
    values: tuple[float, ...],
    label: str,
    policy: str,
) -> float:
    """Return one constant value for a named, fail-closed reference scope."""

    if not values:
        raise ValueError(f"{policy} requires non-empty {label}")
    reference = values[0]
    if any(not _c1_reference_close(value, reference) for value in values[1:]):
        raise ValueError(f"{policy} requires constant {label}")
    return reference


def _require_absolute_stage_constant(
    values: tuple[float, ...],
    label: str,
    policy: str,
) -> float:
    """Return one absolute stage or reject datum-scaled near-equality."""

    if not values:
        raise ValueError(f"{policy} requires non-empty {label}")
    reference = values[0]
    if any(not _absolute_stage_close(value, reference) for value in values[1:]):
        raise ValueError(f"{policy} requires constant {label}")
    return reference


FiniteNumber = Annotated[float, BeforeValidator(_finite_number)]
PositiveFinite = Annotated[FiniteNumber, Field(gt=0.0)]
NonNegativeFinite = Annotated[FiniteNumber, Field(ge=0.0)]
PositiveId = Annotated[int, Field(strict=True, gt=0)]
NonNegativeInt = Annotated[int, Field(strict=True, ge=0)]
PositiveInt = Annotated[int, Field(strict=True, gt=0)]
Sha256 = Annotated[
    str,
    StringConstraints(strict=True, pattern=r"^[0-9a-f]{64}$"),
]
NonBlankText = Annotated[
    str,
    StringConstraints(strict=True, min_length=1, pattern=r".*\S.*"),
]


class StrictContractModel(BaseModel):
    """Reject unknown keys while scalar aliases enforce JSON-safe coercion rules."""

    # Container strictness is intentionally disabled so JSON arrays decoded as
    # ``list`` become immutable tuples. Every scalar alias above is strict or
    # passes through ``_finite_number``, which rejects unsafe coercion.
    model_config = ConfigDict(extra="forbid", frozen=True)


class DatasetVersionIdentity(StrictContractModel):
    """Identify the immutable Dataset Version used to build the snapshot."""

    id: PositiveId
    content_hash: Sha256


class CoordinateReference(StrictContractModel):
    """Freeze the projected engineering and vertical coordinate contract."""

    engineering_crs: Annotated[
        str,
        StringConstraints(strict=True, pattern=r"^EPSG:[1-9][0-9]{3,5}$"),
    ]
    horizontal_unit: Literal["m"]
    vertical_datum: NonBlankText
    vertical_unit: Literal["m"]


class V4LiteSolver(StrictContractModel):
    """Select the single implemented numerical tuple and all time controls."""

    type: Literal["saint-venant"]
    scheme: Literal["finite-volume-hll"]
    time_integrator: Literal["ssp-rk2"]
    friction_method: Literal["manning-semi-implicit"]
    duration_seconds: PositiveFinite
    maximum_time_step_seconds: PositiveFinite
    minimum_time_step_seconds: PositiveFinite
    output_interval_seconds: PositiveFinite
    cfl_number: Annotated[FiniteNumber, Field(gt=0.0, le=1.0)]
    dry_depth_m: NonNegativeFinite
    maximum_retries: NonNegativeInt
    maximum_steps: PositiveInt
    water_balance_tolerance: Annotated[FiniteNumber, Field(gt=0.0, le=0.01)]
    geometry_policy: Literal[
        "absolute-prismatic-v1",
        "relative-prismatic-linear-bed-v1",
        "nonprismatic-section-linear-path-v1",
        "nonprismatic-frictionless-energy-reference-v1",
    ] = "absolute-prismatic-v1"
    geometry_source: Literal[
        "hydrostatic-reconstruction-v1",
        "hydraulic-function-linear-face-v1",
    ] = "hydrostatic-reconstruction-v1"
    bed_elevation_source: Literal[
        "profile-minimum-elevation-v1"
    ] = "profile-minimum-elevation-v1"
    equilibrium_policy: Literal[
        "standard-v1",
        "uniform-manning-reference-v1",
    ] = "standard-v1"
    boundary_closure: Literal[
        "zero-gradient-companion-v1",
        "subcritical-characteristic-v1",
    ] = "zero-gradient-companion-v1"
    boundary_spatial_support: Literal[
        "nearest-section-cell-face-v1"
    ] = "nearest-section-cell-face-v1"
    structure_event_policy: Literal[
        "accepted-state-discrete-v1",
        "bracketed-conservative-replay-right-end-v1",
    ] = "accepted-state-discrete-v1"
    event_time_tolerance_seconds: PositiveFinite = 1.0e-3
    maximum_event_refinements: NonNegativeInt = 30
    control_spatial_support: Literal[
        "bound-section-cell-center-v1"
    ] = "bound-section-cell-center-v1"

    @property
    def policy_tuple(self) -> tuple[str, str, str, str, str, str]:
        """Return the single auditable geometry/source/equilibrium policy tuple."""

        return (
            self.geometry_policy,
            self.geometry_source,
            self.bed_elevation_source,
            self.equilibrium_policy,
            self.boundary_closure,
            self.boundary_spatial_support,
        )

    @model_validator(mode="after")
    def validate_time_controls(self) -> Self:
        """Reject internally inconsistent step and output intervals."""

        if self.minimum_time_step_seconds > self.maximum_time_step_seconds:
            raise ValueError(
                "minimum_time_step_seconds must not exceed maximum_time_step_seconds"
            )
        if self.maximum_time_step_seconds > self.duration_seconds:
            raise ValueError("maximum_time_step_seconds must not exceed duration_seconds")
        if self.output_interval_seconds > self.duration_seconds:
            raise ValueError("output_interval_seconds must not exceed duration_seconds")
        return self


class V4LiteRiver(StrictContractModel):
    """Describe the one confirmed authoritative hydraulic Branch."""

    network_id: PositiveId
    branch_id: PositiveId
    branch_code: NonBlankText
    upstream_node_id: PositiveId
    downstream_node_id: PositiveId
    start_chainage_m: NonNegativeFinite
    end_chainage_m: PositiveFinite
    direction_status: Literal["confirmed"]

    @model_validator(mode="after")
    def validate_branch_identity(self) -> Self:
        """Require distinct endpoints and a positive adopted chainage range."""

        if self.upstream_node_id == self.downstream_node_id:
            raise ValueError("river endpoint identities must be distinct")
        if self.end_chainage_m <= self.start_chainage_m:
            raise ValueError("end_chainage_m must exceed start_chainage_m")
        return self


class ProfilePoint(StrictContractModel):
    """Represent one offset/elevation point from an existing active Profile."""

    offset_m: FiniteNumber
    elevation_m: FiniteNumber


class V4LiteSection(StrictContractModel):
    """Bind one authoritative section identity to its immutable Profile geometry."""

    section_id: PositiveId
    section_code: NonBlankText
    branch_id: PositiveId
    chainage_m: NonNegativeFinite
    profile_id: PositiveId
    profile_hash: Sha256
    default_manning_n: Annotated[FiniteNumber, Field(ge=0.0, le=1.0)]
    points: tuple[ProfilePoint, ...] = Field(min_length=3)

    @model_validator(mode="after")
    def validate_profile_geometry(self) -> Self:
        """Require one contiguous wetted channel with banks above its minimum bed."""

        offsets = tuple(point.offset_m for point in self.points)
        if any(right <= left for left, right in zip(offsets, offsets[1:])):
            raise ValueError("profile point offsets must be strictly increasing")
        if self.maximum_stage_m <= self.minimum_stage_m:
            raise ValueError("profile endpoint banks must be above the minimum bed")
        elevations = tuple(point.elevation_m for point in self.points)
        minimum = min(elevations)
        first_minimum = elevations.index(minimum)
        last_minimum = len(elevations) - 1 - elevations[::-1].index(minimum)
        left_bank = elevations[: first_minimum + 1]
        right_bank = elevations[last_minimum:]
        if any(right > left for left, right in zip(left_bank, left_bank[1:])):
            raise ValueError(
                "v4-lite Profile must descend monotonically from the left bank"
            )
        if any(right < left for left, right in zip(right_bank, right_bank[1:])):
            raise ValueError(
                "v4-lite Profile must ascend monotonically to the right bank"
            )
        if any(value != minimum for value in elevations[first_minimum:last_minimum]):
            raise ValueError(
                "v4-lite Profile must have one contiguous minimum-bed interval"
            )
        return self

    @property
    def minimum_stage_m(self) -> float:
        """Return the lowest Profile elevation used as the dry-bed stage."""

        return min(point.elevation_m for point in self.points)

    @property
    def maximum_stage_m(self) -> float:
        """Return the lower endpoint bank, beyond which extrapolation is unsafe."""

        return min(self.points[0].elevation_m, self.points[-1].elevation_m)


class UniformInitialState(StrictContractModel):
    """Apply one explicitly supplied stage and discharge to every section."""

    type: Literal["uniform"]
    water_level_m: FiniteNumber
    discharge_m3_s: NonNegativeFinite


class SectionInitialValue(StrictContractModel):
    """Supply the initial stage and discharge for one authoritative section."""

    section_id: PositiveId
    water_level_m: FiniteNumber
    discharge_m3_s: NonNegativeFinite


class BySectionInitialState(StrictContractModel):
    """Supply an exact initial state for every section without interpolation."""

    type: Literal["by-section"]
    values: tuple[SectionInitialValue, ...] = Field(min_length=3)


InitialState = Annotated[
    UniformInitialState | BySectionInitialState,
    Field(discriminator="type"),
]


class BoundaryIdentity(StrictContractModel):
    """Retain the public boundary asset only as frozen provenance."""

    namespace: Literal["public.boundary_condition"]
    id: PositiveId


class UpstreamDischargeSeries(StrictContractModel):
    """Bind a non-negative upstream Q(t) series to the Branch source node."""

    identity: BoundaryIdentity
    type: Literal["discharge-series"]
    target_node_id: PositiveId
    time_seconds: tuple[NonNegativeFinite, ...] = Field(min_length=2)
    flow_m3_s: tuple[NonNegativeFinite, ...] = Field(min_length=2)
    interpolation: Literal["linear"]
    extrapolation: Literal["error"]

    @model_validator(mode="after")
    def validate_series(self) -> Self:
        """Require aligned values on a strictly increasing time axis."""

        _validate_time_series(self.time_seconds, self.flow_m3_s, "upstream discharge")
        return self


class DownstreamStageSeries(StrictContractModel):
    """Bind a downstream H(t) series to the Branch sink node."""

    identity: BoundaryIdentity
    type: Literal["stage-series"]
    target_node_id: PositiveId
    time_seconds: tuple[NonNegativeFinite, ...] = Field(min_length=2)
    water_level_m: tuple[FiniteNumber, ...] = Field(min_length=2)
    interpolation: Literal["linear"]
    extrapolation: Literal["error"]

    @model_validator(mode="after")
    def validate_series(self) -> Self:
        """Require aligned values on a strictly increasing time axis."""

        _validate_time_series(self.time_seconds, self.water_level_m, "downstream stage")
        return self


def _validate_time_series(
    times: tuple[float, ...], values: tuple[float, ...], label: str
) -> None:
    """Validate common alignment and ordering rules for a boundary series."""

    if len(times) != len(values):
        raise ValueError(f"{label} times and values must have equal length")
    if any(right <= left for left, right in zip(times, times[1:])):
        raise ValueError(f"{label} times must be strictly increasing")


class V4LiteBoundary(StrictContractModel):
    """Require exactly one upstream Q(t) and one downstream H(t) boundary."""

    upstream: UpstreamDischargeSeries
    downstream: DownstreamStageSeries


class GateIdentity(StrictContractModel):
    """Identify a Gate in its current public asset namespace."""

    namespace: Literal["public.gate"]
    id: PositiveId


class GateFaceBinding(StrictContractModel):
    """Bind a Gate to the face between two adjacent physical sections."""

    upstream_section_id: PositiveId
    downstream_section_id: PositiveId

    @model_validator(mode="after")
    def validate_distinct_sections(self) -> Self:
        """Reject a face whose left and right identities are identical."""

        if self.upstream_section_id == self.downstream_section_id:
            raise ValueError("gate face sections must be distinct")
        return self


class FixedStructureControlInput(StrictContractModel):
    """Select the existing fixed command semantics without a controller latch."""

    type: Literal["fixed"] = "fixed"


class OneShotStageAboveControlInput(StrictContractModel):
    """Latch one action when an accepted absolute stage exceeds a threshold."""

    type: Literal["one-shot-stage-above"]
    threshold_water_level_m: FiniteNumber


class BracketedOneShotStageAboveControlInput(StrictContractModel):
    """Locate one rising threshold crossing by conservative replay."""

    type: Literal["one-shot-stage-above-bracketed-v1"]
    threshold_water_level_m: FiniteNumber


StructureControlInput = Annotated[
    FixedStructureControlInput
    | OneShotStageAboveControlInput
    | BracketedOneShotStageAboveControlInput,
    Field(discriminator="type"),
]


class FixedGateInput(StrictContractModel):
    """Describe one fixed or explicitly threshold-controlled MVP Gate."""

    identity: GateIdentity
    branch_id: PositiveId
    interface: GateFaceBinding
    opening_m: NonNegativeFinite
    width_m: PositiveFinite
    height_m: PositiveFinite
    discharge_coefficient: Annotated[FiniteNumber, Field(gt=0.0, le=1.0)]
    allow_reverse_flow: Annotated[bool, Field(strict=True)]
    control: StructureControlInput = Field(default_factory=FixedStructureControlInput)

    @model_validator(mode="after")
    def validate_opening(self) -> Self:
        """Keep the fixed opening within the physical Gate height."""

        if self.allow_reverse_flow:
            raise ValueError("v4-lite does not support Gate reverse flow")
        if self.opening_m > self.height_m:
            raise ValueError("gate opening_m must not exceed height_m")
        if (
            isinstance(
                self.control,
                (
                    OneShotStageAboveControlInput,
                    BracketedOneShotStageAboveControlInput,
                ),
            )
            and self.opening_m <= 0.0
        ):
            raise ValueError("threshold-controlled Gate target opening_m must be positive")
        return self


class PumpIdentity(StrictContractModel):
    """Identify a Pump in its current public asset namespace."""

    namespace: Literal["public.pump"]
    id: PositiveId


class ExternalPumpInput(StrictContractModel):
    """Describe one fixed or explicitly threshold-controlled external Pump."""

    identity: PumpIdentity
    branch_id: PositiveId
    section_id: PositiveId
    outlet: Literal["external"]
    status: Literal["on", "off"]
    design_flow_m3_s: PositiveFinite
    control: StructureControlInput = Field(default_factory=FixedStructureControlInput)

    @model_validator(mode="after")
    def validate_control_initial_state(self) -> Self:
        """Keep the threshold latch as the only authority that can start a Pump."""

        if (
            isinstance(
                self.control,
                (
                    OneShotStageAboveControlInput,
                    BracketedOneShotStageAboveControlInput,
                ),
            )
            and self.status != "off"
        ):
            raise ValueError("threshold-controlled Pump must have initial status 'off'")
        return self


class V4LiteStructures(StrictContractModel):
    """Limit the MVP to at most one Gate and one external Pump."""

    gates: tuple[FixedGateInput, ...] = Field(max_length=1)
    pumps: tuple[ExternalPumpInput, ...] = Field(max_length=1)


class V4LiteProvenance(StrictContractModel):
    """Freeze engine and validation-policy identity with the numerical input."""

    engine_version: NonBlankText
    engine_commit: NonBlankText
    validation_policy_version: Literal[
        "v4-lite-1",
        "v4-lite-2",
        "v4-lite-3",
        "v4-lite-4",
    ]


class V4LiteInput(StrictContractModel):
    """Canonical, direct-engine-only ``dayu.model-input.v4-lite`` snapshot."""

    schema_version: Literal["dayu.model-input.v4-lite"]
    dataset_version: DatasetVersionIdentity
    coordinate_reference: CoordinateReference
    solver: V4LiteSolver
    river: V4LiteRiver
    sections: tuple[V4LiteSection, ...] = Field(min_length=3)
    initial_state: InitialState
    boundary: V4LiteBoundary
    structures: V4LiteStructures
    provenance: V4LiteProvenance

    @field_validator("sections")
    @classmethod
    def validate_section_collection(
        cls, sections: tuple[V4LiteSection, ...]
    ) -> tuple[V4LiteSection, ...]:
        """Reject duplicate identities and require strict upstream ordering."""

        _require_unique((item.section_id for item in sections), "section_id")
        _require_unique((item.section_code for item in sections), "section_code")
        _require_unique((item.profile_id for item in sections), "profile_id")
        chainages = tuple(item.chainage_m for item in sections)
        if any(right <= left for left, right in zip(chainages, chainages[1:])):
            raise ValueError("sections must be strictly increasing by chainage_m")
        return sections

    @model_validator(mode="after")
    def validate_closed_contract(self) -> Self:
        """Validate all cross-object identities, coverage, and hydraulic ranges."""

        section_by_id = {item.section_id: item for item in self.sections}
        section_ids = tuple(section_by_id)
        self._validate_versioned_policy()
        if (
            self.provenance.validation_policy_version != "v4-lite-3"
            and any(section.default_manning_n <= 0.0 for section in self.sections)
        ):
            raise ValueError(
                "v4-lite-1/v4-lite-2 require default_manning_n greater than 0"
            )
        for section in self.sections:
            if section.branch_id != self.river.branch_id:
                raise ValueError(
                    f"section {section.section_id} references an unknown Branch identity"
                )
            if not self.river.start_chainage_m <= section.chainage_m <= self.river.end_chainage_m:
                raise ValueError(
                    f"section {section.section_id} lies outside the Branch chainage range"
                )
        self._validate_section_geometry_policy()

        if self.boundary.upstream.target_node_id != self.river.upstream_node_id:
            raise ValueError("upstream boundary targets an unknown Branch endpoint")
        if self.boundary.downstream.target_node_id != self.river.downstream_node_id:
            raise ValueError("downstream boundary targets an unknown Branch endpoint")
        if self.boundary.upstream.identity.id == self.boundary.downstream.identity.id:
            raise ValueError("upstream and downstream boundary identities must be distinct")
        self._validate_boundary_coverage()
        self._validate_initial_state(section_by_id)
        self._validate_downstream_stage(section_by_id[section_ids[-1]])
        self._validate_structures(section_ids)
        self._validate_structure_event_policy(section_by_id)
        self._validate_equilibrium_policy()
        self._validate_nonprismatic_lake_scope()
        self._validate_nonprismatic_moving_scope()
        return self

    def _validate_versioned_policy(self) -> None:
        """Bind each supported policy tuple to one explicit validation version."""

        policy = self.solver.policy_tuple
        version = self.provenance.validation_policy_version
        if version == "v4-lite-1":
            explicit = (
                _VERSIONED_POLICY_FIELDS | _EVENT_POLICY_FIELDS
            ) & self.solver.model_fields_set
            if explicit:
                raise ValueError(
                    "v4-lite-1 does not accept explicit versioned policy fields"
                )
            if policy != LEGACY_V4_LITE_POLICY:
                raise ValueError("v4-lite-1 only supports the legacy policy tuple")
            return
        missing = _VERSIONED_POLICY_FIELDS - self.solver.model_fields_set
        if missing:
            raise ValueError(
                f"{version} requires every versioned policy field explicitly; "
                f"missing={sorted(missing)}"
            )
        explicit_event_fields = _EVENT_POLICY_FIELDS & self.solver.model_fields_set
        if version == "v4-lite-2":
            if explicit_event_fields:
                raise ValueError("v4-lite-2 does not accept event policy fields")
            if policy not in {
                B2_STANDARD_POLICY,
                B2_UNIFORM_MANNING_POLICY,
                B2_NONPRISMATIC_LAKE_POLICY,
            }:
                raise ValueError("v4-lite-2 policy tuple is not implemented")
            return
        if version == "v4-lite-3":
            if explicit_event_fields:
                raise ValueError("v4-lite-3 does not accept event policy fields")
            if policy != C1_NONPRISMATIC_MOVING_POLICY:
                raise ValueError("v4-lite-3 policy tuple is not implemented")
            return
        missing_event_fields = _EVENT_POLICY_FIELDS - self.solver.model_fields_set
        if missing_event_fields:
            raise ValueError(
                "v4-lite-4 requires every event policy field explicitly; "
                f"missing={sorted(missing_event_fields)}"
            )
        if policy != C2_BRACKETED_EVENT_POLICY:
            raise ValueError("v4-lite-4 policy tuple is not implemented")
        if self.solver.structure_event_policy != (
            "bracketed-conservative-replay-right-end-v1"
        ):
            raise ValueError("v4-lite-4 requires the bracketed event policy")

    def _validate_section_geometry_policy(self) -> None:
        """Validate exact legacy Profiles or vertically translated linear-bed Profiles."""

        reference = self.sections[0]
        if self.solver.geometry_policy == "absolute-prismatic-v1":
            reference_points = tuple(
                (point.offset_m, point.elevation_m) for point in reference.points
            )
            for section in self.sections[1:]:
                points = tuple(
                    (point.offset_m, point.elevation_m) for point in section.points
                )
                if points != reference_points:
                    raise ValueError(
                        "absolute-prismatic-v1 requires identical absolute Profile points"
                    )
            return

        if self.solver.geometry_policy in {
            "nonprismatic-section-linear-path-v1",
            "nonprismatic-frictionless-energy-reference-v1",
        }:
            return

        reference_shape = self._relative_profile_shape(reference)
        for section in self.sections[1:]:
            shape = self._relative_profile_shape(section)
            if not self._relative_profile_shapes_match(reference_shape, shape):
                raise ValueError(
                    "relative-prismatic-linear-bed-v1 requires identical relative "
                    "Profile shapes"
                )

        beds = tuple(section.minimum_stage_m for section in self.sections)
        if any(right >= left for left, right in zip(beds, beds[1:])):
            raise ValueError(
                "relative-prismatic-linear-bed-v1 requires a strictly descending bed"
            )
        chainages = tuple(section.chainage_m for section in self.sections)
        slopes = tuple(
            (left_bed - right_bed) / (right_chainage - left_chainage)
            for left_bed, right_bed, left_chainage, right_chainage in zip(
                beds,
                beds[1:],
                chainages,
                chainages[1:],
            )
        )
        minimum_gap = min(
            right - left for left, right in zip(chainages, chainages[1:])
        )
        slope_absolute_tolerance = max(
            _POLICY_ABSOLUTE_TOLERANCE,
            8.0 * max(math.ulp(abs(bed)) for bed in beds) / minimum_gap,
        )
        if any(
            not math.isclose(
                slope,
                slopes[0],
                rel_tol=_POLICY_RELATIVE_TOLERANCE,
                abs_tol=slope_absolute_tolerance,
            )
            for slope in slopes[1:]
        ):
            raise ValueError(
                "relative-prismatic-linear-bed-v1 requires one linear bed slope"
            )

    @staticmethod
    def _relative_profile_shape(
        section: V4LiteSection,
    ) -> tuple[tuple[float, float], ...]:
        """Normalize absolute Profile points against their declared minimum bed."""

        bed = section.minimum_stage_m
        return tuple(
            (point.offset_m, point.elevation_m - bed) for point in section.points
        )

    @staticmethod
    def _relative_profile_shapes_match(
        left: tuple[tuple[float, float], ...],
        right: tuple[tuple[float, float], ...],
    ) -> bool:
        """Compare two normalized Profiles with the versioned policy tolerance."""

        return len(left) == len(right) and all(
            _policy_close(left_offset, right_offset)
            and _policy_close(left_height, right_height)
            for (left_offset, left_height), (right_offset, right_height) in zip(
                left,
                right,
            )
        )

    def _validate_boundary_coverage(self) -> None:
        """Require both series to cover the complete simulation interval without extrapolation."""

        for label, times in (
            ("upstream", self.boundary.upstream.time_seconds),
            ("downstream", self.boundary.downstream.time_seconds),
        ):
            if times[0] != 0.0 or times[-1] < self.solver.duration_seconds:
                raise ValueError(
                    f"{label} boundary must cover [0, duration_seconds]"
                )

    def _validate_initial_state(
        self, section_by_id: dict[int, V4LiteSection]
    ) -> None:
        """Require an explicit valid state for every section and no unknown identities."""

        if isinstance(self.initial_state, UniformInitialState):
            for section in self.sections:
                self._validate_initial_value(
                    section,
                    self.initial_state.water_level_m,
                    self.initial_state.discharge_m3_s,
                )
            return

        values = self.initial_state.values
        _require_unique((item.section_id for item in values), "initial section_id")
        actual_ids = {item.section_id for item in values}
        expected_ids = set(section_by_id)
        if actual_ids != expected_ids:
            missing = sorted(expected_ids - actual_ids)
            unknown = sorted(actual_ids - expected_ids)
            raise ValueError(
                "by-section initial_state must match sections exactly; "
                f"missing={missing}, unknown={unknown}"
            )
        for value in values:
            self._validate_initial_value(
                section_by_id[value.section_id],
                value.water_level_m,
                value.discharge_m3_s,
            )

    def _validate_equilibrium_policy(self) -> None:
        """Preflight the complete explicit uniform-Manning reference contract."""

        if self.solver.equilibrium_policy == "standard-v1":
            return
        if self.structures.gates or self.structures.pumps:
            raise ValueError(
                "uniform-manning-reference-v1 does not support Gate or Pump structures"
            )
        if not isinstance(self.initial_state, BySectionInitialState):
            raise ValueError(
                "uniform-manning-reference-v1 requires by-section initial_state"
            )

        value_by_id = {
            value.section_id: value for value in self.initial_state.values
        }
        ordered_values = tuple(
            value_by_id[section.section_id] for section in self.sections
        )
        discharge = _require_policy_constant(
            tuple(value.discharge_m3_s for value in ordered_values),
            "initial discharge",
        )
        if discharge <= 0.0:
            raise ValueError(
                "uniform-manning-reference-v1 requires positive initial discharge"
            )
        depths = tuple(
            value.water_level_m - section.minimum_stage_m
            for value, section in zip(ordered_values, self.sections)
        )
        depth = _require_policy_constant(depths, "initial water depth")
        if depth <= self.solver.dry_depth_m:
            raise ValueError(
                "uniform-manning-reference-v1 requires a wet initial reference"
            )
        _require_policy_constant(
            tuple(section.default_manning_n for section in self.sections),
            "Manning n",
        )
        upstream_flow = _require_policy_constant(
            tuple(self.boundary.upstream.flow_m3_s),
            "upstream discharge boundary",
        )
        if not _policy_close(upstream_flow, discharge):
            raise ValueError(
                "uniform-manning-reference-v1 upstream boundary must match initial discharge"
            )
        downstream_stage = _require_absolute_stage_constant(
            tuple(self.boundary.downstream.water_level_m),
            "downstream stage boundary",
            "uniform-manning-reference-v1",
        )
        final_initial_stage = ordered_values[-1].water_level_m
        if not _absolute_stage_close(downstream_stage, final_initial_stage):
            raise ValueError(
                "uniform-manning-reference-v1 downstream boundary must match the "
                "final initial stage"
            )
        self._validate_equilibrium_cell_centers()

    def _validate_nonprismatic_lake_scope(self) -> None:
        """Limit the first non-prismatic public path to a verified lake at rest."""

        if self.solver.geometry_policy != "nonprismatic-section-linear-path-v1":
            return
        if self.structures.gates or self.structures.pumps:
            raise ValueError(
                "nonprismatic-section-linear-path-v1 does not support structures"
            )

        if isinstance(self.initial_state, UniformInitialState):
            stages = (self.initial_state.water_level_m,) * len(self.sections)
            discharges = (self.initial_state.discharge_m3_s,) * len(self.sections)
        else:
            value_by_id = {
                value.section_id: value for value in self.initial_state.values
            }
            ordered = tuple(
                value_by_id[section.section_id] for section in self.sections
            )
            stages = tuple(value.water_level_m for value in ordered)
            discharges = tuple(value.discharge_m3_s for value in ordered)

        reference_stage = stages[0]
        if any(
            not _absolute_stage_close(stage, reference_stage)
            for stage in stages[1:]
        ):
            raise ValueError(
                "nonprismatic-section-linear-path-v1 requires one common initial stage"
            )
        if any(abs(discharge) > _POLICY_ABSOLUTE_TOLERANCE for discharge in discharges):
            raise ValueError(
                "nonprismatic-section-linear-path-v1 requires zero initial discharge"
            )
        if any(
            reference_stage - section.minimum_stage_m <= self.solver.dry_depth_m
            for section in self.sections
        ):
            raise ValueError(
                "nonprismatic-section-linear-path-v1 requires every section to be wet"
            )
        signatures = tuple(
            self._hydraulic_signature(section, reference_stage)
            for section in self.sections
        )
        if all(
            all(_policy_close(left, right) for left, right in zip(signatures[0], item))
            for item in signatures[1:]
        ):
            raise ValueError(
                "nonprismatic-section-linear-path-v1 requires at least two distinct "
                "hydraulic Profile signatures at the common initial stage"
            )

        upstream = self.boundary.upstream.flow_m3_s
        if any(abs(value) > _POLICY_ABSOLUTE_TOLERANCE for value in upstream):
            raise ValueError(
                "nonprismatic-section-linear-path-v1 requires zero upstream discharge"
            )
        downstream = self.boundary.downstream.water_level_m
        if any(
            not _absolute_stage_close(value, reference_stage)
            for value in downstream
        ):
            raise ValueError(
                "nonprismatic-section-linear-path-v1 downstream stage must match "
                "the common initial stage"
            )

    def _validate_nonprismatic_moving_scope(self) -> None:
        """Admit only the frozen fully wet frictionless-energy reference class."""

        policy = "nonprismatic-frictionless-energy-reference-v1"
        if self.solver.geometry_policy != policy:
            return
        if self.structures.gates or self.structures.pumps:
            raise ValueError(f"{policy} does not support structures")
        if not isinstance(self.initial_state, BySectionInitialState):
            raise ValueError(f"{policy} requires by-section initial_state")

        section_count = len(self.sections)
        domain_length = (
            self.river.end_chainage_m - self.river.start_chainage_m
        )
        expected_dx = domain_length / section_count
        chainage_tolerance = max(
            1.0e-9,
            8.0
            * max(
                math.ulp(abs(self.river.start_chainage_m)),
                math.ulp(abs(self.river.end_chainage_m)),
            ),
        )
        for index, section in enumerate(self.sections):
            expected = self.river.start_chainage_m + (index + 0.5) * expected_dx
            if not math.isclose(
                section.chainage_m,
                expected,
                rel_tol=0.0,
                abs_tol=chainage_tolerance,
            ):
                raise ValueError(
                    f"{policy} requires a uniform cell-centre section grid"
                )

        beds = tuple(section.minimum_stage_m for section in self.sections)
        bed_tolerance = max(
            _POLICY_ABSOLUTE_TOLERANCE,
            8.0 * max(math.ulp(abs(bed)) for bed in beds),
        )
        if any(
            not math.isclose(
                bed,
                beds[0],
                rel_tol=0.0,
                abs_tol=bed_tolerance,
            )
            for bed in beds[1:]
        ):
            raise ValueError(f"{policy} requires one flat bed elevation")
        if any(section.default_manning_n != 0.0 for section in self.sections):
            raise ValueError(f"{policy} requires Manning n=0 in every section")

        value_by_id = {
            value.section_id: value for value in self.initial_state.values
        }
        values = tuple(
            value_by_id[section.section_id] for section in self.sections
        )
        discharge = _require_scope_constant(
            tuple(value.discharge_m3_s for value in values),
            "initial discharge",
            policy,
        )
        if discharge <= 0.0:
            raise ValueError(f"{policy} requires positive downstream discharge")

        stages = tuple(value.water_level_m for value in values)
        minimum_wet_depth = max(
            _MOVING_REFERENCE_DRY_DEPTH_FACTOR * self.solver.dry_depth_m,
            1.0e-6,
        )
        geometries = tuple(
            TabulatedSectionGeometry.from_points(
                tuple(
                    (point.offset_m, point.elevation_m)
                    for point in section.points
                )
            )
            for section in self.sections
        )
        energy_heads: list[float] = []
        celerities: list[float] = []
        for section, geometry, stage in zip(
            self.sections,
            geometries,
            stages,
        ):
            depth = stage - section.minimum_stage_m
            if depth <= minimum_wet_depth:
                raise ValueError(
                    f"{policy} requires depth greater than the frozen wet margin"
                )
            area = geometry.area(stage)
            top_width = geometry.top_width(stage)
            if area <= 0.0 or top_width <= 0.0:
                raise ValueError(f"{policy} requires positive hydraulic geometry")
            celerity = math.sqrt(_GRAVITY_M_S2 * area / top_width)
            froude = abs(discharge / area) / celerity
            if not math.isfinite(froude) or froude > _MOVING_REFERENCE_MAXIMUM_FROUDE:
                raise ValueError(f"{policy} requires Froude number <= 0.8")
            celerities.append(celerity)
            energy_heads.append(
                stage
                + discharge * discharge
                / (2.0 * _GRAVITY_M_S2 * area * area)
            )
        energy_reference = energy_heads[0]
        if any(
            not _energy_head_close(energy, energy_reference)
            for energy in energy_heads[1:]
        ):
            raise ValueError(f"{policy} requires one constant total energy head")
        comparison_stage = min(stages)
        signatures = tuple(
            self._hydraulic_signature(section, comparison_stage)
            for section in self.sections
        )
        if all(
            all(
                _policy_close(left, right)
                for left, right in zip(signatures[0], signature)
            )
            for signature in signatures[1:]
        ):
            raise ValueError(
                f"{policy} requires at least two distinct hydraulic Profile signatures"
            )
        observation_fraction = (
            self.solver.duration_seconds
            * max(celerities)
            / domain_length
        )
        if observation_fraction < _MOVING_REFERENCE_MINIMUM_TRANSIT_FRACTION:
            raise ValueError(
                f"{policy} requires a dimensionless observation fraction >= 0.02"
            )

        upstream_flow = _require_scope_constant(
            tuple(self.boundary.upstream.flow_m3_s),
            "upstream discharge boundary",
            policy,
        )
        if not _c1_reference_close(upstream_flow, discharge):
            raise ValueError(f"{policy} upstream boundary must match initial discharge")
        downstream_stage = _require_absolute_stage_constant(
            tuple(self.boundary.downstream.water_level_m),
            "downstream stage boundary",
            policy,
        )
        if not _absolute_stage_close(downstream_stage, stages[-1]):
            raise ValueError(
                f"{policy} downstream stage must match the final initial stage"
            )

    @staticmethod
    def _hydraulic_signature(
        section: V4LiteSection,
        stage: float,
    ) -> tuple[float, float, float, float]:
        """Evaluate the actual A/T/P/I1 identity used by the numerical mesh."""

        geometry = TabulatedSectionGeometry.from_points(
            tuple((point.offset_m, point.elevation_m) for point in section.points)
        )
        return (
            geometry.area(stage),
            geometry.top_width(stage),
            geometry.wetted_perimeter(stage),
            geometry.pressure_moment(stage),
        )

    def _validate_equilibrium_cell_centers(self) -> None:
        """Align adopted chainages with the cell-center metric used by the kernel."""

        chainages = tuple(section.chainage_m for section in self.sections)
        internal_faces = tuple(
            0.5 * (left + right)
            for left, right in zip(chainages, chainages[1:])
        )
        faces = (
            self.river.start_chainage_m,
            *internal_faces,
            self.river.end_chainage_m,
        )
        lengths = tuple(right - left for left, right in zip(faces, faces[1:]))
        for index, chainage_gap in enumerate(
            right - left for left, right in zip(chainages, chainages[1:])
        ):
            kernel_gap = 0.5 * (lengths[index] + lengths[index + 1])
            if not _policy_close(kernel_gap, chainage_gap):
                raise ValueError(
                    "uniform-manning-reference-v1 requires section chainages to "
                    "coincide with finite-volume cell centers"
                )

    def _validate_initial_value(
        self, section: V4LiteSection, water_level: float, discharge: float
    ) -> None:
        """Keep initial stage inside the Profile table and dry-cell discharge at zero."""

        if not section.minimum_stage_m <= water_level <= section.maximum_stage_m:
            raise ValueError(
                f"initial water level for section {section.section_id} is outside its Profile range"
            )
        depth = water_level - section.minimum_stage_m
        if depth <= self.solver.dry_depth_m and discharge != 0.0:
            raise ValueError(
                f"dry section {section.section_id} must have zero initial discharge"
            )

    def _validate_downstream_stage(self, section: V4LiteSection) -> None:
        """Keep every downstream H(t) value inside the endpoint Profile range."""

        for level in self.boundary.downstream.water_level_m:
            if not section.minimum_stage_m <= level <= section.maximum_stage_m:
                raise ValueError("downstream stage is outside the endpoint Profile range")

    def _validate_structures(self, section_ids: tuple[int, ...]) -> None:
        """Resolve structure bindings without chainage or nearest-neighbour guessing."""

        known_sections = set(section_ids)
        section_by_id = {section.section_id: section for section in self.sections}
        for gate in self.structures.gates:
            if gate.branch_id != self.river.branch_id:
                raise ValueError("Gate references an unknown Branch identity")
            pair = (
                gate.interface.upstream_section_id,
                gate.interface.downstream_section_id,
            )
            adjacent_pairs = set(zip(section_ids, section_ids[1:]))
            if pair not in adjacent_pairs:
                raise ValueError("Gate interface must use adjacent ordered section identities")
            if isinstance(
                gate.control,
                (
                    OneShotStageAboveControlInput,
                    BracketedOneShotStageAboveControlInput,
                ),
            ):
                monitored = section_by_id[gate.interface.upstream_section_id]
                self._validate_control_threshold(
                    gate.control,
                    monitored,
                    "Gate upstream section",
                )
        for pump in self.structures.pumps:
            if pump.branch_id != self.river.branch_id:
                raise ValueError("Pump references an unknown Branch identity")
            if pump.section_id not in known_sections:
                raise ValueError("Pump references an unknown section identity")
            if isinstance(
                pump.control,
                (
                    OneShotStageAboveControlInput,
                    BracketedOneShotStageAboveControlInput,
                ),
            ):
                self._validate_control_threshold(
                    pump.control,
                    section_by_id[pump.section_id],
                    "Pump section",
                )

    def _validate_structure_event_policy(
        self,
        section_by_id: dict[int, V4LiteSection],
    ) -> None:
        """Keep bracketed replay distinct from the frozen discrete controller."""

        controls = tuple(
            structure.control
            for structure in (*self.structures.gates, *self.structures.pumps)
        )
        version = self.provenance.validation_policy_version
        if version != "v4-lite-4":
            if any(
                isinstance(control, BracketedOneShotStageAboveControlInput)
                for control in controls
            ):
                raise ValueError(
                    "bracketed threshold control requires validation_policy_version "
                    "v4-lite-4"
                )
            return
        if not controls:
            raise ValueError("v4-lite-4 requires at least one controlled structure")
        if any(
            not isinstance(control, BracketedOneShotStageAboveControlInput)
            for control in controls
        ):
            raise ValueError("v4-lite-4 requires every structure to use bracketed control")
        if self.solver.event_time_tolerance_seconds < (
            self.solver.minimum_time_step_seconds
        ):
            raise ValueError(
                "event_time_tolerance_seconds must not be less than "
                "minimum_time_step_seconds"
            )

        if isinstance(self.initial_state, UniformInitialState):
            stage_by_section = {
                section_id: self.initial_state.water_level_m
                for section_id in section_by_id
            }
        else:
            stage_by_section = {
                value.section_id: value.water_level_m
                for value in self.initial_state.values
            }
        for gate in self.structures.gates:
            control = gate.control
            if not isinstance(control, BracketedOneShotStageAboveControlInput):
                raise ValueError("v4-lite-4 Gate control must be bracketed")
            initial_stage = stage_by_section[gate.interface.upstream_section_id]
            if initial_stage >= control.threshold_water_level_m:
                raise ValueError("bracketed Gate initial stage must be below threshold")
        for pump in self.structures.pumps:
            control = pump.control
            if not isinstance(control, BracketedOneShotStageAboveControlInput):
                raise ValueError("v4-lite-4 Pump control must be bracketed")
            initial_stage = stage_by_section[pump.section_id]
            if initial_stage >= control.threshold_water_level_m:
                raise ValueError("bracketed Pump initial stage must be below threshold")

    @staticmethod
    def _validate_control_threshold(
        control: OneShotStageAboveControlInput
        | BracketedOneShotStageAboveControlInput,
        section: V4LiteSection,
        label: str,
    ) -> None:
        """Keep a strict-above threshold inside its monitored Profile range."""

        threshold = control.threshold_water_level_m
        if not section.minimum_stage_m <= threshold < section.maximum_stage_m:
            raise ValueError(
                f"{label} control threshold must satisfy minimum_stage_m <= "
                "threshold_water_level_m < maximum_stage_m"
            )


def _require_unique(values: Any, label: str) -> None:
    """Reject duplicate identities while accepting any one-pass iterable."""

    materialized = tuple(values)
    if len(materialized) != len(set(materialized)):
        raise ValueError(f"{label} values must be unique")


def parse_v4_lite_input(payload: Mapping[str, Any]) -> V4LiteInput:
    """Parse an untrusted JSON-like mapping into the strict v4-lite contract."""

    if not isinstance(payload, Mapping):
        raise HydraulicInputError("dayu.model-input.v4-lite payload must be an object")
    try:
        return V4LiteInput.model_validate(payload)
    except ValidationError as exc:
        raise HydraulicInputError(
            f"dayu.model-input.v4-lite validation failed: {exc}"
        ) from exc


__all__ = [
    "MODEL_INPUT_V4_LITE",
    "V4_LITE_SOLVER_TUPLE",
    "BySectionInitialState",
    "CoordinateReference",
    "DatasetVersionIdentity",
    "DownstreamStageSeries",
    "ExternalPumpInput",
    "FixedGateInput",
    "FixedStructureControlInput",
    "OneShotStageAboveControlInput",
    "ProfilePoint",
    "SectionInitialValue",
    "StructureControlInput",
    "UniformInitialState",
    "UpstreamDischargeSeries",
    "V4LiteBoundary",
    "V4LiteInput",
    "V4LiteProvenance",
    "V4LiteRiver",
    "V4LiteSection",
    "V4LiteSolver",
    "V4LiteStructures",
    "parse_v4_lite_input",
]
