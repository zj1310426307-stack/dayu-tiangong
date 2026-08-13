"""在真实 PostGIS 上验证 Phase 1 数据、空间契约和索引。"""

import os

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.database.session import SessionLocal
from app.main import app


pytestmark = pytest.mark.skipif(
    os.getenv("RUN_POSTGIS_TESTS") != "1",
    reason="需要先启动并初始化 Phase 1 PostGIS，再设置 RUN_POSTGIS_TESTS=1",
)
client = TestClient(app)


def test_postgis_health_and_seed_statistics() -> None:
    """健康端点必须执行真实 PostGIS SQL，统计必须匹配演示种子。"""

    health = client.get("/api/v1/gis/health")
    assert health.status_code == 200
    assert health.json()["status"] == "healthy"
    assert health.json()["database"] == "dayu_tiangong"
    assert "POSTGIS=" in health.json()["postgis_version"]
    assert health.json()["srid"] == 4490

    statistics = client.get("/api/v1/gis/stats", params={"dataset_version_id": 1})
    assert statistics.status_code == 200
    assert statistics.json() == {
        "dataset_version_id": 1,
        "rivers": 3,
        "gates": 5,
        "pumps": 3,
        "cross_sections": 20,
        "demo_data": True,
        "source": "PostGIS / DEMO DATA",
    }


@pytest.mark.parametrize(
    ("resource", "expected_total", "geometry_type"),
    [
        ("rivers", 3, "LineString"),
        ("gates", 5, "Point"),
        ("pumps", 3, "Point"),
        ("cross_sections", 20, "Point"),
    ],
)
def test_geojson_collections(resource: str, expected_total: int, geometry_type: str) -> None:
    """四类列表都必须返回标准 GeoJSON、稳定属性与分页元数据。"""

    response = client.get(
        f"/api/v1/gis/{resource}",
        params={"dataset_version_id": 1, "limit": 100, "offset": 0},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["type"] == "FeatureCollection"
    assert payload["meta"] == {
        "total": expected_total,
        "limit": 100,
        "offset": 0,
        "dataset_version_id": 1,
        "bbox": None,
        "demo_data": True,
        "crs": "EPSG:4490",
    }
    assert len(payload["features"]) == expected_total
    assert payload["features"][0]["type"] == "Feature"
    assert payload["features"][0]["geometry"]["type"] == geometry_type
    assert payload["features"][0]["properties"]["demo_data"] is True
    assert payload["features"][0]["properties"]["feature_type"]


def test_bbox_pagination_details_and_validation() -> None:
    """有界查询、分页、详情、404 与 bbox 校验均应可观察。"""

    outside = client.get(
        "/api/v1/gis/rivers",
        params={"dataset_version_id": 1, "bbox": "0,0,1,1"},
    ).json()
    assert outside["meta"]["total"] == 0
    assert outside["features"] == []

    first = client.get(
        "/api/v1/gis/cross_sections",
        params={"dataset_version_id": 1, "limit": 1, "offset": 0},
    ).json()
    second = client.get(
        "/api/v1/gis/cross_sections",
        params={"dataset_version_id": 1, "limit": 1, "offset": 1},
    ).json()
    assert first["meta"]["total"] == 20
    assert first["features"][0]["id"] != second["features"][0]["id"]

    river = client.get("/api/v1/gis/rivers/1", params={"dataset_version_id": 1})
    assert river.status_code == 200
    assert river.json()["properties"]["cross_section_count"] > 0
    assert client.get(
        "/api/v1/gis/gates/9999", params={"dataset_version_id": 1}
    ).status_code == 404
    assert client.get(
        "/api/v1/gis/rivers", params={"dataset_version_id": 1, "bbox": "bad"}
    ).status_code == 422
    assert client.get(
        "/api/v1/gis/rivers",
        params={"dataset_version_id": 1, "bbox": "2,2,1,1"},
    ).status_code == 422


@pytest.mark.parametrize(
    "path",
    [
        "/api/v1/gis/stats",
        "/api/v1/gis/rivers",
        "/api/v1/gis/gates",
        "/api/v1/gis/pumps",
        "/api/v1/gis/cross_sections",
        "/api/v1/gis/interaction-frame",
    ],
)
def test_gis_business_reads_require_dataset_version(path: str) -> None:
    """Every business layer and dynamic frame must reject unversioned reads."""

    assert client.get(path).status_code == 422


def test_database_srid_geometry_types_migration_and_gist_indexes() -> None:
    """直接审计数据库，防止 ORM 响应正确但物理空间约束或索引缺失。"""

    with SessionLocal() as session:
        revision = session.scalar(text("SELECT version_num FROM alembic_version"))
        assert revision == "20260813_0010"

        geometries = session.execute(
            text(
                """
                SELECT 'river' AS table_name, GeometryType(geometry), ST_SRID(geometry)
                FROM river WHERE id = (SELECT min(id) FROM river)
                UNION ALL
                SELECT 'gate', GeometryType(geometry), ST_SRID(geometry)
                FROM gate WHERE id = (SELECT min(id) FROM gate)
                UNION ALL
                SELECT 'pump', GeometryType(geometry), ST_SRID(geometry)
                FROM pump WHERE id = (SELECT min(id) FROM pump)
                UNION ALL
                SELECT 'cross_section', GeometryType(geometry), ST_SRID(geometry)
                FROM cross_section WHERE id = (SELECT min(id) FROM cross_section)
                UNION ALL
                SELECT 'map_annotation', GeometryType(geometry), ST_SRID(geometry)
                FROM map_annotation WHERE id = (SELECT min(id) FROM map_annotation)
                """
            )
        ).all()
        assert set(geometries) == {
            ("river", "LINESTRING", 4490),
            ("gate", "POINT", 4490),
            ("pump", "POINT", 4490),
            ("cross_section", "POINT", 4490),
            ("map_annotation", "POINT", 4490),
        }

        gist_indexes = session.execute(
            text(
                """
                SELECT indexname FROM pg_indexes
                WHERE schemaname = 'public'
                  AND indexname IN (
                    'ix_river_geometry_gist', 'ix_gate_geometry_gist',
                    'ix_pump_geometry_gist', 'ix_cross_section_geometry_gist',
                    'ix_map_annotation_geometry_gist'
                  )
                  AND lower(indexdef) LIKE '%using gist%'
                """
            )
        ).scalars().all()
        assert set(gist_indexes) == {
            "ix_river_geometry_gist",
            "ix_map_annotation_geometry_gist",
            "ix_gate_geometry_gist",
            "ix_pump_geometry_gist",
            "ix_cross_section_geometry_gist",
        }
