"""Fail-closed contracts shared by the QGIS Server project builder."""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any


IDENTIFIER = re.compile(r"^[a-z][a-z0-9_]{1,62}$")
ALLOWED_GROUPS = (
    "01_HYDROGRAPHY",
    "02_HYDRAULIC_MODEL",
    "03_ENGINEERING",
)


class BuildContractError(ValueError):
    """Raised when source project or registry input violates the deployment contract."""


@dataclass(frozen=True)
class BootstrapLayer:
    """Validated immutable bootstrap layer used to construct the server project."""

    layer_key: str
    title: str
    display_title: str
    group_key: str
    order: int
    source_schema: str
    source_relation: str
    geometry_type: str
    native_crs: str
    qgis_short_name: str
    service_mode: str
    render_mode: str
    dataset_filter_field: str
    feature_info_fields: tuple[str, ...]
    active: bool


def _identifier(value: Any, field: str) -> str:
    """Validate an identifier before it can influence a datasource or public layer name."""

    if not isinstance(value, str) or not IDENTIFIER.fullmatch(value):
        raise BuildContractError(f"{field} must be a safe PostgreSQL-style identifier")
    return value


def parse_bootstrap_layer(raw: dict[str, Any]) -> BootstrapLayer:
    """Parse one snapshot row and enforce the frozen A1 service/security subset."""

    layer_key = _identifier(raw.get("layer_key"), "layer_key")
    qgis_short_name = _identifier(raw.get("qgis_short_name"), "qgis_short_name")
    source_relation = _identifier(raw.get("source_relation"), "source_relation")
    source_schema = raw.get("source_schema")
    if source_schema != "publish":
        raise BuildContractError("A1 QGIS_WMS layers must use the publish schema")
    if raw.get("service_mode") != "QGIS_WMS" or raw.get("render_mode") != "RASTER_WMS":
        raise BuildContractError("A1 only accepts QGIS_WMS + RASTER_WMS")
    if raw.get("dataset_filter_field") != "dataset_version_id":
        raise BuildContractError("A1 versioned layers must filter by dataset_version_id")
    if raw.get("group_key") not in ALLOWED_GROUPS:
        raise BuildContractError("group_key is outside the A1 server project allowlist")
    if raw.get("native_crs") != "EPSG:4490":
        raise BuildContractError("A1 native CRS must be EPSG:4490")
    fields = raw.get("feature_info_fields")
    if not isinstance(fields, list) or not fields:
        raise BuildContractError("feature_info_fields must be a non-empty list")
    safe_fields = tuple(_identifier(value, "feature_info_field") for value in fields)
    geometry_type = raw.get("geometry_type")
    if geometry_type not in {"Point", "LineString", "Polygon"}:
        raise BuildContractError("geometry_type is not allowed")
    order = raw.get("order")
    if not isinstance(order, int) or order < 0:
        raise BuildContractError("order must be a non-negative integer")
    return BootstrapLayer(
        layer_key=layer_key,
        title=str(raw.get("title") or layer_key),
        display_title=str(raw.get("display_title") or raw.get("title") or layer_key),
        group_key=str(raw["group_key"]),
        order=order,
        source_schema=source_schema,
        source_relation=source_relation,
        geometry_type=geometry_type,
        native_crs="EPSG:4490",
        qgis_short_name=qgis_short_name,
        service_mode="QGIS_WMS",
        render_mode="RASTER_WMS",
        dataset_filter_field="dataset_version_id",
        feature_info_fields=safe_fields,
        active=raw.get("active") is True,
    )


def validate_snapshot(raw: dict[str, Any]) -> tuple[BootstrapLayer, ...]:
    """Validate snapshot metadata and return active layers in deterministic order."""

    if raw.get("schema_version") not in {
        "dayu-bootstrap-registry/v1",
        "dayu-registry-snapshot/v1",
    }:
        raise BuildContractError("unsupported bootstrap registry schema_version")
    if raw.get("project_key") != "dayu_tiangong":
        raise BuildContractError("unexpected project_key")
    notice = str(raw.get("notice", ""))
    if raw.get("schema_version") == "dayu-bootstrap-registry/v1" and "TEMPORARY BOOTSTRAP SNAPSHOT" not in notice:
        raise BuildContractError("bootstrap snapshot must retain its temporary notice")
    if raw.get("schema_version") == "dayu-registry-snapshot/v1" and "IMMUTABLE REGISTRY EXPORT" not in notice:
        raise BuildContractError("registry export must retain its immutable notice")
    rows = raw.get("layers")
    if not isinstance(rows, list):
        raise BuildContractError("layers must be a list")
    layers = tuple(parse_bootstrap_layer(row) for row in rows if row.get("active") is True)
    keys = [layer.layer_key for layer in layers]
    short_names = [layer.qgis_short_name for layer in layers]
    if len(keys) != len(set(keys)):
        raise BuildContractError("layer_key must be unique")
    if len(short_names) != len(set(short_names)):
        raise BuildContractError("qgis_short_name must be unique")
    return tuple(sorted(layers, key=lambda layer: (layer.order, layer.layer_key)))
