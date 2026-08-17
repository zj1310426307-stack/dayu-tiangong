"""Collapse the active GIS catalog to GeoServer-published PostGIS views.

Revision ID: 20260817_0015
Revises: 20260815_0014
"""

from collections.abc import Sequence

from alembic import op


revision: str = "20260817_0015"
down_revision: str | None = "20260815_0014"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


CORE_LAYERS = (
    "river",
    "river_segment",
    "river_node",
    "cross_section",
    "gate",
    "pump",
    "map_annotation",
    "administrative_area",
    "road",
    "place_name",
    "water_name",
    "poi",
)
QGIS_LAYERS = ("river", "cross_section", "gate", "pump")
LEGACY_STATIC_LAYERS = tuple(layer for layer in CORE_LAYERS if layer not in QGIS_LAYERS)
DYNAMIC_LAYERS = ("water_result", "velocity_result", "risk_result", "gate_status", "pump_status")
MARTIN_LAYERS = (
    "river_mvt",
    "road_mvt",
    "administrative_area_mvt",
    "place_name_mvt",
    "engineering_facility_mvt",
)


def _quoted(values: tuple[str, ...]) -> str:
    """Render migration-owned constant strings as one SQL IN list."""

    return ",".join(f"'{value}'" for value in values)


def upgrade() -> None:
    """Activate only GeoServer WMS layers while retaining inactive rollback rows."""

    for constraint in (
        "ck_gis_layer_registry_source_schema",
        "ck_gis_layer_registry_service_mode",
        "ck_gis_layer_registry_render_mode",
        "ck_gis_layer_registry_service_render",
        "ck_gis_layer_registry_qgis_contract",
    ):
        op.drop_constraint(constraint, "gis_layer_registry", type_="check")

    op.execute("UPDATE gis_layer_registry SET active = FALSE")
    op.execute(
        "UPDATE gis_layer_registry SET active = TRUE, source_schema = 'publish', "
        "service_mode = 'GEOSERVER_WMS', render_mode = 'RASTER_WMS', "
        "dataset_filter_field = 'dataset_version_id', qgis_short_name = NULL, "
        "updated_by = 'gis-reset-01', revision = revision + 1 "
        f"WHERE layer_key IN ({_quoted(CORE_LAYERS)})"
    )

    op.create_check_constraint(
        "ck_gis_catalog_active_source",
        "gis_layer_registry",
        "active IS NOT TRUE OR source_schema = 'publish'",
    )
    op.create_check_constraint(
        "ck_gis_catalog_active_service",
        "gis_layer_registry",
        "active IS NOT TRUE OR service_mode = 'GEOSERVER_WMS'",
    )
    op.create_check_constraint(
        "ck_gis_catalog_active_render",
        "gis_layer_registry",
        "active IS NOT TRUE OR render_mode = 'RASTER_WMS'",
    )
    op.create_check_constraint(
        "ck_gis_catalog_active_version_filter",
        "gis_layer_registry",
        "active IS NOT TRUE OR dataset_filter_field = 'dataset_version_id'",
    )


def downgrade() -> None:
    """Restore the GIS-OPT-2 renderer matrix without dropping catalog rows."""

    for constraint in (
        "ck_gis_catalog_active_source",
        "ck_gis_catalog_active_service",
        "ck_gis_catalog_active_render",
        "ck_gis_catalog_active_version_filter",
    ):
        op.drop_constraint(constraint, "gis_layer_registry", type_="check")

    op.execute("UPDATE gis_layer_registry SET active = TRUE")
    op.execute(
        "UPDATE gis_layer_registry SET service_mode = 'QGIS_WMS', "
        "render_mode = 'RASTER_WMS', qgis_short_name = layer_key "
        f"WHERE layer_key IN ({_quoted(QGIS_LAYERS)})"
    )
    op.execute(
        "UPDATE gis_layer_registry SET service_mode = 'GEOSERVER_WMS_LEGACY', "
        "render_mode = 'RASTER_WMS', qgis_short_name = NULL "
        f"WHERE layer_key IN ({_quoted(LEGACY_STATIC_LAYERS)})"
    )
    op.execute(
        "UPDATE gis_layer_registry SET service_mode = 'CESIUM_DYNAMIC', "
        "render_mode = 'DYNAMIC_PRIMITIVE', qgis_short_name = NULL "
        f"WHERE layer_key IN ({_quoted(DYNAMIC_LAYERS)})"
    )
    op.execute(
        "UPDATE gis_layer_registry SET service_mode = 'MARTIN_MVT', "
        "render_mode = 'VECTOR_TILE', qgis_short_name = NULL "
        f"WHERE layer_key IN ({_quoted(MARTIN_LAYERS)})"
    )

    op.create_check_constraint(
        "ck_gis_layer_registry_source_schema",
        "gis_layer_registry",
        "source_schema IN ('publish','tiles')",
    )
    op.create_check_constraint(
        "ck_gis_layer_registry_service_mode",
        "gis_layer_registry",
        "service_mode IN ('QGIS_WMS','GEOSERVER_WMS_LEGACY','MARTIN_MVT','TITILER','FASTAPI','CESIUM_DYNAMIC','THREE_D_TILES')",
    )
    op.create_check_constraint(
        "ck_gis_layer_registry_render_mode",
        "gis_layer_registry",
        "render_mode IN ('RASTER_WMS','VECTOR_TILE','RASTER_TILE','DYNAMIC_PRIMITIVE','THREE_D')",
    )
    op.create_check_constraint(
        "ck_gis_layer_registry_service_render",
        "gis_layer_registry",
        "(service_mode = 'QGIS_WMS' AND render_mode = 'RASTER_WMS') OR "
        "(service_mode = 'GEOSERVER_WMS_LEGACY' AND render_mode IN ('RASTER_WMS','RASTER_TILE')) OR "
        "(service_mode = 'MARTIN_MVT' AND render_mode = 'VECTOR_TILE') OR "
        "(service_mode = 'TITILER' AND render_mode = 'RASTER_TILE') OR "
        "(service_mode IN ('FASTAPI','CESIUM_DYNAMIC') AND render_mode = 'DYNAMIC_PRIMITIVE') OR "
        "(service_mode = 'THREE_D_TILES' AND render_mode = 'THREE_D')",
    )
    op.create_check_constraint(
        "ck_gis_layer_registry_qgis_contract",
        "gis_layer_registry",
        "service_mode <> 'QGIS_WMS' OR (qgis_short_name IS NOT NULL AND dataset_filter_field = 'dataset_version_id' AND source_schema = 'publish')",
    )
