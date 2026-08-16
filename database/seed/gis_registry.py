"""Idempotently seed the authoritative GIS layer and basemap allow-lists."""

from __future__ import annotations

import os
import sys
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPOSITORY_ROOT / "backend"))

from app.database.session import SessionLocal
from app.gis.models import BasemapRegistry, GISLayerRegistry


STATIC_LAYERS = (
    ("river", "河道", "01_HYDROGRAPHY", "LINESTRING", "QGIS_WMS", "river", "river_detail", 10),
    ("cross_section", "横断面", "02_HYDRAULIC_MODEL", "POINT", "QGIS_WMS", "cross_section", "cross_section_detail", 20),
    ("gate", "闸门", "03_ENGINEERING", "POINT", "QGIS_WMS", "gate", "gate_detail", 30),
    ("pump", "泵站", "03_ENGINEERING", "POINT", "QGIS_WMS", "pump", "pump_detail", 40),
    ("river_segment", "河段", "01_HYDROGRAPHY", "LINESTRING", "GEOSERVER_WMS_LEGACY", None, "river_segment_detail", 50),
    ("river_node", "河网节点", "01_HYDROGRAPHY", "POINT", "GEOSERVER_WMS_LEGACY", None, "river_node_detail", 60),
    ("map_annotation", "地图注记", "90_REFERENCE", "POINT", "GEOSERVER_WMS_LEGACY", None, "annotation_detail", 70),
    ("administrative_area", "行政区", "90_REFERENCE", "POLYGON", "GEOSERVER_WMS_LEGACY", None, None, 80),
    ("road", "道路", "90_REFERENCE", "LINESTRING", "GEOSERVER_WMS_LEGACY", None, None, 90),
    ("place_name", "地名", "90_REFERENCE", "POINT", "GEOSERVER_WMS_LEGACY", None, None, 100),
    ("water_name", "水系名称", "90_REFERENCE", "POINT", "GEOSERVER_WMS_LEGACY", None, None, 110),
    ("poi", "兴趣点", "90_REFERENCE", "POINT", "GEOSERVER_WMS_LEGACY", None, None, 120),
)

DYNAMIC_LAYERS = (
    ("water_result", "水位结果", "05_SIMULATION", "cross_section", "cross_section", 200),
    ("velocity_result", "流速结果", "05_SIMULATION", "cross_section", "cross_section", 210),
    ("risk_result", "风险结果", "05_SIMULATION", "administrative_area", None, 220),
    ("gate_status", "闸门状态", "05_SIMULATION", "gate", "gate", 230),
    ("pump_status", "泵站状态", "05_SIMULATION", "pump", "pump", 240),
)

MARTIN_LAYERS = (
    ("river_mvt", "河道矢量瓦片", "01_HYDROGRAPHY", "river", "LINESTRING", 300),
    ("road_mvt", "道路矢量瓦片", "90_REFERENCE", "road", "LINESTRING", 310),
    ("administrative_area_mvt", "行政区矢量瓦片", "90_REFERENCE", "administrative_area", "POLYGON", 320),
    ("place_name_mvt", "地名矢量瓦片", "90_REFERENCE", "place_name", "POINT", 330),
    ("engineering_facility_mvt", "工程设施矢量瓦片", "03_ENGINEERING", "engineering_facility", "POINT", 340),
)


def _upsert_layer(session: Session, values: dict[str, object]) -> None:
    statement = insert(GISLayerRegistry).values(**values)
    update_values = {
        key: getattr(statement.excluded, key)
        for key in values
        if key not in {"layer_key", "created_by"}
    }
    session.execute(
        statement.on_conflict_do_update(
            constraint="uq_gis_layer_registry_layer_key",
            set_=update_values,
        )
    )


def seed_gis_registry(session: Session) -> dict[str, int]:
    """Seed all current logical layers and deployment-owned basemap endpoints."""

    common = {
        "native_crs": "EPSG:4490",
        "dataset_filter_field": "dataset_version_id",
        "cache_mode": "CLIENT_PRIVATE",
        "active": True,
        "revision": 1,
        "created_by": "gis-opt2-seed",
        "updated_by": "gis-opt2-seed",
    }
    for key, title, group, geometry, mode, short_name, detail, order in STATIC_LAYERS:
        _upsert_layer(
            session,
            {
                **common,
                "layer_key": key,
                "title": title,
                "group_key": group,
                "source_schema": "publish",
                "source_relation": key,
                "geometry_type": geometry,
                "qgis_short_name": short_name,
                "service_mode": mode,
                "render_mode": "RASTER_WMS",
                "identify_enabled": True,
                "legend_enabled": True,
                "search_enabled": key in {"river", "gate", "pump", "place_name", "poi"},
                "capabilities": {"render": True, "identify": True, "legend": True, "print": False},
                "feature_info_fields": ["id", "dataset_version_id"],
                "identify_mode": "FEATURE_INFO",
                "detail_route_key": detail,
                "model_entity_type": key if key in {"river", "cross_section", "gate", "pump"} else None,
                "display_order": order,
                "default_visible": key in {"river", "gate", "pump"},
                "default_opacity": 1.0,
            },
        )
    for key, title, group, relation, entity_type, order in DYNAMIC_LAYERS:
        _upsert_layer(
            session,
            {
                **common,
                "layer_key": key,
                "title": title,
                "group_key": group,
                "source_schema": "publish",
                "source_relation": relation,
                "geometry_type": "POINT",
                "qgis_short_name": None,
                "service_mode": "CESIUM_DYNAMIC",
                "render_mode": "DYNAMIC_PRIMITIVE",
                "identify_enabled": True,
                "legend_enabled": True,
                "search_enabled": False,
                "capabilities": {"render": True, "identify": True, "legend": True, "print": False},
                "feature_info_fields": ["id", "dataset_version_id"],
                "identify_mode": "CLIENT_PICK",
                "detail_route_key": f"{entity_type}_detail" if entity_type else None,
                "model_entity_type": entity_type,
                "display_order": order,
                "default_visible": True,
                "default_opacity": 0.9,
            },
        )
    for key, title, group, relation, geometry, order in MARTIN_LAYERS:
        _upsert_layer(
            session,
            {
                **common,
                "layer_key": key,
                "title": title,
                "group_key": group,
                "source_schema": "tiles",
                "source_relation": relation,
                "geometry_type": geometry,
                "qgis_short_name": None,
                "service_mode": "MARTIN_MVT",
                "render_mode": "VECTOR_TILE",
                "identify_enabled": False,
                "legend_enabled": False,
                "search_enabled": False,
                "capabilities": {"render": True, "identify": False, "legend": False, "print": False},
                "feature_info_fields": ["id", "dataset_version_id"],
                "identify_mode": "CLIENT_PICK",
                "detail_route_key": None,
                "model_entity_type": None,
                "display_order": order,
                "default_visible": False,
                "default_opacity": 1.0,
                "cache_mode": "VERSIONED_PUBLIC",
            },
        )

    basemap_values = {
        "basemap_key": "world_imagery",
        "title": "影像底图",
        "basemap_type": "ARCGIS_REST",
        "endpoint_key": "world_imagery_proxy",
        "native_crs": "EPSG:3857",
        "credit": "Esri World Imagery（经平台受控代理）",
        "display_order": 10,
        "default_visible": True,
        "default_opacity": 1.0,
        "active": True,
        "revision": 1,
        "created_by": "gis-opt2-seed",
        "updated_by": "gis-opt2-seed",
    }
    statement = insert(BasemapRegistry).values(**basemap_values)
    session.execute(
        statement.on_conflict_do_update(
            constraint="uq_basemap_registry_key",
            set_={
                key: getattr(statement.excluded, key)
                for key in basemap_values
                if key not in {"basemap_key", "created_by"}
            },
        )
    )
    session.commit()
    return {"layers": len(STATIC_LAYERS) + len(DYNAMIC_LAYERS) + len(MARTIN_LAYERS), "basemaps": 1}


def validate_gis_registry(
    session: Session, *, qgis_server_role: str = "dayu_qgis_server"
) -> dict[str, int]:
    """Fail closed when an active registry source or renderer grant is missing.

    Registry rows are an executable allow-list, not aspirational metadata. A
    publish source must resolve to a relation, a Martin source must resolve to
    its tile function, and every QGIS WMS relation must be readable by the
    dedicated headless-renderer role.
    """

    rows = list(
        session.query(GISLayerRegistry)
        .filter(GISLayerRegistry.active.is_(True))
        .order_by(GISLayerRegistry.layer_key)
    )
    failures: list[str] = []
    qgis_checked = 0
    for row in rows:
        if row.source_schema == "publish":
            exists = bool(
                session.execute(
                    text("SELECT to_regclass(:qualified_name) IS NOT NULL"),
                    {"qualified_name": f"{row.source_schema}.{row.source_relation}"},
                ).scalar_one()
            )
        else:
            exists = bool(
                session.execute(
                    text(
                        "SELECT EXISTS ("
                        "SELECT 1 FROM pg_catalog.pg_proc p "
                        "JOIN pg_catalog.pg_namespace n ON n.oid = p.pronamespace "
                        "WHERE n.nspname = :schema_name AND p.proname = :relation_name)"
                    ),
                    {
                        "schema_name": row.source_schema,
                        "relation_name": row.source_relation,
                    },
                ).scalar_one()
            )
        if not exists:
            failures.append(
                f"{row.layer_key}: missing {row.source_schema}.{row.source_relation}"
            )
            continue
        if row.service_mode == "QGIS_WMS":
            qgis_checked += 1
            can_read = bool(
                session.execute(
                    text(
                        "SELECT has_table_privilege("
                        ":role_name, :qualified_name, 'SELECT')"
                    ),
                    {
                        "role_name": qgis_server_role,
                        "qualified_name": f"{row.source_schema}.{row.source_relation}",
                    },
                ).scalar_one()
            )
            if not can_read:
                failures.append(
                    f"{row.layer_key}: {qgis_server_role} lacks SELECT on "
                    f"{row.source_schema}.{row.source_relation}"
                )
    if failures:
        raise RuntimeError("GIS_REGISTRY_VALIDATION_FAILED: " + "; ".join(failures))
    return {"sources": len(rows), "qgis_permissions": qgis_checked}


def main() -> None:
    """Run as a Compose one-shot after migration and core demo seeding."""

    with SessionLocal() as session:
        counts = seed_gis_registry(session)
        evidence = validate_gis_registry(
            session,
            qgis_server_role=os.getenv("QGIS_SERVER_DB_USER", "dayu_qgis_server"),
        )
    print(f"GIS Registry ready: {counts}, validated: {evidence}")


if __name__ == "__main__":
    main()
