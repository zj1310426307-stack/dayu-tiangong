"""Public contracts for the GeoServer-only PostGIS GIS Catalog."""

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


ServiceMode = Literal["GEOSERVER_WMS"]
RenderMode = Literal["RASTER_WMS"]
CacheMode = Literal["CLIENT_PRIVATE", "VERSIONED_PUBLIC"]


class CatalogProject(BaseModel):
    """Describe the platform CRS boundary without exposing local project files."""

    model_config = ConfigDict(extra="forbid")
    project_key: str
    title: str
    native_crs: Literal["EPSG:4490"] = "EPSG:4490"
    web_crs: Literal["EPSG:3857"] = "EPSG:3857"


class CatalogDataset(BaseModel):
    """Identify the immutable published dataset rendered by this Catalog."""

    model_config = ConfigDict(extra="forbid")
    dataset_version_id: int
    version: str
    name: str
    status: Literal["published"]
    content_hash: str
    published_at: datetime
    change_summary: str | None


class CatalogCapabilities(BaseModel):
    """Separate current WebGIS abilities from future model and 3D work."""

    model_config = ConfigDict(extra="forbid")
    identify: bool
    legend: bool
    measure: bool
    version_switch: bool
    editing: Literal[False] = False
    three_d: Literal[False] = False


class CatalogService(BaseModel):
    """Expose one same-origin FastAPI gateway backed by private GeoServer."""

    model_config = ConfigDict(extra="forbid")
    service_key: Literal["geoserver_ogc"] = "geoserver_ogc"
    service_mode: ServiceMode = "GEOSERVER_WMS"
    endpoint: Literal["/api/v1/gis/ogc/wms"] = "/api/v1/gis/ogc/wms"
    health_endpoint: Literal["/api/v1/gis/geoserver/health"] = "/api/v1/gis/geoserver/health"
    wms_version: Literal["1.1.1"] = "1.1.1"
    healthy: bool


class CatalogGroup(BaseModel):
    """Group layers without duplicating renderer or style definitions."""

    model_config = ConfigDict(extra="forbid")
    group_key: str
    title: str
    order: int
    collapsed: bool = False


class CatalogLayer(BaseModel):
    """Return one browser-safe GeoServer layer descriptor."""

    model_config = ConfigDict(extra="forbid")
    key: str
    title: str
    group_key: str
    group_title: str
    order: int
    z_index: int
    geometry_type: str
    service_key: Literal["geoserver_ogc"] = "geoserver_ogc"
    service_mode: ServiceMode = "GEOSERVER_WMS"
    render_mode: RenderMode = "RASTER_WMS"
    layer_name: str
    dataset_version_id: int
    default_visible: bool
    default_opacity: float = Field(ge=0, le=1)
    identify_enabled: bool
    legend_enabled: bool
    search_enabled: bool
    detail_route_key: str | None
    model_entity_type: str | None
    cache_mode: CacheMode
    capabilities: dict[str, bool]


class CatalogBasemap(BaseModel):
    """Use a GeoServer-published reference layer as the minimal local basemap."""

    model_config = ConfigDict(extra="forbid")
    basemap_key: Literal["dayu_reference"] = "dayu_reference"
    title: Literal["行政区参考底图"] = "行政区参考底图"
    type: Literal["WMS"] = "WMS"
    endpoint: Literal["/api/v1/gis/ogc/wms"] = "/api/v1/gis/ogc/wms"
    layer_key: Literal["administrative_area"] = "administrative_area"
    layer_name: Literal["dayu:administrative_area"] = "dayu:administrative_area"
    crs: Literal["EPSG:3857"] = "EPSG:3857"
    visible: bool = True
    opacity: float = Field(default=0.45, ge=0, le=1)


class GISCatalogResponse(BaseModel):
    """Return the complete deterministic WebGIS bootstrap document."""

    model_config = ConfigDict(extra="forbid")
    schema_version: Literal["gis-catalog/v1"] = "gis-catalog/v1"
    catalog_revision: str
    generated_at: datetime
    project: CatalogProject
    dataset: CatalogDataset
    capabilities: CatalogCapabilities
    services: list[CatalogService]
    groups: list[CatalogGroup]
    layers: list[CatalogLayer]
    basemaps: list[CatalogBasemap]


class CatalogFeature(BaseModel):
    """Represent one sanitized GeoServer FeatureInfo item."""

    model_config = ConfigDict(extra="forbid")
    id: str
    geometry: dict[str, Any] | None = None
    properties: dict[str, Any]


class GISFeatureInfoResponse(BaseModel):
    """Return bounded attributes for one map click and one dataset version."""

    model_config = ConfigDict(extra="forbid")
    layer_key: str
    dataset_version_id: int
    crs: Literal["EPSG:3857"] = "EPSG:3857"
    features: list[CatalogFeature]
