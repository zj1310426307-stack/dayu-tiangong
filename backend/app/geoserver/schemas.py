"""Pydantic contracts for GeoServer health, layers, and public endpoints."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class GeoServerLayerRecord(BaseModel):
    """Describe one source-controlled static map layer."""

    model_config = ConfigDict(extra="forbid")

    name: str
    qualified_name: str
    title: str
    geometry_type: Literal["LineString", "Point"]
    style: str
    wms_enabled: Literal[True] = True
    wmts_cached: bool
    srid: Literal[4490] = 4490


class GeoServerHealthResponse(BaseModel):
    """Report real OGC capabilities and the expected Phase 1A catalog size."""

    model_config = ConfigDict(extra="forbid")

    status: Literal["healthy"]
    workspace: Literal["dayu"] = "dayu"
    layers: int = Field(ge=0)
    cached_layers: int = Field(ge=0)
    wms: Literal["online"] = "online"
    wmts: Literal["online"] = "online"
    wfs_mode: Literal["basic-read-only"] = "basic-read-only"
    source: Literal["PostGIS / CGCS2000"] = "PostGIS / CGCS2000"


class GeoServerConfigResponse(BaseModel):
    """Expose public OGC URLs without leaking management endpoints or credentials."""

    model_config = ConfigDict(extra="forbid")

    workspace: Literal["dayu"] = "dayu"
    wms_url: str
    wmts_url: str
    wfs_url: str
    preferred_wmts_matrix_set: Literal["EPSG:900913"] = "EPSG:900913"
    interaction_source: Literal["FastAPI /api/v1/gis/*"] = "FastAPI /api/v1/gis/*"
