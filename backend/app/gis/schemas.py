"""GIS GeoJSON、分页、统计和健康检查的 Pydantic 契约。"""

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class GeoJSONFeature(BaseModel):
    """表示单个带业务属性的 GeoJSON Feature。"""

    model_config = ConfigDict(extra="forbid")

    type: Literal["Feature"] = "Feature"
    id: int
    geometry: dict[str, Any]
    properties: dict[str, Any]


class PaginationMeta(BaseModel):
    """描述有界空间读取的总量、分页和数据口径。"""

    model_config = ConfigDict(extra="forbid")

    total: int = Field(ge=0)
    limit: int = Field(ge=1, le=1000)
    offset: int = Field(ge=0)
    dataset_version_id: int = Field(gt=0)
    bbox: list[float] | None = None
    demo_data: Literal[True] = True
    crs: Literal["EPSG:4490"] = "EPSG:4490"


class GeoJSONFeatureCollection(BaseModel):
    """表示带分页元数据的 GeoJSON FeatureCollection。"""

    model_config = ConfigDict(extra="forbid")

    type: Literal["FeatureCollection"] = "FeatureCollection"
    features: list[GeoJSONFeature]
    meta: PaginationMeta


class GISStatisticsResponse(BaseModel):
    """返回四类 DEMO DATA 资产的真实数据库计数。"""

    model_config = ConfigDict(extra="forbid")

    dataset_version_id: int = Field(gt=0)
    rivers: int = Field(ge=0)
    gates: int = Field(ge=0)
    pumps: int = Field(ge=0)
    cross_sections: int = Field(ge=0)
    demo_data: Literal[True] = True
    source: Literal["PostGIS / DEMO DATA"] = "PostGIS / DEMO DATA"


class GISHealthResponse(BaseModel):
    """返回数据库和 PostGIS 扩展的真实连接信息。"""

    model_config = ConfigDict(extra="forbid")

    status: Literal["healthy"]
    database: str
    postgis_version: str
    srid: Literal[4490] = 4490


class GISWaterSample(BaseModel):
    """Represent one version-safe hydraulic result at a mapped cross section."""

    model_config = ConfigDict(extra="forbid")

    section_id: int = Field(gt=0)
    section_code: str
    river_id: int = Field(gt=0)
    longitude: float
    latitude: float
    water_level: float
    flow: float
    velocity: float
    risk_level: Literal["normal", "warning", "danger"]
    velocity_level: Literal["low", "medium", "high"]
    flow_direction: Literal["downstream", "upstream", "stationary"]
    flow_bearing_degrees: float = Field(ge=0, lt=360)


class GISStructureSample(BaseModel):
    """Expose one simulated gate or pump state without implying real device telemetry."""

    model_config = ConfigDict(extra="forbid")

    structure_type: Literal["gate", "pump"]
    structure_id: int = Field(gt=0)
    code: str
    name: str
    longitude: float
    latitude: float
    requested_value: float | None
    actual_value: float | None
    flow: float
    power_kw: float | None
    state: Literal["open", "closed", "running", "stopped", "unknown"]
    constraint_flags: list[str]


class GISInteractionFrame(BaseModel):
    """Return one atomic version/time frame for every dynamic GIS overlay."""

    model_config = ConfigDict(extra="forbid")

    dataset_version_id: int = Field(gt=0)
    task_id: int | None = Field(default=None, gt=0)
    dispatch_run_id: int | None = Field(default=None, gt=0)
    task_status: str | None = None
    timeline: list[float]
    requested_time_seconds: float = Field(ge=0)
    selected_time_seconds: float | None = Field(default=None, ge=0)
    warning_level: float
    danger_level: float
    threshold_source: Literal["dispatch_plan", "demo_default"]
    water_samples: list[GISWaterSample]
    structure_samples: list[GISStructureSample]
    crs: Literal["EPSG:4490"] = "EPSG:4490"
    demo_data: Literal[True] = True
