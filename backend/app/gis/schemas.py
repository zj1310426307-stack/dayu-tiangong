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
