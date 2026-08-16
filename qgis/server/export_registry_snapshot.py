"""Export the authoritative QGIS_WMS subset as an immutable builder input."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

import psycopg


GROUP_MAP = {
    "01_HYDROGRAPHY": "01_HYDROGRAPHY",
    "02_HYDRAULIC_MODEL": "02_HYDRAULIC_MODEL",
    "03_ENGINEERING": "03_ENGINEERING",
}
GEOMETRY_MAP = {
    "POINT": "Point",
    "LINESTRING": "LineString",
    "POLYGON": "Polygon",
}


def export(output: Path) -> dict[str, object]:
    """Read only allow-listed fields; never serialize a DSN, URL, or credential."""

    with psycopg.connect(
        host=os.getenv("POSTGRES_HOST", "database"),
        port=int(os.getenv("POSTGRES_PORT", "5432")),
        dbname=os.getenv("POSTGRES_DB", "dayu_tiangong"),
        user=os.getenv("POSTGRES_USER", "dayu"),
        password=os.environ["POSTGRES_PASSWORD"],
    ) as connection, connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT layer_key, title, group_key, display_order, source_schema,
                   source_relation, geometry_type, native_crs, qgis_short_name,
                   service_mode, render_mode, dataset_filter_field,
                   feature_info_fields, active
              FROM public.gis_layer_registry
             WHERE active IS TRUE AND service_mode = 'QGIS_WMS'
             ORDER BY display_order, layer_key
            """
        )
        layers = []
        for row in cursor.fetchall():
            group = GROUP_MAP.get(row[2])
            geometry = GEOMETRY_MAP.get(row[6])
            if group is None or geometry is None:
                raise ValueError(f"Registry layer {row[0]} is outside the server-project subset")
            layers.append(
                {
                    "layer_key": row[0], "title": row[1], "display_title": row[1],
                    "group_key": group, "order": row[3], "source_schema": row[4],
                    "source_relation": row[5], "geometry_type": geometry,
                    "native_crs": row[7], "qgis_short_name": row[8],
                    "service_mode": row[9], "render_mode": row[10],
                    "dataset_filter_field": row[11],
                    "feature_info_fields": list(row[12]), "active": row[13],
                }
            )
    payload: dict[str, object] = {
        "schema_version": "dayu-registry-snapshot/v1",
        "notice": "IMMUTABLE REGISTRY EXPORT. Generated from authoritative gis_layer_registry.",
        "project_key": "dayu_tiangong",
        "layers": layers,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n", encoding="utf-8")
    return payload


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    payload = export(args.output.resolve())
    print(json.dumps({"layers": len(payload["layers"]), "output": args.output.name}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
