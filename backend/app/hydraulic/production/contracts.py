"""Solver-neutral contracts for the Production-04 engineering workflow."""

from __future__ import annotations

from datetime import UTC, datetime
import math
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, FiniteFloat, model_validator


QualityFlag = Literal["GOOD", "SUSPECT", "MISSING", "REJECTED"]
HydraulicVariable = Literal["water_level", "discharge", "velocity"]
QASeverity = Literal["ERROR", "WARNING", "INFO"]
WorkflowState = Literal[
    "DRAFT",
    "QA_PASSED",
    "CALIBRATED",
    "VALIDATED",
    "PRODUCTION_APPROVED",
]


class ProductionSeriesPoint(BaseModel):
    """Represent one explicit sample without treating missing data as zero."""

    model_config = ConfigDict(extra="forbid")

    time_seconds: FiniteFloat = Field(ge=0)
    value: FiniteFloat | None = None
    quality_flag: QualityFlag = "GOOD"
    timestamp: datetime | None = None

    @model_validator(mode="after")
    def validate_missing_semantics(self) -> "ProductionSeriesPoint":
        """Require missing/rejected samples to remain empty and timestamp-aware."""

        if self.quality_flag in {"MISSING", "REJECTED"} and self.value is not None:
            raise ValueError("MISSING/REJECTED samples must not carry a numeric value")
        if self.quality_flag in {"GOOD", "SUSPECT"} and self.value is None:
            raise ValueError("GOOD/SUSPECT samples require a numeric value")
        if self.timestamp is not None and self.timestamp.tzinfo is None:
            raise ValueError("absolute timestamps must include an explicit timezone")
        return self


class ProductionSeries(BaseModel):
    """Describe an observed, simulated, boundary, or external hydraulic series."""

    model_config = ConfigDict(extra="forbid")

    series_id: str = Field(min_length=1, max_length=128)
    variable: HydraulicVariable
    unit: Literal["m", "m3/s", "m/s"]
    samples: list[ProductionSeriesPoint]
    source: str = Field(min_length=1, max_length=256)
    branch_id: str | None = Field(default=None, max_length=128)
    chainage_m: FiniteFloat | None = Field(default=None, ge=0)
    station_id: str | None = Field(default=None, max_length=128)
    vertical_datum: str = Field(default="UNKNOWN", min_length=1, max_length=64)
    time_basis: Literal["relative", "absolute"] = "relative"
    timezone: str | None = Field(default=None, max_length=64)

    @model_validator(mode="after")
    def validate_series(self) -> "ProductionSeries":
        """Reject duplicate/non-monotonic times and incompatible units."""

        expected = {"water_level": "m", "discharge": "m3/s", "velocity": "m/s"}
        if self.unit != expected[self.variable]:
            raise ValueError(f"{self.variable} series unit must be {expected[self.variable]}")
        times = [float(sample.time_seconds) for sample in self.samples]
        if times != sorted(times) or len(times) != len(set(times)):
            raise ValueError("series times must be unique and monotonically increasing")
        if self.time_basis == "absolute":
            if not self.timezone or any(sample.timestamp is None for sample in self.samples):
                raise ValueError("absolute series require timezone and timestamp on every sample")
        return self


class TimeAlignmentOptions(BaseModel):
    """Make comparison alignment explicit and reproducible."""

    model_config = ConfigDict(extra="forbid")

    method: Literal["exact", "interpolation", "nearest-with-tolerance"] = "exact"
    tolerance_seconds: FiniteFloat = Field(default=0.0, ge=0)
    minimum_valid_samples: int = Field(default=3, ge=1)
    minimum_coverage_ratio: FiniteFloat = Field(default=0.5, ge=0, le=1)

    @model_validator(mode="after")
    def validate_tolerance(self) -> "TimeAlignmentOptions":
        """Require a positive tolerance only for nearest matching."""

        if self.method == "nearest-with-tolerance" and self.tolerance_seconds <= 0:
            raise ValueError("nearest-with-tolerance requires a positive tolerance_seconds")
        return self


class HydraulicMetrics(BaseModel):
    """Keep dimensional metrics separate for one hydraulic variable."""

    variable: HydraulicVariable
    unit: str
    alignment_method: str
    valid_sample_count: int = Field(ge=0)
    observed_sample_count: int = Field(ge=0)
    coverage_ratio: float = Field(ge=0, le=1)
    sufficient_samples: bool
    mae: float | None = None
    rmse: float | None = None
    bias: float | None = None
    nse: float | None = None
    r_squared: float | None = None
    peak_value_error: float | None = None
    peak_relative_error: float | None = None
    peak_time_error_seconds: float | None = None


class MetricEvaluationRequest(BaseModel):
    """Evaluate one observed/simulated variable pair."""

    observed: ProductionSeries
    simulated: ProductionSeries
    alignment: TimeAlignmentOptions = Field(default_factory=TimeAlignmentOptions)


class QAIssue(BaseModel):
    """Expose one map-locatable model QA finding."""

    code: str = Field(min_length=1, max_length=96)
    severity: QASeverity
    category: Literal[
        "Network", "CrossSection", "Boundary", "Structure", "Observation", "CRS"
    ]
    entity_type: str = Field(min_length=1, max_length=64)
    entity_id: str | None = Field(default=None, max_length=128)
    message: str = Field(min_length=1)
    suggestion: str | None = None
    location: dict[str, Any] | None = None
    context: dict[str, Any] = Field(default_factory=dict)


class ProductionBranch(BaseModel):
    """Carry the QA-relevant subset of a directed hydraulic branch."""

    branch_id: str = Field(min_length=1, max_length=128)
    start_chainage_m: FiniteFloat = Field(ge=0)
    end_chainage_m: FiniteFloat = Field(gt=0)
    direction_confirmed: bool
    centerline: list[tuple[FiniteFloat, FiniteFloat]] = Field(min_length=2)
    upstream_node_id: str | None = None
    downstream_node_id: str | None = None

    @model_validator(mode="after")
    def validate_range(self) -> "ProductionBranch":
        """Reject zero-length and reversed adopted chainage ranges."""

        if self.end_chainage_m <= self.start_chainage_m:
            raise ValueError("branch end_chainage_m must exceed start_chainage_m")
        return self


class ProductionCrossSection(BaseModel):
    """Carry section geometry and authority needed by the production QA gate."""

    section_id: str = Field(min_length=1, max_length=128)
    branch_id: str = Field(min_length=1, max_length=128)
    chainage_m: FiniteFloat = Field(ge=0)
    offsets_m: list[FiniteFloat] = Field(min_length=3)
    elevations_m: list[FiniteFloat] = Field(min_length=3)
    vertical_datum: str = Field(min_length=1, max_length=64)
    orientation_confirmed: bool
    axis: list[tuple[FiniteFloat, FiniteFloat]] = Field(default_factory=list)
    location: tuple[FiniteFloat, FiniteFloat] | None = None

    @model_validator(mode="after")
    def validate_profile_shape(self) -> "ProductionCrossSection":
        """Keep profile arrays aligned while leaving QA to report engineering issues."""

        if len(self.offsets_m) != len(self.elevations_m):
            raise ValueError("cross-section offset/elevation arrays must align")
        if self.axis and len(self.axis) < 2:
            raise ValueError("cross-section axis requires at least two points")
        return self


class ProductionBoundary(BaseModel):
    """Describe one endpoint or lateral boundary for QA."""

    boundary_id: str = Field(min_length=1, max_length=128)
    branch_id: str = Field(min_length=1, max_length=128)
    location: Literal["upstream", "downstream", "lateral"]
    chainage_m: FiniteFloat | None = Field(default=None, ge=0)
    series: ProductionSeries

    @model_validator(mode="after")
    def validate_location(self) -> "ProductionBoundary":
        """Require chainage only for lateral inflow and enforce variable semantics."""

        if (self.location == "lateral") != (self.chainage_m is not None):
            raise ValueError("only lateral boundaries require chainage_m")
        if self.location == "upstream" and self.series.variable != "discharge":
            raise ValueError("upstream production boundary must be discharge")
        if self.location == "downstream" and self.series.variable != "water_level":
            raise ValueError("downstream production boundary must be water_level")
        if self.location == "lateral" and self.series.variable != "discharge":
            raise ValueError("lateral production boundary must be discharge")
        return self


class ProductionStructure(BaseModel):
    """Carry structure readiness without assuming unsupported solver behavior."""

    structure_id: str = Field(min_length=1, max_length=128)
    structure_type: Literal[
        "weir", "culvert", "bridge", "gate", "sluice", "pump", "orifice", "dam"
    ]
    branch_id: str = Field(min_length=1, max_length=128)
    chainage_m: FiniteFloat = Field(ge=0)
    vertical_datum: str = Field(min_length=1, max_length=64)
    capability_status: Literal[
        "VERIFIED_NATIVE", "VERIFIED_EQUIVALENT", "UNVERIFIED", "UNSUPPORTED"
    ]
    status: Literal["draft", "active", "inactive", "retired"] = "active"
    location: tuple[FiniteFloat, FiniteFloat] | None = None


class QAThresholds(BaseModel):
    """Configure project-level QA warnings without changing global truth."""

    maximum_projection_distance_m: FiniteFloat = Field(default=50.0, gt=0)
    minimum_section_spacing_m: FiniteFloat = Field(default=1.0, gt=0)
    maximum_section_spacing_m: FiniteFloat = Field(default=5000.0, gt=0)
    maximum_bed_jump_m: FiniteFloat = Field(default=10.0, gt=0)
    maximum_reverse_bed_slope: FiniteFloat = Field(default=0.02, ge=0)


class HydraulicModelQARequest(BaseModel):
    """Collect one immutable view for centralized pre-run QA."""

    model_config = ConfigDict(extra="forbid")

    engineering_crs: str
    horizontal_unit: str
    vertical_datum: str
    simulation_duration_seconds: FiniteFloat = Field(gt=0)
    branches: list[ProductionBranch]
    cross_sections: list[ProductionCrossSection]
    boundaries: list[ProductionBoundary]
    observations: list[ProductionSeries] = Field(default_factory=list)
    structures: list[ProductionStructure] = Field(default_factory=list)
    thresholds: QAThresholds = Field(default_factory=QAThresholds)


class HydraulicModelQAResult(BaseModel):
    """Return a non-bypassable software gate and map-ready findings."""

    ruleset_version: str
    error_count: int = Field(ge=0)
    warning_count: int = Field(ge=0)
    info_count: int = Field(ge=0)
    run_allowed: bool
    issues: list[QAIssue]
    spacing_statistics: dict[str, float | int | None] = Field(default_factory=dict)
    thalweg_profile: list[dict[str, float | str]] = Field(default_factory=list)


class TimeSeriesColumnMapping(BaseModel):
    """Map a boundary/observation table into one normalized series."""

    time: str
    value: str
    quality_flag: str | None = None


class TimeSeriesImportOptions(BaseModel):
    """Declare one boundary or observation import without guessed metadata."""

    series_kind: Literal["boundary", "observation"]
    series_id: str = Field(min_length=1, max_length=128)
    variable: Literal["water_level", "discharge"]
    unit: Literal["m", "m3/s"]
    source: str = Field(min_length=1, max_length=256)
    branch_id: str = Field(min_length=1, max_length=128)
    chainage_m: FiniteFloat = Field(ge=0)
    station_id: str | None = Field(default=None, max_length=128)
    vertical_datum: str = Field(default="UNKNOWN", min_length=1, max_length=64)
    time_basis: Literal["relative", "absolute"]
    timezone: str | None = Field(default=None, max_length=64)
    column_mapping: TimeSeriesColumnMapping
    sheet_name: str | None = Field(default=None, max_length=128)

    @model_validator(mode="after")
    def validate_import_semantics(self) -> "TimeSeriesImportOptions":
        """Require observation identity and dimensional unit consistency."""

        expected = "m" if self.variable == "water_level" else "m3/s"
        if self.unit != expected:
            raise ValueError(f"{self.variable} series unit must be {expected}")
        if self.series_kind == "observation" and not self.station_id:
            raise ValueError("observation import requires station_id")
        return self


class TimeSeriesImportPreview(BaseModel):
    """Return one normalized series and lineage without committing it."""

    source_filename: str
    source_sha256: str
    row_count: int = Field(ge=0)
    issues: list[QAIssue]
    series: ProductionSeries
    provenance: dict[str, Any]


class CalibrationParameter(BaseModel):
    """Define a grouped parameter override shared by explicit model entities."""

    group_id: str = Field(min_length=1, max_length=128)
    parameter: Literal["manning_n"] = "manning_n"
    target_ids: list[str] = Field(min_length=1)
    values: list[FiniteFloat] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_values(self) -> "CalibrationParameter":
        """Reject physically invalid or duplicate candidate values."""

        if len(self.target_ids) != len(set(self.target_ids)):
            raise ValueError("calibration parameter target_ids must be unique")
        try:
            target_ids = [int(value) for value in self.target_ids]
        except ValueError as exc:
            raise ValueError("manning_n target_ids must be integer Cross Section IDs") from exc
        if any(value <= 0 for value in target_ids):
            raise ValueError("manning_n target_ids must be positive Cross Section IDs")
        if len(self.values) != len(set(float(value) for value in self.values)):
            raise ValueError("calibration parameter values must be unique")
        if self.parameter == "manning_n" and any(not 0 < value <= 0.3 for value in self.values):
            raise ValueError("manning_n candidate values must be in (0, 0.3]")
        return self


class ParameterSweepRequest(BaseModel):
    """Bound deterministic calibration candidates before tasks are queued."""

    parameters: list[CalibrationParameter] = Field(min_length=1)
    max_runs: int = Field(default=100, ge=1, le=1000)


class CalibrationCandidate(BaseModel):
    """Represent one immutable candidate and its optional evaluated metrics."""

    candidate_id: str
    overrides: dict[str, float]
    metrics: list[HydraulicMetrics] = Field(default_factory=list)
    task_id: int | None = None
    status: Literal["planned", "queued", "running", "completed", "failed", "cancelled"] = (
        "planned"
    )
    objective_score: float | None = None
    rank: int | None = None
    qualified: bool = False


class ParameterSweepPlan(BaseModel):
    """Return bounded candidates and progress dimensions."""

    total_candidates: int = Field(ge=1)
    max_runs: int = Field(ge=1)
    candidates: list[CalibrationCandidate]


class CalibrationObjective(BaseModel):
    """Define an explicit score instead of an unexplained composite metric."""

    mode: Literal["water-level-focused", "discharge-focused", "multi-metric"]
    weights: dict[str, FiniteFloat] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_weights(self) -> "CalibrationObjective":
        """Require non-negative weights with a positive sum."""

        if any(value < 0 for value in self.weights.values()) or sum(self.weights.values()) <= 0:
            raise ValueError("calibration objective weights must be non-negative with positive sum")
        return self


class CalibrationRankingRequest(BaseModel):
    """Rank completed candidates under one declared objective."""

    candidates: list[CalibrationCandidate]
    objective: CalibrationObjective


class CalibrationPromotionRequest(BaseModel):
    """Record explicit human acceptance without silently editing the source model."""

    candidate_id: str = Field(min_length=1, max_length=128)
    accepted_by: str = Field(min_length=1, max_length=128)
    acceptance_reason: str = Field(min_length=1, max_length=1000)
    acceptance_criteria: AcceptanceCriteria


class DatasetWindow(BaseModel):
    """Separate calibration and validation evidence windows."""

    dataset_id: str = Field(min_length=1, max_length=128)
    event_id: str = Field(min_length=1, max_length=128)
    station_ids: list[str] = Field(min_length=1)
    start_time: datetime
    end_time: datetime
    role: Literal["calibration", "validation"]
    holdout_type: Literal["independent_event", "temporal_holdout", "same_data"]

    @model_validator(mode="after")
    def validate_window(self) -> "DatasetWindow":
        """Require timezone-aware, positive evidence windows."""

        if self.start_time.tzinfo is None or self.end_time.tzinfo is None:
            raise ValueError("dataset windows require timezone-aware timestamps")
        if self.end_time <= self.start_time:
            raise ValueError("dataset window end_time must exceed start_time")
        return self


class ValidationIndependenceResult(BaseModel):
    """Explain whether evidence can support a formal VALIDATED state."""

    independent: bool
    temporal_holdout: bool
    issues: list[QAIssue]


class ValidationIndependenceRequest(BaseModel):
    """Compare explicitly separated calibration and validation windows."""

    calibration: DatasetWindow
    validation: DatasetWindow


class AcceptanceCriteria(BaseModel):
    """Store project-specific acceptance limits; no global values are implied."""

    maximum_water_level_rmse: FiniteFloat | None = Field(default=None, ge=0)
    maximum_discharge_rmse: FiniteFloat | None = Field(default=None, ge=0)
    maximum_peak_relative_error: FiniteFloat | None = Field(default=None, ge=0)
    maximum_peak_time_error_seconds: FiniteFloat | None = Field(default=None, ge=0)
    minimum_nse: FiniteFloat | None = None
    minimum_r_squared: FiniteFloat | None = Field(default=None, ge=0, le=1)
    minimum_observation_coverage: FiniteFloat = Field(default=0.5, ge=0, le=1)
    maximum_mass_balance_relative_error: FiniteFloat | None = Field(default=None, ge=0)


class AcceptanceEvaluationRequest(BaseModel):
    """Evaluate metrics and independent-data evidence without self-approval."""

    metrics: list[HydraulicMetrics]
    criteria: AcceptanceCriteria
    independence: ValidationIndependenceResult
    mass_balance_relative_error: FiniteFloat | None = Field(default=None, ge=0)


class AcceptanceEvaluation(BaseModel):
    """Return software gate state, never a professional approval claim."""

    criteria_passed: bool
    model_state: WorkflowState
    checks: list[dict[str, Any]]
    professional_approval_required: bool = True


class ExternalColumnMapping(BaseModel):
    """Map legally exported external columns into Dayu variables."""

    branch: str
    chainage: str
    time: str
    water_level: str | None = None
    discharge: str | None = None
    velocity: str | None = None

    @model_validator(mode="after")
    def validate_variables(self) -> "ExternalColumnMapping":
        """Require at least one hydraulic result variable."""

        if not any((self.water_level, self.discharge, self.velocity)):
            raise ValueError("external mapping requires H, Q, or velocity")
        return self


class ExternalBranchMapping(BaseModel):
    """Require explicit branch and chainage alignment."""

    external_branch: str
    dayu_branch: str
    chainage_scale: FiniteFloat = Field(default=1.0, gt=0)
    chainage_offset_m: FiniteFloat = 0.0
    direction: Literal["same", "reverse"] = "same"
    external_origin_m: FiniteFloat = 0.0
    dayu_reference_end_m: FiniteFloat | None = Field(default=None, ge=0)

    def map_chainage(self, value: float) -> float:
        """Apply the reviewed unit, origin, and direction mapping."""

        normalized = (value - float(self.external_origin_m)) * float(self.chainage_scale)
        if self.direction == "reverse":
            if self.dayu_reference_end_m is None:
                raise ValueError("reverse chainage mapping requires dayu_reference_end_m")
            return float(self.dayu_reference_end_m) - normalized + float(self.chainage_offset_m)
        return normalized + float(self.chainage_offset_m)


class ExternalResultImportOptions(BaseModel):
    """Freeze an external mapping profile and provenance fields."""

    external_model_name: str = Field(min_length=1, max_length=128)
    external_model_version: str = Field(default="UNKNOWN", min_length=1, max_length=128)
    scenario: str = Field(min_length=1, max_length=128)
    vertical_datum: str = Field(min_length=1, max_length=64)
    time_basis: Literal["relative", "absolute"]
    timezone: str | None = None
    column_mapping: ExternalColumnMapping
    branch_mappings: list[ExternalBranchMapping] = Field(min_length=1)
    sheet_name: str | None = Field(default=None, max_length=128)


class ExternalResultPoint(BaseModel):
    """Represent one normalized external result row."""

    external_branch: str
    branch_id: str
    external_chainage: float
    chainage_m: float
    time_seconds: float = Field(ge=0)
    timestamp: datetime | None = None
    water_level_m: float | None = None
    discharge_m3s: float | None = None
    velocity_m_s: float | None = None


class ExternalResultPreview(BaseModel):
    """Return a dry-run import without mutating authoritative data."""

    source_filename: str
    source_sha256: str
    row_count: int = Field(ge=0)
    branch_count: int = Field(ge=0)
    variables: list[HydraulicVariable]
    issues: list[QAIssue]
    points: list[ExternalResultPoint]
    provenance: dict[str, Any]


class ExternalComparisonRequest(BaseModel):
    """Compare unified Dayu results with an external reference model."""

    dayu_series: list[ProductionSeries]
    external_series: list[ProductionSeries]
    alignment: TimeAlignmentOptions


class ExternalComparisonResult(BaseModel):
    """Return location-specific and longitudinal model-to-model differences."""

    metrics: list[HydraulicMetrics]
    longitudinal: list[dict[str, Any]]
    time_series: list[dict[str, Any]]
    reference_not_ground_truth: bool = True


class HydraulicResultPoint(BaseModel):
    """Represent one unified result sample used by engineering products."""

    scenario_id: str
    branch_id: str
    cross_section_id: str
    chainage_m: FiniteFloat = Field(ge=0)
    time_seconds: FiniteFloat = Field(ge=0)
    water_level_m: FiniteFloat
    discharge_m3s: FiniteFloat
    velocity_m_s: FiniteFloat
    depth_m: FiniteFloat | None = Field(default=None, ge=0)
    flow_area_m2: FiniteFloat | None = Field(default=None, ge=0)
    bed_elevation_m: FiniteFloat | None = None
    left_bank_elevation_m: FiniteFloat | None = None
    right_bank_elevation_m: FiniteFloat | None = None
    geometry: dict[str, Any] | None = None


class ResultProductRequest(BaseModel):
    """Generate products from exact unified results without invented attributes."""

    project_id: str
    model_version: str
    baseline_scenario_id: str | None = None
    project_scenario_id: str
    afflux_threshold_m: FiniteFloat = Field(default=0.01, ge=0)
    points: list[HydraulicResultPoint] = Field(min_length=1)
    calibration_table: list[dict[str, Any]] = Field(default_factory=list)
    validation_table: list[dict[str, Any]] = Field(default_factory=list)
    external_comparison_table: list[dict[str, Any]] = Field(default_factory=list)


class ResultProductBundle(BaseModel):
    """Return reusable tables and map features for UI and export."""

    max_envelope: list[dict[str, Any]]
    longitudinal_profile: list[dict[str, Any]]
    scenario_difference: list[dict[str, Any]]
    maximum_afflux: dict[str, Any] | None
    afflux_reaches: list[dict[str, Any]]
    key_section_table: list[dict[str, Any]]
    calibration_table: list[dict[str, Any]]
    validation_table: list[dict[str, Any]]
    external_comparison_table: list[dict[str, Any]]
    geojson: dict[str, Any]


class AcceptanceManifestRequest(BaseModel):
    """Build a machine-readable evidence manifest from immutable identities."""

    project: str
    model_version: str
    qa: dict[str, Any]
    engine: dict[str, Any]
    runtime: dict[str, Any]
    calibration: dict[str, Any] | None = None
    validation: dict[str, Any] | None = None
    comparison: dict[str, Any] | None = None
    run: dict[str, Any]
    metrics: dict[str, Any]
    result_hashes: dict[str, str]


class AcceptanceManifest(BaseModel):
    """Return canonical evidence and a digest suitable for exported artifacts."""

    schema_version: Literal["dayu-production-acceptance-v1"] = "dayu-production-acceptance-v1"
    generated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    manifest_hash: str
    evidence: dict[str, Any]


class ProductionCapabilityResponse(BaseModel):
    """Expose the implemented software framework and honest evidence boundary."""

    framework_version: Literal["hydro-1d-production-04-v1"] = "hydro-1d-production-04-v1"
    engineering_import: list[str]
    model_qa: bool
    calibration: list[str]
    validation: list[str]
    external_comparison: list[str]
    result_products: list[str]
    real_project_status: Literal["DATA_NOT_AVAILABLE"] = "DATA_NOT_AVAILABLE"
    real_project_reason: str


def finite_number(value: object, field: str) -> float:
    """Normalize one finite number with a stable error for parsers."""

    if isinstance(value, bool):
        raise ValueError(f"{field} must be a finite number")
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field} must be a finite number") from exc
    if not math.isfinite(result):
        raise ValueError(f"{field} must be a finite number")
    return result
