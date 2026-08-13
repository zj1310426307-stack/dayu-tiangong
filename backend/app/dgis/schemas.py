"""Strict contracts for the DGIS spatiotemporal foundation."""

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


FeatureStateType = Literal[
    "water_level", "flow", "rainfall", "gate", "pump", "flood_risk"
]
FeatureStateSource = Literal["observation", "simulation", "dispatch", "import"]
SimulationLayerType = Literal[
    "water_level", "velocity", "flood_risk", "terrain", "facility_3d"
]
SimulationServiceType = Literal["COG", "TITILER", "MVT", "WMS", "3D_TILES"]


class PointGeometry(BaseModel):
    """Represent one CGCS2000 point without accepting arbitrary GeoJSON shapes."""

    model_config = ConfigDict(extra="forbid")

    type: Literal["Point"] = "Point"
    coordinates: tuple[float, float]

    @field_validator("coordinates")
    @classmethod
    def validate_coordinates(cls, value: tuple[float, float]) -> tuple[float, float]:
        """Reject coordinates outside the longitude and latitude domains."""

        longitude, latitude = value
        if not -180 <= longitude <= 180 or not -90 <= latitude <= 90:
            raise ValueError("coordinates are outside EPSG:4490 longitude/latitude bounds")
        return value


class FeatureStateCreate(BaseModel):
    """Create one immutable state sample for observation or simulation replay."""

    model_config = ConfigDict(extra="forbid")

    dataset_version_id: int = Field(gt=0)
    feature_type: FeatureStateType
    feature_id: int = Field(gt=0)
    timestamp: datetime
    state_json: dict[str, Any]
    geometry: PointGeometry
    source: FeatureStateSource
    task_id: int | None = Field(default=None, gt=0)

    @model_validator(mode="after")
    def validate_simulation_task(self) -> "FeatureStateCreate":
        """Require provenance for simulated state while keeping observations independent."""

        if self.source == "simulation" and self.task_id is None:
            raise ValueError("task_id is required for simulation state")
        return self


class FeatureStateRecord(FeatureStateCreate):
    """Return the persistent identity of one spatiotemporal state sample."""

    id: int = Field(gt=0)


class FeatureStateCollection(BaseModel):
    """Return a bounded state page plus the query and storage semantics."""

    model_config = ConfigDict(extra="forbid")

    items: list[FeatureStateRecord]
    total: int = Field(ge=0)
    dataset_version_id: int = Field(gt=0)
    storage: Literal["TimescaleDB hypertable + PostGIS"] = "TimescaleDB hypertable + PostGIS"
    crs: Literal["EPSG:4490"] = "EPSG:4490"
    demo_data: Literal[True] = True


class SimulationLayerRecord(BaseModel):
    """Describe one versioned simulation visualization service."""

    model_config = ConfigDict(extra="forbid")

    id: int = Field(gt=0)
    dataset_version_id: int = Field(gt=0)
    task_id: int | None
    name: str
    layer_type: SimulationLayerType
    time_start: datetime | None
    time_end: datetime | None
    service_type: SimulationServiceType
    service_url: str
    style: dict[str, Any]
    version: str
    created_time: datetime


class ThreeDTilesAsset(BaseModel):
    """Expose one Cesium-native 3D Tiles asset with explicit provenance."""

    model_config = ConfigDict(extra="forbid")

    layer_id: int = Field(gt=0)
    name: str
    tileset_url: str
    version: str
    maximum_screen_space_error: float = Field(gt=0)
    demo_data: Literal[True] = True


class DGISComponent(BaseModel):
    """Report one open-source component and its responsibility boundary."""

    model_config = ConfigDict(extra="forbid")

    key: Literal["postgis", "timescaledb", "geoserver", "geonode", "gdal", "martin", "titiler", "cesium"]
    name: str
    responsibility: str
    status: Literal["online", "configured", "optional", "offline"]
    endpoint: str | None = None
    version: str | None = None


class DGISHealthResponse(BaseModel):
    """Summarize the integrated foundation without leaking administrator credentials."""

    model_config = ConfigDict(extra="forbid")

    status: Literal["healthy", "degraded"]
    database: Literal["single PostgreSQL/PostGIS instance"] = "single PostgreSQL/PostGIS instance"
    timescale_hypertable: bool
    components: list[DGISComponent]
    vector_tile_sources: list[str]
    simulation_layer_count: int = Field(ge=0)
    demo_data: Literal[True] = True


class DGISCatalogResponse(BaseModel):
    """Return frontend-safe spatial data, tile, raster, and 3D catalog entries."""

    model_config = ConfigDict(extra="forbid")

    components: list[DGISComponent]
    simulation_layers: list[SimulationLayerRecord]
    vector_tile_template: str
    vector_tile_sources: list[str]
    geonode_url: str | None
    conversion_formats: dict[str, list[str]]


class ConversionCapabilityResponse(BaseModel):
    """Describe installed GDAL engines and the bounded format contract."""

    model_config = ConfigDict(extra="forbid")

    status: Literal["online", "offline"]
    gdal_version: str | None
    vector_inputs: list[str]
    raster_inputs: list[str]
    outputs: list[str]
    cad_note: str


class ConversionJobResponse(BaseModel):
    """Return one completed GDAL operation with paths relative to controlled storage."""

    model_config = ConfigDict(extra="forbid")

    job_id: str
    operation: Literal["inspect", "geojson", "cog", "postgis"]
    status: Literal["success"]
    input_format: str
    output_format: str
    output_name: str | None
    details: dict[str, Any]
