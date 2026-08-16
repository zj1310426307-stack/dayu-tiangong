"""Strict public DTOs for gis-catalog/v1alpha1."""

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


ServiceMode = Literal["QGIS_WMS", "GEOSERVER_WMS_LEGACY", "MARTIN_MVT", "TITILER", "FASTAPI", "CESIUM_DYNAMIC", "THREE_D_TILES"]
RenderMode = Literal["RASTER_WMS", "VECTOR_TILE", "RASTER_TILE", "DYNAMIC_PRIMITIVE", "THREE_D"]
CacheMode = Literal["NONE", "CLIENT_PRIVATE", "VERSIONED_PUBLIC"]


class CatalogProject(BaseModel):
    model_config = ConfigDict(extra="forbid")
    project_key: str
    title: str
    crs: str
    project_revision: str
    qgis_project_hash: str | None
    qgis_version: str | None
    extent: tuple[float, float, float, float] | None


class CatalogDataset(BaseModel):
    model_config = ConfigDict(extra="forbid")
    dataset_version_id: int
    version: str
    name: str
    status: Literal["published"]
    content_hash: str
    published_at: datetime
    change_summary: str | None


class CatalogCapabilities(BaseModel):
    model_config = ConfigDict(extra="forbid")
    identify: bool
    legend: bool
    print: bool
    measure: bool
    version_switch: bool
    external_basemap_registration: bool
    editing: bool


class CatalogService(BaseModel):
    model_config = ConfigDict(extra="forbid")
    service_key: str
    service_mode: ServiceMode
    endpoint: str
    healthy: bool
    revision: str | None = None
    wms_version: str | None = None
    wmts_endpoint: str | None = None
    gateway_contract_version: str | None = None
    tile_template: str | None = None
    endpoint_key: str | None = None
    min_zoom: int | None = None
    max_zoom: int | None = None


class CatalogGroup(BaseModel):
    model_config = ConfigDict(extra="forbid")
    group_key: str
    title: str
    order: int
    collapsed: bool = False


class CatalogLayer(BaseModel):
    model_config = ConfigDict(extra="forbid")
    key: str
    title: str
    display_title: str
    group_key: str
    group_title: str
    order: int
    z_index: int
    geometry_type: str
    service_key: str
    service_mode: ServiceMode
    render_mode: RenderMode
    dataset_version_id: int
    dataset_filter_field: str | None
    default_visible: bool
    default_opacity: float = Field(ge=0, le=1)
    min_scale: float | None
    max_scale: float | None
    identify_enabled: bool
    legend_enabled: bool
    search_enabled: bool
    qgis_short_name: str | None
    model_entity_type: str | None
    service: dict[str, Any]
    legend: dict[str, Any] | None
    identify: dict[str, Any]
    cache_mode: CacheMode
    capabilities: dict[str, bool]


class CatalogBasemap(BaseModel):
    model_config = ConfigDict(extra="forbid")
    basemap_key: str
    title: str
    type: Literal["XYZ", "WMS", "WMTS", "COG", "MVT", "ARCGIS_REST"]
    endpoint: str
    credit: str
    crs: str
    visible: bool
    opacity: float = Field(ge=0, le=1)


class GISCatalogResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_version: Literal["gis-catalog/v1alpha1"] = "gis-catalog/v1alpha1"
    catalog_revision: str
    generated_at: datetime
    project: CatalogProject
    dataset: CatalogDataset
    capabilities: CatalogCapabilities
    services: list[CatalogService]
    groups: list[CatalogGroup]
    layers: list[CatalogLayer]
    basemaps: list[CatalogBasemap]
