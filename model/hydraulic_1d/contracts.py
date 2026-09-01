"""Solver-neutral input and result contracts for production one-dimensional hydraulics."""

from __future__ import annotations

from datetime import datetime
from math import isclose
from typing import Any, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, FiniteFloat, model_validator

from model.hydraulic_1d.errors import Hydraulic1DValidationError


HYDRAULIC_1D_INPUT_SCHEMA = "dayu.hydraulic-1d.input.v1"
HYDRAULIC_RESULT_SCHEMA = "dayu.hydraulic-result.v1"


class StrictHydraulicModel(BaseModel):
    """Make frozen snapshots deterministic and reject unregistered fields."""

    model_config = ConfigDict(extra="forbid", frozen=True)


class TimeValue(StrictHydraulicModel):
    """Represent one finite boundary-condition sample in SI units."""

    time_seconds: FiniteFloat = Field(ge=0.0)
    value: FiniteFloat


class CrossSectionPoint(StrictHydraulicModel):
    """Represent one ordered station/elevation point in a Dayu profile."""

    station_m: FiniteFloat = Field(ge=0.0)
    elevation_m: FiniteFloat
    zone: Literal["main_channel", "floodplain"] = "main_channel"
    source_x: FiniteFloat | None = None
    source_y: FiniteFloat | None = None
    source_z: FiniteFloat | None = None
    source_crs: str | None = Field(default=None, min_length=1, max_length=64)
    source_axis_mapping: str | None = Field(default=None, min_length=1, max_length=32)


class RoughnessZone(StrictHydraulicModel):
    """Preserve a transverse Dayu roughness zone before adapter validation."""

    start_station_m: FiniteFloat = Field(ge=0.0)
    end_station_m: FiniteFloat = Field(gt=0.0)
    manning_n: FiniteFloat = Field(gt=0.0)

    @model_validator(mode="after")
    def validate_extent(self) -> Self:
        """Require a positive station interval for every roughness zone."""

        if self.end_station_m <= self.start_station_m:
            raise ValueError("roughness-zone end must exceed start")
        return self


class HydraulicCrossSection(StrictHydraulicModel):
    """Carry one unified cross section independently of MASCARET file syntax."""

    id: str = Field(min_length=1, max_length=128)
    branch_id: str = Field(min_length=1, max_length=128)
    code: str = Field(min_length=1, max_length=128)
    chainage_m: FiniteFloat = Field(ge=0.0)
    vertical_datum: str = Field(min_length=1, max_length=64)
    points: tuple[CrossSectionPoint, ...] = Field(min_length=3)
    manning_n: FiniteFloat = Field(gt=0.0)
    roughness_zones: tuple[RoughnessZone, ...] = ()
    location_geometry: dict[str, Any] | None = None
    axis_geometry: dict[str, Any] | None = None
    left_bank: dict[str, Any] | None = None
    right_bank: dict[str, Any] | None = None

    @model_validator(mode="after")
    def validate_profile(self) -> Self:
        """Require strictly ordered points and bounded transverse roughness zones."""

        stations = [item.station_m for item in self.points]
        if any(right <= left for left, right in zip(stations, stations[1:])):
            raise ValueError("cross-section stations must be strictly increasing")
        for zone in self.roughness_zones:
            if zone.end_station_m > stations[-1]:
                raise ValueError(
                    "roughness zone exceeds the cross-section station range"
                )
        return self


class HydraulicBranch(StrictHydraulicModel):
    """Represent one directed Dayu branch with solver-neutral topology identities."""

    id: str = Field(min_length=1, max_length=128)
    code: str = Field(min_length=1, max_length=128)
    upstream_node_id: str = Field(min_length=1, max_length=128)
    downstream_node_id: str = Field(min_length=1, max_length=128)
    start_chainage_m: FiniteFloat = Field(ge=0.0)
    end_chainage_m: FiniteFloat = Field(gt=0.0)

    @model_validator(mode="after")
    def validate_direction(self) -> Self:
        """Require a positive directed chainage interval and distinct endpoint nodes."""

        if self.end_chainage_m <= self.start_chainage_m:
            raise ValueError("branch end_chainage_m must exceed start_chainage_m")
        if self.upstream_node_id == self.downstream_node_id:
            raise ValueError("branch endpoints must be distinct")
        return self


class HydraulicNode(StrictHydraulicModel):
    """Represent one solver-neutral network node and its engineering role."""

    id: str = Field(min_length=1, max_length=128)
    code: str = Field(min_length=1, max_length=128)
    node_type: Literal[
        "boundary",
        "junction",
        "bifurcation",
        "internal",
        "storage_connection",
    ]
    name: str | None = Field(default=None, min_length=1, max_length=128)
    location_geometry: dict[str, Any] | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class BoundaryCondition(StrictHydraulicModel):
    """Represent Q(t), H(t), constants, or a lateral Q(t) in one contract."""

    id: str = Field(min_length=1, max_length=128)
    branch_id: str = Field(min_length=1, max_length=128)
    location: Literal["upstream", "downstream", "lateral"]
    variable: Literal["discharge", "water_level"]
    series: tuple[TimeValue, ...] = Field(min_length=1)
    chainage_m: FiniteFloat | None = Field(default=None, ge=0.0)

    @model_validator(mode="after")
    def validate_series(self) -> Self:
        """Require increasing samples and a chainage only for lateral inflows."""

        times = [item.time_seconds for item in self.series]
        if any(right <= left for left, right in zip(times, times[1:])):
            raise ValueError("boundary sample times must be strictly increasing")
        if self.location == "lateral":
            if self.variable != "discharge" or self.chainage_m is None:
                raise ValueError("lateral boundary requires discharge and chainage_m")
        elif self.chainage_m is not None:
            raise ValueError("endpoint boundary must not define chainage_m")
        return self


class SectionInitialState(StrictHydraulicModel):
    """Represent an optional section-specific initial water level and discharge."""

    cross_section_id: str = Field(min_length=1, max_length=128)
    water_level_m: FiniteFloat
    discharge_m3s: FiniteFloat


class InitialCondition(StrictHydraulicModel):
    """Represent either a uniform state or an explicit state at every section."""

    water_level_m: FiniteFloat | None = None
    discharge_m3s: FiniteFloat | None = None
    by_section: tuple[SectionInitialState, ...] = ()

    @model_validator(mode="after")
    def validate_mode(self) -> Self:
        """Forbid ambiguous mixtures of uniform and section-specific initial states."""

        has_uniform = self.water_level_m is not None or self.discharge_m3s is not None
        if self.by_section and has_uniform:
            raise ValueError(
                "initial condition cannot mix uniform and by-section values"
            )
        if self.by_section:
            return self
        if self.water_level_m is None or self.discharge_m3s is None:
            raise ValueError(
                "uniform initial condition requires water level and discharge"
            )
        return self


class HydraulicStructure(StrictHydraulicModel):
    """Preserve structure geometry, behaviour, and operation without solver syntax."""

    id: str = Field(min_length=1, max_length=128)
    name: str = Field(
        default="Unnamed hydraulic structure", min_length=1, max_length=128
    )
    branch_id: str = Field(min_length=1, max_length=128)
    kind: Literal[
        "weir",
        "culvert",
        "bridge",
        "gate",
        "sluice",
        "pump",
        "orifice",
        "dam",
        "storage_link",
        "compound",
    ]
    chainage_m: FiniteFloat = Field(ge=0.0)
    location_geometry: dict[str, Any] | None = None
    geometry: dict[str, Any] = Field(default_factory=dict)
    hydraulic_law_type: str = Field(default="none", min_length=1, max_length=64)
    hydraulic_law_parameters: dict[str, Any] = Field(default_factory=dict)
    operation_rule_type: Literal[
        "fixed",
        "time_series",
        "water_level_controlled",
        "scenario_specific",
    ] = "fixed"
    operation_parameters: dict[str, Any] = Field(default_factory=dict)
    scenario_id: str | None = Field(default=None, min_length=1, max_length=128)
    status: Literal["draft", "active", "inactive", "retired"] = "active"
    metadata: dict[str, Any] = Field(default_factory=dict)
    # Compatibility field for pre-Engineering-03 snapshots. New callers use the
    # separated geometry/law/operation fields above.
    parameters: dict[str, Any] = Field(default_factory=dict)


class SimulationSettings(StrictHydraulicModel):
    """Carry physical time controls without exposing an internal CFL scheme."""

    duration_seconds: FiniteFloat = Field(gt=0.0)
    time_step_seconds: FiniteFloat = Field(gt=0.0)
    output_interval_seconds: FiniteFloat = Field(gt=0.0)

    @model_validator(mode="after")
    def validate_intervals(self) -> Self:
        """Ensure requested output has one deterministic complete time axis."""

        if self.time_step_seconds > self.duration_seconds:
            raise ValueError("time step cannot exceed duration")
        if self.output_interval_seconds > self.duration_seconds:
            raise ValueError("output interval cannot exceed duration")
        if self.output_interval_seconds < self.time_step_seconds:
            raise ValueError("output interval cannot be shorter than the time step")
        output_count = self.duration_seconds / self.output_interval_seconds
        if not isclose(output_count, round(output_count), rel_tol=0.0, abs_tol=1e-9):
            raise ValueError("output interval must divide duration exactly")
        return self

    def expected_output_times(self) -> tuple[float, ...]:
        """Return the required t=0 through duration output cadence."""

        count = round(self.duration_seconds / self.output_interval_seconds)
        return tuple(index * self.output_interval_seconds for index in range(count + 1))


class Hydraulic1DModel(StrictHydraulicModel):
    """Freeze the Dayu unified model before selecting an external engine adapter."""

    schema_version: Literal[HYDRAULIC_1D_INPUT_SCHEMA] = HYDRAULIC_1D_INPUT_SCHEMA
    simulation_id: str = Field(min_length=1, max_length=128)
    scenario_id: str = Field(min_length=1, max_length=128)
    network_id: str = Field(min_length=1, max_length=128)
    nodes: tuple[HydraulicNode, ...] = ()
    branches: tuple[HydraulicBranch, ...] = Field(min_length=1)
    cross_sections: tuple[HydraulicCrossSection, ...] = Field(min_length=2)
    boundaries: tuple[BoundaryCondition, ...] = Field(min_length=2)
    initial_condition: InitialCondition
    settings: SimulationSettings
    structures: tuple[HydraulicStructure, ...] = ()
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_references(self) -> Self:
        """Close topology, section, boundary, and initial-state references."""

        branch_map = {item.id: item for item in self.branches}
        if len(branch_map) != len(self.branches):
            raise ValueError("branch ids must be unique")
        node_map = {item.id: item for item in self.nodes}
        if len(node_map) != len(self.nodes):
            raise ValueError("node ids must be unique")
        if node_map:
            for branch in self.branches:
                if branch.upstream_node_id not in node_map:
                    raise ValueError("branch upstream node reference is dangling")
                if branch.downstream_node_id not in node_map:
                    raise ValueError("branch downstream node reference is dangling")
        section_map = {item.id: item for item in self.cross_sections}
        if len(section_map) != len(self.cross_sections):
            raise ValueError("cross-section ids must be unique")
        for section in self.cross_sections:
            branch = branch_map.get(section.branch_id)
            if branch is None:
                raise ValueError("cross section references an unknown branch")
            if (
                not branch.start_chainage_m
                <= section.chainage_m
                <= branch.end_chainage_m
            ):
                raise ValueError("cross-section chainage lies outside its branch")
        for branch in self.branches:
            sections = sorted(
                (item for item in self.cross_sections if item.branch_id == branch.id),
                key=lambda item: item.chainage_m,
            )
            if len(sections) < 2:
                raise ValueError("each branch requires at least two cross sections")
            if any(
                right.chainage_m <= left.chainage_m
                for left, right in zip(sections, sections[1:])
            ):
                raise ValueError("cross-section chainages must be strictly increasing")
            if not isclose(
                sections[0].chainage_m,
                branch.start_chainage_m,
                rel_tol=0.0,
                abs_tol=1e-6,
            ):
                raise ValueError("first cross section must coincide with branch start")
            if not isclose(
                sections[-1].chainage_m,
                branch.end_chainage_m,
                rel_tol=0.0,
                abs_tol=1e-6,
            ):
                raise ValueError("last cross section must coincide with branch end")
        for boundary in self.boundaries:
            branch = branch_map.get(boundary.branch_id)
            if branch is None:
                raise ValueError("boundary references an unknown branch")
            if boundary.chainage_m is not None and not (
                branch.start_chainage_m <= boundary.chainage_m <= branch.end_chainage_m
            ):
                raise ValueError("lateral boundary chainage lies outside its branch")
        state_ids = [
            item.cross_section_id for item in self.initial_condition.by_section
        ]
        if len(state_ids) != len(set(state_ids)):
            raise ValueError("initial-state cross-section ids must be unique")
        if state_ids and set(state_ids) != set(section_map):
            raise ValueError("by-section initial state must cover every cross section")
        for structure in self.structures:
            branch = branch_map.get(structure.branch_id)
            if branch is None:
                raise ValueError("structure references an unknown branch")
            if (
                not branch.start_chainage_m
                <= structure.chainage_m
                <= branch.end_chainage_m
            ):
                raise ValueError("structure chainage lies outside its branch")
        structure_ids = [item.id for item in self.structures]
        if len(structure_ids) != len(set(structure_ids)):
            raise ValueError("structure ids must be unique")
        return self

    @classmethod
    def parse_snapshot(cls, payload: Any) -> "Hydraulic1DModel":
        """Parse untrusted input and expose one stable adapter-facing error code."""

        try:
            return cls.model_validate(payload)
        except Exception as exc:
            raise Hydraulic1DValidationError(
                "DAYU_HYDRAULIC_1D_INPUT_INVALID",
                str(exc),
                field_path="hydraulic_model",
            ) from exc


class HydraulicResultRecord(StrictHydraulicModel):
    """Represent one solver-neutral hydraulic value at a section and timestamp."""

    simulation_id: str
    scenario_id: str
    engine: str
    engine_version: str
    branch_id: str
    chainage_m: FiniteFloat
    cross_section_id: str
    timestamp: datetime | FiniteFloat
    water_level_m: FiniteFloat
    depth_m: FiniteFloat = Field(ge=0.0)
    discharge_m3s: FiniteFloat
    velocity_m_s: FiniteFloat
    flow_area_m2: FiniteFloat = Field(ge=0.0)
    wet_area_m2: FiniteFloat | None = Field(default=None, ge=0.0)
    hydraulic_radius_m: FiniteFloat | None = Field(default=None, ge=0.0)
    top_width_m: FiniteFloat | None = Field(default=None, ge=0.0)
    froude_number: FiniteFloat | None = Field(default=None, ge=0.0)


class HydraulicResult(StrictHydraulicModel):
    """Return a complete Dayu result without exposing raw MASCARET rows to clients."""

    schema_version: Literal[HYDRAULIC_RESULT_SCHEMA] = HYDRAULIC_RESULT_SCHEMA
    simulation_id: str
    scenario_id: str
    engine: str
    engine_version: str
    records: tuple[HydraulicResultRecord, ...]
    diagnostics: dict[str, Any] = Field(default_factory=dict)
    artifacts: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-compatible representation for API and worker persistence."""

        return self.model_dump(mode="json")
