"""Strict Phase 1C contracts for annotations, spatial analysis and thematic mapping."""

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


AnnotationType = Literal[
    "river", "gate", "pump", "cross_section", "hydrology_station",
    "dispatch_event", "parameter", "place",
]
RelatedType = Literal[
    "river", "gate", "pump", "cross_section", "hydrology_station", "dispatch_event"
]
SpatialObjectType = Literal["river", "gate", "pump", "cross_section"]
AnalysisFeatureType = Literal["river", "gate", "pump", "cross_section", "hydrology_station"]


class AnnotationBase(BaseModel):
    """Validate one versioned professional label and its scale/style semantics."""

    model_config = ConfigDict(extra="forbid")

    dataset_version_id: int = Field(gt=0)
    annotation_type: AnnotationType
    name: str = Field(min_length=1, max_length=128)
    text: str = Field(min_length=1, max_length=256)
    description: str | None = Field(default=None, max_length=1000)
    longitude: float = Field(ge=-180, le=180)
    latitude: float = Field(ge=-90, le=90)
    rotation: float = Field(default=0, ge=0, lt=360)
    font_size: int = Field(default=14, ge=8, le=72)
    color: str = Field(default="#E8F7FF", pattern=r"^#[0-9A-Fa-f]{6}$")
    visible_scale_min: float = Field(default=0, ge=0)
    visible_scale_max: float = Field(default=500000, ge=0)
    related_type: RelatedType | None = None
    related_id: int | None = Field(default=None, gt=0)

    @model_validator(mode="after")
    def validate_ranges_and_relation(self) -> "AnnotationBase":
        """Keep scale ranges ordered and relation fields atomic."""

        if self.visible_scale_max < self.visible_scale_min:
            raise ValueError("visible_scale_max must be >= visible_scale_min")
        if (self.related_type is None) != (self.related_id is None):
            raise ValueError("related_type and related_id must be supplied together")
        return self


class AnnotationCreate(AnnotationBase):
    """Create one annotation in the selected authoritative dataset version."""


class AnnotationUpdate(BaseModel):
    """Update editable annotation fields without moving it across data versions."""

    model_config = ConfigDict(extra="forbid")

    annotation_type: AnnotationType | None = None
    name: str | None = Field(default=None, min_length=1, max_length=128)
    text: str | None = Field(default=None, min_length=1, max_length=256)
    description: str | None = Field(default=None, max_length=1000)
    longitude: float | None = Field(default=None, ge=-180, le=180)
    latitude: float | None = Field(default=None, ge=-90, le=90)
    rotation: float | None = Field(default=None, ge=0, lt=360)
    font_size: int | None = Field(default=None, ge=8, le=72)
    color: str | None = Field(default=None, pattern=r"^#[0-9A-Fa-f]{6}$")
    visible_scale_min: float | None = Field(default=None, ge=0)
    visible_scale_max: float | None = Field(default=None, ge=0)
    related_type: RelatedType | None = None
    related_id: int | None = Field(default=None, gt=0)


class AnnotationRecord(AnnotationBase):
    """Return one persisted label plus its dynamic display text for the selected time."""

    id: int = Field(gt=0)
    display_text: str
    dynamic_lines: list[str]
    dynamic_source: Literal["static", "simulation", "dispatch"]
    created_time: datetime


class AnnotationCollection(BaseModel):
    """Return a bounded label page and explicit collection/rendering metadata."""

    model_config = ConfigDict(extra="forbid")

    items: list[AnnotationRecord]
    total: int = Field(ge=0)
    limit: int = Field(ge=1, le=5000)
    offset: int = Field(ge=0)
    dataset_version_id: int = Field(gt=0)
    scale_denominator: float = Field(ge=0)
    renderer: Literal["Cesium LabelCollection"] = "Cesium LabelCollection"
    demo_data: Literal[True] = True


class LayerCatalogItem(BaseModel):
    """Describe one layer without exposing GeoServer administrator endpoints."""

    model_config = ConfigDict(extra="forbid")

    key: str
    title: str
    group: Literal["base", "engineering", "annotation", "model", "dispatch", "analysis"]
    source: Literal["WMS", "WMTS", "MVT", "FastAPI", "PostGIS analysis"]
    geometry: Literal["raster", "point", "line", "polygon", "mixed"]
    version_isolated: Literal[True] = True
    default_visible: bool
    dynamic: bool


class SpatialFeature(BaseModel):
    """Represent one version-safe analysis hit as compact GeoJSON."""

    model_config = ConfigDict(extra="forbid")

    object_type: AnalysisFeatureType
    object_id: int = Field(gt=0)
    name: str
    geometry: dict[str, Any]
    properties: dict[str, Any] = Field(default_factory=dict)
    distance_m: float | None = Field(default=None, ge=0)


class TraceResponse(BaseModel):
    """Return upstream/downstream topology and assets controlled by one selected river."""

    model_config = ConfigDict(extra="forbid")

    dataset_version_id: int = Field(gt=0)
    selected_river: SpatialFeature
    upstream_rivers: list[SpatialFeature]
    downstream_rivers: list[SpatialFeature]
    gates: list[SpatialFeature]
    pumps: list[SpatialFeature]
    cross_sections: list[SpatialFeature]
    crs: Literal["EPSG:4490"] = "EPSG:4490"


class SpatialSelectRequest(BaseModel):
    """Select supported engineering objects intersecting one CGCS2000 rectangle."""

    model_config = ConfigDict(extra="forbid")

    dataset_version_id: int = Field(gt=0)
    bbox: list[float] = Field(min_length=4, max_length=4)
    object_types: list[SpatialObjectType] = Field(
        default_factory=lambda: ["river", "gate", "pump", "cross_section"]
    )
    limit_per_type: int = Field(default=500, ge=1, le=1000)

    @field_validator("bbox")
    @classmethod
    def validate_bbox(cls, value: list[float]) -> list[float]:
        """Reject inverted or out-of-range geographic rectangles."""

        min_x, min_y, max_x, max_y = value
        if not (-180 <= min_x < max_x <= 180 and -90 <= min_y < max_y <= 90):
            raise ValueError("bbox must be minx,miny,maxx,maxy in EPSG:4490")
        return value


class SpatialSelectResponse(BaseModel):
    """Group one box-selection result by engineering object type."""

    model_config = ConfigDict(extra="forbid")

    dataset_version_id: int = Field(gt=0)
    bbox: list[float]
    features: list[SpatialFeature]
    counts: dict[str, int]
    crs: Literal["EPSG:4490"] = "EPSG:4490"


class BufferAnalysisRequest(BaseModel):
    """Request a metre-based facility impact buffer from one existing object."""

    model_config = ConfigDict(extra="forbid")

    dataset_version_id: int = Field(gt=0)
    object_type: SpatialObjectType
    object_id: int = Field(gt=0)
    distance_m: float = Field(gt=0, le=100000)
    include_types: list[SpatialObjectType] = Field(
        default_factory=lambda: ["river", "gate", "pump", "cross_section"]
    )


class BufferAnalysisResponse(BaseModel):
    """Return the geography-derived buffer polygon and impacted assets."""

    model_config = ConfigDict(extra="forbid")

    dataset_version_id: int = Field(gt=0)
    source: SpatialFeature
    distance_m: float = Field(gt=0)
    buffer_geometry: dict[str, Any]
    impacted: list[SpatialFeature]
    distance_basis: Literal["PostGIS geography metres"] = "PostGIS geography metres"


class NearestFacilityRequest(BaseModel):
    """Find nearby gate, pump and annotated hydrology-station facilities."""

    model_config = ConfigDict(extra="forbid")

    dataset_version_id: int = Field(gt=0)
    longitude: float = Field(ge=-180, le=180)
    latitude: float = Field(ge=-90, le=90)
    facility_types: list[Literal["gate", "pump", "hydrology_station"]] = Field(
        default_factory=lambda: ["gate", "pump", "hydrology_station"]
    )
    limit: int = Field(default=5, ge=1, le=50)
    max_distance_m: float | None = Field(default=None, gt=0, le=1000000)


class NearestFacilityResponse(BaseModel):
    """Return facilities ordered by exact geography distance in metres."""

    model_config = ConfigDict(extra="forbid")

    dataset_version_id: int = Field(gt=0)
    origin: dict[str, Any]
    facilities: list[SpatialFeature]
    distance_basis: Literal["PostGIS geography metres"] = "PostGIS geography metres"


class ComparisonWaterSample(BaseModel):
    """Expose one A/B hydraulic difference at a stable cross-section identifier."""

    model_config = ConfigDict(extra="forbid")

    section_id: int = Field(gt=0)
    section_code: str
    river_id: int = Field(gt=0)
    longitude: float
    latitude: float
    baseline_water_level: float
    comparison_water_level: float
    water_level_difference: float
    baseline_velocity: float
    comparison_velocity: float
    velocity_difference: float
    baseline_flow: float
    comparison_flow: float
    flow_difference: float


class ComparisonStructureSample(BaseModel):
    """Expose one baseline/comparison gate or pump state difference."""

    model_config = ConfigDict(extra="forbid")

    structure_type: Literal["gate", "pump"]
    structure_id: int = Field(gt=0)
    name: str
    longitude: float
    latitude: float
    baseline_value: float | None
    comparison_value: float | None
    value_difference: float | None
    baseline_flow: float | None
    comparison_flow: float | None
    flow_difference: float | None


class GISComparisonFrame(BaseModel):
    """Return one atomic same-version A/B spatial comparison frame."""

    model_config = ConfigDict(extra="forbid")

    dataset_version_id: int = Field(gt=0)
    baseline_task_id: int = Field(gt=0)
    comparison_task_id: int = Field(gt=0)
    baseline_dispatch_run_id: int | None = Field(default=None, gt=0)
    comparison_dispatch_run_id: int | None = Field(default=None, gt=0)
    requested_time_seconds: float = Field(ge=0)
    baseline_time_seconds: float | None = Field(default=None, ge=0)
    comparison_time_seconds: float | None = Field(default=None, ge=0)
    water_samples: list[ComparisonWaterSample]
    structure_samples: list[ComparisonStructureSample]
    execution_authorized: Literal[False] = False
    demo_data: Literal[True] = True


class ThematicMapRequest(BaseModel):
    """Describe a bounded, deterministic PDF map generated from authoritative GIS/model data."""

    model_config = ConfigDict(extra="forbid")

    dataset_version_id: int = Field(gt=0)
    title: str = Field(default="大禹·天工 水动力专题图", min_length=1, max_length=120)
    time_seconds: float = Field(default=0, ge=0)
    task_id: int | None = Field(default=None, gt=0)
    dispatch_run_id: int | None = Field(default=None, gt=0)
    bbox: list[float] | None = Field(default=None, min_length=4, max_length=4)
    author: str = Field(default="Dayu Tiangong", min_length=1, max_length=64)

    @field_validator("bbox")
    @classmethod
    def validate_optional_bbox(cls, value: list[float] | None) -> list[float] | None:
        """Validate the optional map extent with the same EPSG:4490 boundary."""

        if value is None:
            return value
        min_x, min_y, max_x, max_y = value
        if not (-180 <= min_x < max_x <= 180 and -90 <= min_y < max_y <= 90):
            raise ValueError("bbox must be minx,miny,maxx,maxy in EPSG:4490")
        return value
