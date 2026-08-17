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

from app.database.session import SessionLocal
from app.gis.models import GISCatalogLayer


CATALOG_LAYERS = (
    ("river", "河道", "01_HYDROGRAPHY", "LINESTRING", "river_detail", 10, True),
    ("cross_section", "横断面", "02_HYDRAULIC_MODEL", "POINT", "cross_section_detail", 20, True),
    ("gate", "闸门", "03_ENGINEERING", "POINT", "gate_detail", 30, True),
    ("pump", "泵站", "03_ENGINEERING", "POINT", "pump_detail", 40, True),
    ("river_segment", "河段", "01_HYDROGRAPHY", "LINESTRING", "river_segment_detail", 50, False),
    ("river_node", "河网节点", "01_HYDROGRAPHY", "POINT", "river_node_detail", 60, False),
    ("map_annotation", "地图注记", "90_REFERENCE", "POINT", "annotation_detail", 70, False),
    ("administrative_area", "行政区", "90_REFERENCE", "POLYGON", None, 80, False),
    ("road", "道路", "90_REFERENCE", "LINESTRING", None, 90, False),
    ("place_name", "地名", "90_REFERENCE", "POINT", None, 100, False),
    ("water_name", "水系名称", "90_REFERENCE", "POINT", None, 110, False),
    ("poi", "兴趣点", "90_REFERENCE", "POINT", None, 120, False),
)


def seed_gis_catalog(session: Session) -> dict[str, int]:
    """Upsert the twelve GeoServer layers and retire every alternate renderer."""

    active_keys: list[str] = []
    for key, title, group, geometry, detail, order, visible in CATALOG_LAYERS:
        active_keys.append(key)
        values = {
            "layer_key": key,
            "title": title,
            "group_key": group,
            "source_schema": "publish",
            "source_relation": key,
            "geometry_type": geometry,
            "native_crs": "EPSG:4490",
            "qgis_short_name": None,
            "service_mode": "GEOSERVER_WMS",
            "render_mode": "RASTER_WMS",
            "dataset_filter_field": "dataset_version_id",
            "identify_enabled": True,
            "legend_enabled": True,
            "search_enabled": key in {"river", "gate", "pump", "place_name", "poi"},
            "capabilities": {"render": True, "identify": True, "legend": True, "print": False},
            "feature_info_fields": ["id", "dataset_version_id"],
            "cache_mode": "CLIENT_PRIVATE",
            "identify_mode": "FEATURE_INFO",
            "detail_route_key": detail,
            "model_entity_type": key if key in {"river", "cross_section", "gate", "pump"} else None,
            "display_order": order,
            "default_visible": visible,
            "default_opacity": 1.0,
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
    session.commit()
    return {"layers": len(active_keys)}


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
