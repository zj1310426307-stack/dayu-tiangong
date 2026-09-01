"""Seed and validate the PostGIS-owned GeoServer layer catalog."""

from __future__ import annotations

import os
import sys
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPOSITORY_ROOT / "backend"))

from app.database.session import SessionLocal  # noqa: E402
from app.gis.models import BasemapRegistry, GISCatalogLayer  # noqa: E402


CATALOG_LAYERS = (
    ("river", "河道", "01_HYDROGRAPHY", "LINESTRING", "river", True, "river_detail", 10, True, 1.0),
    ("cross_section", "横断面", "02_HYDRAULIC_MODEL", "POINT", "cross_section", True, "cross_section_detail", 20, True, 1.0),
    ("gate", "闸门", "03_ENGINEERING", "POINT", "gate", True, "gate_detail", 30, True, 1.0),
    ("pump", "泵站", "03_ENGINEERING", "POINT", "pump", True, "pump_detail", 40, True, 1.0),
    ("river_segment", "河段", "01_HYDROGRAPHY", "LINESTRING", "river_segment", True, "river_segment_detail", 50, False, 1.0),
    ("river_node", "河网节点", "01_HYDROGRAPHY", "POINT", "river_node", True, "river_node_detail", 60, False, 1.0),
    ("administrative_area", "广东行政区（开放数据）", "90_REFERENCE", "MULTIPOLYGON", "administrative_area_open", False, None, 70, True, 0.28),
    ("road", "广东主要道路（OpenStreetMap）", "90_REFERENCE", "MULTILINESTRING", "road_open", False, None, 80, True, 0.80),
    ("waterway", "广东主要水系（OpenStreetMap）", "90_REFERENCE", "MULTILINESTRING", "waterway_open", False, None, 90, True, 0.90),
)

BASEMAPS = (
    ("nasa_blue_marble", "NASA Blue Marble 真彩色影像", "nasa_gibs_blue_marble", "NASA Earth Observatory / GIBS", 0, False),
    ("nasa_viirs_true_color", "NASA VIIRS 真彩色影像 2026-08-16", "nasa_gibs_viirs_20260816", "NASA EOSDIS GIBS / VIIRS NOAA-21", 1, False),
    (
        "esri_world_imagery",
        "Esri World Imagery 高分辨率影像",
        "esri_world_imagery",
        "Source: Esri, Vantor, Earthstar Geographics, and the GIS User Community",
        2,
        True,
    ),
)


def seed_gis_catalog(session: Session) -> dict[str, int]:
    """Upsert truthful Guangdong layers and allow-listed online basemaps."""

    active_keys: list[str] = []
    for key, title, group, geometry, relation, version_scoped, detail, order, visible, opacity in CATALOG_LAYERS:
        active_keys.append(key)
        values = {
            "layer_key": key,
            "title": title,
            "group_key": group,
            "source_schema": "publish",
            "source_relation": relation,
            "geometry_type": geometry,
            "native_crs": "EPSG:4490",
            "qgis_short_name": None,
            "service_mode": "GEOSERVER_WMS",
            "render_mode": "RASTER_WMS",
            "dataset_filter_field": "dataset_version_id" if version_scoped else None,
            "identify_enabled": True,
            "legend_enabled": True,
            "search_enabled": key in {"river", "gate", "pump"},
            "capabilities": {"render": True, "identify": True, "legend": True, "print": False},
            "feature_info_fields": (
                ["id", "dataset_version_id"]
                if version_scoped
                else [
                    "id",
                    "source",
                    "source_id",
                    "name_zh",
                    {
                        "administrative_area": "administrative_level",
                        "road": "road_type",
                        "waterway": "waterway_type",
                    }[key],
                ]
            ),
            "cache_mode": "CLIENT_PRIVATE",
            "identify_mode": "FEATURE_INFO",
            "detail_route_key": detail,
            "model_entity_type": key if key in {"river", "cross_section", "gate", "pump"} else None,
            "display_order": order,
            "default_visible": visible,
            "default_opacity": opacity,
            "active": True,
            "revision": 2,
            "created_by": "gis-reset-01",
            "updated_by": "gis-reset-01",
        }
        statement = insert(GISCatalogLayer).values(**values)
        session.execute(
            statement.on_conflict_do_update(
                constraint="uq_gis_layer_registry_layer_key",
                set_={
                    field: getattr(statement.excluded, field)
                    for field in values
                    if field not in {"layer_key", "created_by"}
                },
            )
        )
    session.query(GISCatalogLayer).filter(
        GISCatalogLayer.layer_key.not_in(active_keys)
    ).update({"active": False, "updated_by": "gis-reset-01"}, synchronize_session=False)
    active_basemaps: list[str] = []
    for key, title, endpoint_key, credit, order, visible in BASEMAPS:
        active_basemaps.append(key)
        values = {
            "basemap_key": key,
            "title": title,
            "basemap_type": "XYZ",
            "endpoint_key": endpoint_key,
            "native_crs": "EPSG:3857",
            "credit": credit,
            "display_order": order,
            "default_visible": visible,
            "default_opacity": 1.0,
            "active": True,
            "revision": 2,
            "created_by": "gis-open-data-guangdong",
            "updated_by": "gis-open-data-guangdong",
        }
        statement = insert(BasemapRegistry).values(**values)
        session.execute(
            statement.on_conflict_do_update(
                constraint="uq_basemap_registry_key",
                set_={
                    field: getattr(statement.excluded, field)
                    for field in values
                    if field not in {"basemap_key", "created_by"}
                },
            )
        )
    session.query(BasemapRegistry).filter(
        BasemapRegistry.basemap_key.not_in(active_basemaps)
    ).update(
        {"active": False, "updated_by": "gis-open-data-guangdong"},
        synchronize_session=False,
    )
    session.commit()
    return {"layers": len(active_keys), "basemaps": len(active_basemaps)}


def validate_gis_catalog(
    session: Session, *, geoserver_role: str = "dayu_geoserver"
) -> dict[str, int]:
    """Prove each active source exists and the read-only GeoServer role can read it."""

    rows = list(
        session.query(GISCatalogLayer)
        .filter(GISCatalogLayer.active.is_(True))
        .order_by(GISCatalogLayer.layer_key)
    )
    failures: list[str] = []
    permissions = 0
    for row in rows:
        qualified_name = f"{row.source_schema}.{row.source_relation}"
        exists = bool(
            session.execute(
                text("SELECT to_regclass(:qualified_name) IS NOT NULL"),
                {"qualified_name": qualified_name},
            ).scalar_one()
        )
        if not exists:
            failures.append(f"{row.layer_key}: missing {qualified_name}")
            continue
        can_read = bool(
            session.execute(
                text("SELECT has_table_privilege(:role_name, :qualified_name, 'SELECT')"),
                {"role_name": geoserver_role, "qualified_name": qualified_name},
            ).scalar_one()
        )
        if can_read:
            permissions += 1
        else:
            failures.append(f"{row.layer_key}: {geoserver_role} lacks SELECT on {qualified_name}")
    if failures:
        raise RuntimeError("GIS_CATALOG_VALIDATION_FAILED: " + "; ".join(failures))
    return {"sources": len(rows), "geoserver_permissions": permissions}


def main() -> None:
    """Run the idempotent Catalog seed after GeoServer role provisioning."""

    with SessionLocal() as session:
        counts = seed_gis_catalog(session)
        evidence = validate_gis_catalog(
            session,
            geoserver_role=os.getenv("GEOSERVER_DB_USER", "dayu_geoserver"),
        )
    print(f"GIS Catalog ready: {counts}, validated: {evidence}")


if __name__ == "__main__":
    main()
