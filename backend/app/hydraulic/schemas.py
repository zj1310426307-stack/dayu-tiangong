"""Contracts for hydraulic coordinates, topology, profiles, imports, and exports."""

from datetime import date, datetime
import math
import re
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


ALLOWED_SOURCE_SRIDS = {4326, 4490, 4546, 4547, 4548, 4549}
ALLOWED_ENGINEERING_SRIDS = {4546, 4547, 4548, 4549}
CENTRAL_MERIDIANS = {4546: 111.0, 4547: 114.0, 4548: 117.0, 4549: 120.0}
EPSG_PATTERN = re.compile(r"^EPSG:(\d{4,6})$")


class CoordinateReferenceSpec(BaseModel):
    """Declare the complete horizontal/vertical coordinate interpretation for an import."""

    model_config = ConfigDict(extra="forbid")

    source_crs: str
    engineering_crs: str
    coordinate_mode: Literal["geographic", "projected"]
    axis_mapping: Literal["x_easting_y_northing", "x_northing_y_easting"]
    x_field: str = Field(default="x", min_length=1, max_length=64)
    y_field: str = Field(default="y", min_length=1, max_length=64)
    z_field: str | None = Field(default=None, min_length=1, max_length=64)
    horizontal_unit: Literal["m", "degree"]
    vertical_unit: Literal["m"] = "m"
    vertical_datum: str = Field(min_length=1, max_length=64)
    central_meridian: float
    zone_width: Literal[3]
    zone_prefix_mode: Literal["none", "included", "stripped"] = "none"

    @staticmethod
    def _srid(value: str, field: str) -> int:
        """Parse an EPSG identifier and provide a field-specific validation error."""

        match = EPSG_PATTERN.fullmatch(value.strip().upper())
        if match is None:
            raise ValueError(f"{field} must use EPSG:<code>")
        return int(match.group(1))

    @model_validator(mode="after")
    def validate_coordinate_contract(self) -> "CoordinateReferenceSpec":
        """Reject unknown CRS, silent axis assumptions, and geographic engineering CRS."""

        source = self._srid(self.source_crs, "source_crs")
        engineering = self._srid(self.engineering_crs, "engineering_crs")
        if source not in ALLOWED_SOURCE_SRIDS:
            raise ValueError(f"source_crs must be one of {sorted(ALLOWED_SOURCE_SRIDS)}")
        if engineering not in ALLOWED_ENGINEERING_SRIDS:
            raise ValueError(f"engineering_crs must be one of {sorted(ALLOWED_ENGINEERING_SRIDS)}")
        expected_mode = "geographic" if source in {4326, 4490} else "projected"
        if self.coordinate_mode != expected_mode:
            raise ValueError(f"coordinate_mode must be {expected_mode} for EPSG:{source}")
        expected_unit = "degree" if expected_mode == "geographic" else "m"
        if self.horizontal_unit != expected_unit:
            raise ValueError(f"horizontal_unit must be {expected_unit} for EPSG:{source}")
        expected_meridian = CENTRAL_MERIDIANS.get(engineering)
        if not math.isclose(
            self.central_meridian, expected_meridian or self.central_meridian, abs_tol=1.0e-9
        ):
            raise ValueError(
                f"central_meridian must be {expected_meridian:g} for EPSG:{engineering}"
            )
        return self

    @property
    def source_srid(self) -> int:
        """Return the validated numeric source SRID."""

        return self._srid(self.source_crs, "source_crs")

    @property
    def engineering_srid(self) -> int:
        """Return the validated projected engineering SRID."""

        return self._srid(self.engineering_crs, "engineering_crs")

    def normalize_xy(self, x: float, y: float) -> tuple[float, float]:
        """Map supplied axes into easting/longitude then northing/latitude order."""

        if self.axis_mapping == "x_easting_y_northing":
            return float(x), float(y)
        return float(y), float(x)


class HydraulicIssue(BaseModel):
    """Describe one parser or quality finding without hiding severity."""

    severity: Literal["error", "warning", "info", "passed"]
    code: str = Field(min_length=1, max_length=64)
    message: str = Field(min_length=1)
    entity_type: str | None = None
    entity_ref: str | None = None
    context: dict[str, object] = Field(default_factory=dict)


class HydraulicChainageInput(BaseModel):
    """Represent one ordered source coordinate and adopted chainage on a branch."""

    model_config = ConfigDict(extra="forbid")

    chainage: float = Field(ge=0)
    x: float
    y: float
    z: float | None = None
    point_code: str | None = Field(default=None, max_length=64)


class HydraulicBranchInput(BaseModel):
    """Represent one branch and its source-order vertices."""

    model_config = ConfigDict(extra="forbid")

    code: str = Field(min_length=1, max_length=64)
    river_name: str = Field(min_length=1, max_length=128)
    branch_name: str = Field(min_length=1, max_length=128)
    flow_direction: Literal["forward", "reverse", "unknown"] = "unknown"
    source_revision: str | None = Field(default=None, max_length=64)
    points: list[HydraulicChainageInput] = Field(min_length=2)

    @field_validator("points")
    @classmethod
    def validate_chainage_order(
        cls, value: list[HydraulicChainageInput]
    ) -> list[HydraulicChainageInput]:
        """Require finite, strictly increasing adopted chainage in source point order."""

        if any(not math.isfinite(point.chainage) for point in value):
            raise ValueError("branch chainage values must be finite")
        if any(right.chainage <= left.chainage for left, right in zip(value, value[1:])):
            raise ValueError("branch chainage values must be strictly increasing")
        return value


MarkerType = Literal[
    "none",
    "left_bank",
    "right_bank",
    "left_levee",
    "right_levee",
    "low_flow_left",
    "low_flow_right",
    "thalweg",
]


class HydraulicSectionPointInput(BaseModel):
    """Represent one profile point with marker and optional surveyed source XYZ."""

    model_config = ConfigDict(extra="forbid")

    sequence: int = Field(ge=0)
    distance: float = Field(ge=0)
    elevation: float
    marker_type: MarkerType = "none"
    point_code: str | None = Field(default=None, max_length=64)
    x: float | None = None
    y: float | None = None
    z: float | None = None

    @model_validator(mode="after")
    def validate_point(self) -> "HydraulicSectionPointInput":
        """Reject one-sided coordinates and non-finite profile values."""

        if (self.x is None) != (self.y is None):
            raise ValueError("section point x and y must be provided together")
        if not math.isfinite(self.distance) or not math.isfinite(self.elevation):
            raise ValueError("section distance and elevation must be finite")
        return self


class HydraulicRoughnessZoneInput(BaseModel):
    """Declare one non-overlapping Manning interval for a profile."""

    model_config = ConfigDict(extra="forbid")

    zone_order: int = Field(ge=0)
    offset_start_m: float = Field(ge=0)
    offset_end_m: float = Field(gt=0)
    manning_n: float = Field(gt=0)
    zone_type: str = Field(default="channel", min_length=1, max_length=32)

    @model_validator(mode="after")
    def validate_range(self) -> "HydraulicRoughnessZoneInput":
        """Require each roughness interval to have positive width."""

        if self.offset_end_m <= self.offset_start_m:
            raise ValueError("roughness offset_end_m must exceed offset_start_m")
        return self


class HydraulicCrossSectionInput(BaseModel):
    """Represent one section location plus one Topography ID profile."""

    model_config = ConfigDict(extra="forbid")

    section_code: str = Field(min_length=1, max_length=64)
    section_name: str | None = Field(default=None, max_length=128)
    branch_code: str = Field(min_length=1, max_length=64)
    chainage: float = Field(ge=0)
    topography_id: str = Field(default="DEFAULT", min_length=1, max_length=64)
    survey_date: date | None = None
    survey_method: str | None = Field(default=None, max_length=64)
    bed_elevation_m: float | None = None
    bed_elevation_source: Literal["unconfirmed", "surveyed", "design", "synthetic"] = "unconfirmed"
    bed_elevation_confirmed_by: str | None = Field(default=None, max_length=128)
    bed_elevation_confirmed_at: datetime | None = None
    default_manning_n: float = Field(default=0.03, gt=0)
    location_x: float | None = None
    location_y: float | None = None
    axis_points: list[tuple[float, float]] = Field(default_factory=list)
    roughness_zones: list[HydraulicRoughnessZoneInput] = Field(default_factory=list)
    points: list[HydraulicSectionPointInput] = Field(min_length=3)

    @field_validator("axis_points")
    @classmethod
    def validate_axis_points(cls, value: list[tuple[float, float]]) -> list[tuple[float, float]]:
        """Allow no surveyed axis or a valid LineString with at least two points."""

        if value and len(value) < 2:
            raise ValueError("cross-section axis requires at least two points")
        return value

    @field_validator("points")
    @classmethod
    def validate_profile_order(
        cls, value: list[HydraulicSectionPointInput]
    ) -> list[HydraulicSectionPointInput]:
        """Require unique order and strictly increasing finite offsets."""

        sequences = [point.sequence for point in value]
        if sequences != sorted(sequences) or len(sequences) != len(set(sequences)):
            raise ValueError("section point sequence must be unique and increasing")
        if any(right.distance <= left.distance for left, right in zip(value, value[1:])):
            raise ValueError("section point distance must be strictly increasing")
        return value

    @model_validator(mode="after")
    def validate_location_and_roughness(self) -> "HydraulicCrossSectionInput":
        """Reject incomplete XY and overlapping/out-of-profile roughness intervals."""

        if (self.location_x is None) != (self.location_y is None):
            raise ValueError("section location_x and location_y must be provided together")
        bed_authority = (
            self.bed_elevation_m,
            self.bed_elevation_confirmed_by,
            self.bed_elevation_confirmed_at,
        )
        if self.bed_elevation_source == "unconfirmed":
            if any(value is not None for value in bed_authority):
                raise ValueError(
                    "unconfirmed bed elevation must remain null; no Profile minimum is inferred"
                )
        elif any(value is None for value in bed_authority):
            raise ValueError(
                "authoritative bed elevation requires elevation, source, actor, and time"
            )
        ordered = sorted(self.roughness_zones, key=lambda item: item.zone_order)
        if [item.zone_order for item in ordered] != list(range(len(ordered))):
            raise ValueError("roughness zone_order must start at zero and remain contiguous")
        lower, upper = self.points[0].distance, self.points[-1].distance
        for left, right in zip(ordered, ordered[1:]):
            if right.offset_start_m < left.offset_end_m:
                raise ValueError("roughness zones must not overlap")
        if any(item.offset_start_m < lower or item.offset_end_m > upper for item in ordered):
            raise ValueError("roughness zones must remain within the profile offset range")
        return self


class HydraulicExchangePayload(BaseModel):
    """Normalize supported files into a neutral version-independent DTO."""

    model_config = ConfigDict(extra="forbid")

    network_code: str = Field(min_length=1, max_length=64)
    network_name: str = Field(min_length=1, max_length=128)
    source_srid: int
    source_kind: Literal["mike11", "excel", "csv", "geojson", "shp", "dxf", "api"]
    coordinate_reference: CoordinateReferenceSpec | None = None
    branches: list[HydraulicBranchInput] = Field(default_factory=list)
    sections: list[HydraulicCrossSectionInput] = Field(default_factory=list)

    @field_validator("source_srid")
    @classmethod
    def validate_source_srid(cls, value: int) -> int:
        """Require an explicit source CRS from the approved allow-list."""

        if value not in ALLOWED_SOURCE_SRIDS:
            raise ValueError(f"source_srid must be one of {sorted(ALLOWED_SOURCE_SRIDS)}")
        return value

    @model_validator(mode="after")
    def validate_payload_identity(self) -> "HydraulicExchangePayload":
        """Reject empty input, duplicate identities, and mismatched coordinate declarations."""

        if not self.branches and not self.sections:
            raise ValueError("hydraulic exchange payload contains no branches or cross sections")
        branch_codes = [branch.code for branch in self.branches]
        section_codes = [(section.section_code, section.topography_id) for section in self.sections]
        if len(branch_codes) != len(set(branch_codes)):
            raise ValueError("branch codes must be unique within one import")
        if len(section_codes) != len(set(section_codes)):
            raise ValueError(
                "cross-section code and Topography ID pairs must be unique within one import"
            )
        if self.coordinate_reference and self.coordinate_reference.source_srid != self.source_srid:
            raise ValueError("source_srid and coordinate_reference.source_crs must match")
        return self


class HydraulicNodeRecord(BaseModel):
    """Return one hydraulic node for the network tree and map."""

    id: int
    node_code: str
    node_name: str | None
    node_type: str
    geometry: dict[str, Any]


class HydraulicReachRecord(BaseModel):
    """Return one branch reach and its adopted chainage interval."""

    id: int
    reach_code: str
    reach_type: str
    start_chainage_m: float
    end_chainage_m: float
    upstream_node_id: int
    downstream_node_id: int
    length_m: float
    geometry: dict[str, Any]


class HydraulicSectionSummary(BaseModel):
    """Return the lightweight section identity used by the network tree."""

    id: int
    section_code: str
    chainage: float
    topography_id: str
    profile_count: int = Field(ge=0)
    point_count: int = Field(ge=0)
    orientation_status: str
    bed_elevation_m: float | None
    bed_elevation_source: str


class HydraulicBranchRecord(BaseModel):
    """Return one branch with nodes, reaches, and ordered section summaries."""

    id: int
    legacy_river_id: int | None
    branch_code: str
    river_name: str
    branch_name: str
    start_chainage: float
    end_chainage: float
    length_m: float
    direction_status: str
    upstream_node_id: int | None
    downstream_node_id: int | None
    section_count: int = Field(ge=0)
    reach_count: int = Field(ge=0)
    reaches: list[HydraulicReachRecord] = Field(default_factory=list)
    sections: list[HydraulicSectionSummary] = Field(default_factory=list)


class HydraulicNetworkRecord(BaseModel):
    """Return one versioned network with coordinate, node, branch, and reach state."""

    id: int
    dataset_version_id: int
    code: str
    name: str
    display_crs: str
    engineering_crs: str | None
    horizontal_unit: str
    vertical_datum: str
    vertical_unit: str
    source_kind: str
    branch_count: int = Field(ge=0)
    node_count: int = Field(ge=0)
    reach_count: int = Field(ge=0)
    nodes: list[HydraulicNodeRecord] = Field(default_factory=list)
    branches: list[HydraulicBranchRecord] = Field(default_factory=list)


class HydraulicSectionPointRecord(BaseModel):
    """Return one normalized profile point."""

    sequence: int
    distance: float
    elevation: float
    marker_type: str
    point_code: str | None
    x: float | None = None
    y: float | None = None
    z: float | None = None


class HydraulicRoughnessZoneRecord(BaseModel):
    """Return one normalized roughness interval."""

    zone_order: int
    offset_start_m: float
    offset_end_m: float
    manning_n: float
    zone_type: str


class HydraulicHydraulicRowRecord(BaseModel):
    """Return one processed stage/property row."""

    stage_m: float
    area_m2: float
    top_width_m: float
    wetted_perimeter_m: float
    hydraulic_radius_m: float
    conveyance: float


class HydraulicProcessingRecord(BaseModel):
    """Return cached profile processing metadata and table rows."""

    id: int
    profile_hash: str
    processor_version: str
    vertical_step_m: float
    status: str
    minimum_stage_m: float | None
    maximum_stage_m: float | None
    generated_at: datetime | None
    diagnostics: dict[str, Any]
    rows: list[HydraulicHydraulicRowRecord] = Field(default_factory=list)


class HydraulicProfileRecord(BaseModel):
    """Return one Topography ID, points, roughness, and optional processed table."""

    id: int
    topography_id: str
    survey_date: date | None
    survey_method: str | None
    vertical_datum: str
    vertical_unit: str
    default_manning_n: float
    profile_hash: str
    is_active: bool
    points: list[HydraulicSectionPointRecord]
    roughness_zones: list[HydraulicRoughnessZoneRecord]
    processing: HydraulicProcessingRecord | None = None


class HydraulicSectionDetail(BaseModel):
    """Return one section location plus all selectable survey profiles."""

    id: int
    dataset_version_id: int
    branch_id: int
    branch_code: str
    legacy_cross_section_id: int | None
    section_code: str
    section_name: str
    chainage: float
    computed_chainage_m: float | None
    chainage_source: str
    snap_distance_m: float | None
    orientation_status: str
    bed_elevation_m: float | None
    bed_elevation_source: str
    bed_elevation_confirmed_by: str | None
    bed_elevation_confirmed_at: datetime | None
    location_geometry: dict[str, object]
    axis_geometry: dict[str, object] | None
    profiles: list[HydraulicProfileRecord]


class HydraulicImportJobRecord(BaseModel):
    """Return immutable source identity, coordinate evidence, issues, and status."""

    id: int
    job_code: str
    dataset_version_id: int
    filename: str
    source_format: str
    source_srid: int
    source_hash_sha256: str
    config_hash: str
    coordinate_reference: CoordinateReferenceSpec
    transformation_evidence: dict[str, Any]
    parser_profile: str
    status: str
    record_counts: dict[str, int]
    issues: list[HydraulicIssue]
    native_validation_status: str
    created_at: datetime
    completed_at: datetime | None


class HydraulicImportPreview(BaseModel):
    """Return a file preview without mutating authoritative hydraulic entities."""

    job: HydraulicImportJobRecord
    payload: HydraulicExchangePayload | None


class HydraulicImportCommitRequest(BaseModel):
    """Confirm a preview only when its coordinate/parser configuration hash matches."""

    job_code: str = Field(min_length=1, max_length=32)
    preview_config_hash: str = Field(min_length=64, max_length=64)


class HydraulicValidationRequest(BaseModel):
    """Select one Dataset Version for persisted hydraulic quality checks."""

    dataset_version_id: int = Field(gt=0)


class HydraulicValidationRunRecord(BaseModel):
    """Return one persisted validation run and its findings."""

    id: int
    run_code: str
    dataset_version_id: int
    status: str
    summary: dict[str, Any]
    created_at: datetime
    completed_at: datetime | None
    results: list[HydraulicIssue]


class HydraulicTopologyBuildRequest(BaseModel):
    """Configure deterministic topology construction in the network engineering CRS."""

    snap_tolerance_m: float = Field(default=0.5, gt=0, le=100)
    minimum_reach_length_m: float = Field(default=0.1, gt=0, le=1000)


class HydraulicTopologyReport(BaseModel):
    """Summarize deterministic topology output and QA findings."""

    network_id: int
    engineering_crs: str
    snap_tolerance_m: float
    node_count: int
    branch_count: int
    reach_count: int
    issues: list[HydraulicIssue]


class HydraulicBranchActionRecord(BaseModel):
    """Return the branch state after reverse or chainage recalculation."""

    branch_id: int
    direction_status: str
    start_chainage_m: float
    end_chainage_m: float
    length_m: float


class HydraulicLocateRequest(BaseModel):
    """Configure cross-section location tolerance and optional audited override."""

    snap_tolerance_m: float = Field(default=5, gt=0, le=1000)
    manual_chainage_m: float | None = Field(default=None, ge=0)
    override_reason: str | None = Field(default=None, min_length=3, max_length=500)
    actor: str | None = Field(default=None, min_length=1, max_length=128)

    @model_validator(mode="after")
    def validate_override_audit(self) -> "HydraulicLocateRequest":
        """Require reason and actor whenever an adopted chainage is manually overridden."""

        if self.manual_chainage_m is not None and (not self.override_reason or not self.actor):
            raise ValueError("manual chainage requires override_reason and actor")
        return self


class HydraulicProcessRequest(BaseModel):
    """Select the finite vertical step used for hydraulic table generation."""

    vertical_step_m: float = Field(default=0.05, gt=0, le=10)


class HydraulicBatchProcessRequest(HydraulicProcessRequest):
    """Select multiple profiles for one deterministic batch processing request."""

    profile_ids: list[int] = Field(min_length=1, max_length=1000)


class HydraulicCapabilityResponse(BaseModel):
    """Report actual general import and isolated exchange-adapter capabilities."""

    exchange_profile: str
    native_xns11_available: bool
    native_nwk11_available: bool
    supported_imports: list[str]
    supported_exports: list[str]
    source_srids: list[int]
    engineering_srids: list[int]
    axis_mappings: list[str]
    limitation: str


HydraulicStructureType = Literal[
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
HydraulicStructureStatus = Literal["draft", "active", "inactive", "retired"]
HydraulicOperationRule = Literal[
    "fixed",
    "time_series",
    "water_level_controlled",
    "scenario_specific",
]


class HydraulicStructureCreate(BaseModel):
    """Create one located structure with separated geometry and hydraulic behaviour."""

    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    dataset_version_id: int = Field(gt=0)
    network_id: int = Field(gt=0)
    branch_id: int = Field(gt=0)
    structure_code: str = Field(min_length=1, max_length=64)
    structure_name: str = Field(min_length=1, max_length=128)
    structure_type: HydraulicStructureType
    chainage_m: float = Field(ge=0)
    x: float
    y: float
    crest_elevation_m: float | None = None
    invert_elevation_m: float | None = None
    width_m: float | None = Field(default=None, gt=0)
    height_m: float | None = Field(default=None, gt=0)
    hydraulic_law_type: str = Field(default="none", min_length=1, max_length=64)
    hydraulic_parameters: dict[str, Any] = Field(default_factory=dict)
    operation_rule_type: HydraulicOperationRule = "fixed"
    operation_parameters: dict[str, Any] = Field(default_factory=dict)
    status: HydraulicStructureStatus = "draft"
    metadata: dict[str, Any] = Field(default_factory=dict)


class HydraulicStructureUpdate(BaseModel):
    """Edit mutable structure fields while preserving version/network ownership."""

    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    branch_id: int | None = Field(default=None, gt=0)
    structure_code: str | None = Field(default=None, min_length=1, max_length=64)
    structure_name: str | None = Field(default=None, min_length=1, max_length=128)
    structure_type: HydraulicStructureType | None = None
    chainage_m: float | None = Field(default=None, ge=0)
    x: float | None = None
    y: float | None = None
    crest_elevation_m: float | None = None
    invert_elevation_m: float | None = None
    width_m: float | None = Field(default=None, gt=0)
    height_m: float | None = Field(default=None, gt=0)
    hydraulic_law_type: str | None = Field(default=None, min_length=1, max_length=64)
    hydraulic_parameters: dict[str, Any] | None = None
    operation_rule_type: HydraulicOperationRule | None = None
    operation_parameters: dict[str, Any] | None = None
    status: HydraulicStructureStatus | None = None
    metadata: dict[str, Any] | None = None

    @model_validator(mode="after")
    def validate_location_pair(self) -> "HydraulicStructureUpdate":
        """Require X/Y to move together so a structure never acquires partial geometry."""

        if (self.x is None) != (self.y is None):
            raise ValueError("x and y must be supplied together")
        return self


class HydraulicStructureRecord(BaseModel):
    """Return a unified structure, spatial location, and current capability status."""

    id: int
    dataset_version_id: int
    network_id: int
    branch_id: int
    structure_code: str
    structure_name: str
    structure_type: HydraulicStructureType
    chainage_m: float
    location_geometry: dict[str, Any]
    crest_elevation_m: float | None
    invert_elevation_m: float | None
    width_m: float | None
    height_m: float | None
    hydraulic_law_type: str
    hydraulic_parameters: dict[str, Any]
    operation_rule_type: HydraulicOperationRule
    operation_parameters: dict[str, Any]
    status: HydraulicStructureStatus
    metadata: dict[str, Any]
    legacy_gate_id: int | None
    legacy_pump_id: int | None
    solver_status: str
    solver_reason: str


class HydraulicStructureScenarioUpsert(BaseModel):
    """Override a structure for one Simulation Case without copying its geometry."""

    model_config = ConfigDict(extra="forbid")

    status_override: HydraulicStructureStatus | None = None
    hydraulic_parameters_override: dict[str, Any] = Field(default_factory=dict)
    operation_rule_type_override: HydraulicOperationRule | None = None
    operation_parameters_override: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)


class HydraulicStructureScenarioRecord(HydraulicStructureScenarioUpsert):
    """Return one persisted case-specific structure override."""

    id: int
    dataset_version_id: int
    case_id: int
    structure_id: int
    updated_at: datetime


class SolverCapabilityRecord(BaseModel):
    """Expose one version-bound engine capability without adapter internals."""

    engine: str
    engine_version: str
    adapter_version: str
    feature: str
    status: str
    reason: str
    benchmark_ids: list[str]
    verified_at: str | None


class HydraulicNetworkGraphRecord(BaseModel):
    """Return reusable topology relationships for GIS and model clients."""

    network_id: int
    nodes: list[dict[str, Any]]
    branches: list[dict[str, Any]]
    cross_sections: list[dict[str, Any]]
    structures: list[HydraulicStructureRecord]
    boundaries: list[dict[str, Any]]
