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


MODEL_INPUT_V4_LITE = "dayu.model-input.v4-lite"
V4_LITE_SOLVER_TUPLE = (
    MODEL_INPUT_V4_LITE,
    "saint-venant",
    "finite-volume-hll",
    "ssp-rk2",
)


def _finite_number(value: Any) -> float:
    """Accept JSON integers/floats, reject booleans, strings, NaN, and infinity."""

    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("value must be a JSON number")
    number = float(value)
    if not math.isfinite(number):
        raise ValueError("value must be finite")
    return number


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
    default_manning_n: Annotated[FiniteNumber, Field(gt=0.0, le=1.0)]
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


class FixedGateInput(StrictContractModel):
    """Describe the single optional fixed-opening Gate supported by the MVP."""

    identity: GateIdentity
    branch_id: PositiveId
    interface: GateFaceBinding
    opening_m: NonNegativeFinite
    width_m: PositiveFinite
    height_m: PositiveFinite
    discharge_coefficient: Annotated[FiniteNumber, Field(gt=0.0, le=1.0)]
    allow_reverse_flow: Annotated[bool, Field(strict=True)]

    @model_validator(mode="after")
    def validate_opening(self) -> Self:
        """Keep the fixed opening within the physical Gate height."""

        if self.allow_reverse_flow:
            raise ValueError("v4-lite does not support Gate reverse flow")
        if self.opening_m > self.height_m:
            raise ValueError("gate opening_m must not exceed height_m")
        return self


class PumpIdentity(StrictContractModel):
    """Identify a Pump in its current public asset namespace."""

    namespace: Literal["public.pump"]
    id: PositiveId


class ExternalPumpInput(StrictContractModel):
    """Describe the single optional ON/OFF Pump as an external cell sink."""

    identity: PumpIdentity
    branch_id: PositiveId
    section_id: PositiveId
    outlet: Literal["external"]
    status: Literal["on", "off"]
    design_flow_m3_s: PositiveFinite


class V4LiteStructures(StrictContractModel):
    """Limit the MVP to at most one Gate and one external Pump."""

    gates: tuple[FixedGateInput, ...] = Field(max_length=1)
    pumps: tuple[ExternalPumpInput, ...] = Field(max_length=1)


class V4LiteProvenance(StrictContractModel):
    """Freeze engine and validation-policy identity with the numerical input."""

    engine_version: NonBlankText
    engine_commit: NonBlankText
    validation_policy_version: Literal["v4-lite-1"]


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
        reference_geometry = tuple(
            (point.offset_m, point.elevation_m) for point in self.sections[0].points
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
            geometry = tuple(
                (point.offset_m, point.elevation_m) for point in section.points
            )
            if geometry != reference_geometry:
                raise ValueError(
                    "v4-lite currently requires identical prismatic section geometry; "
                    "non-prismatic geometry source terms are not implemented"
                )

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
        return self

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
        for pump in self.structures.pumps:
            if pump.branch_id != self.river.branch_id:
                raise ValueError("Pump references an unknown Branch identity")
            if pump.section_id not in known_sections:
                raise ValueError("Pump references an unknown section identity")


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
    "ProfilePoint",
    "SectionInitialValue",
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
