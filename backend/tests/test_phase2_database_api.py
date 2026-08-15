"""在真实 PostGIS 上验证 Phase 2 管理、拓扑、校验和模型输入契约。"""

import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.database.session import SessionLocal
from app.main import app


pytestmark = pytest.mark.skipif(
    os.getenv("RUN_POSTGIS_TESTS") != "1",
    reason="需要先启动并初始化 Phase 2 PostGIS，再设置 RUN_POSTGIS_TESTS=1",
)
client = TestClient(app)
REPOSITORY_ROOT = Path(__file__).resolve().parents[2]


def test_phase2_lists_topology_validation_and_model_input() -> None:
    """演示版本必须贯通资产读取、拓扑、质量门禁和 Phase 3 输入快照。"""

    assert client.get("/api/v1/rivers").json()["total"] == 3
    assert client.get("/api/v1/cross-sections").json()["total"] == 20
    assert client.get("/api/v1/gates").json()["total"] == 5
    assert client.get("/api/v1/pumps").json()["total"] == 3

    topology = client.get(
        "/api/v1/rivers/topology", params={"dataset_version_id": 1}
    ).json()
    assert len(topology["nodes"]) == 8
    assert len(topology["segments"]) == 7
    assert len(topology["connections"]) == 7
    assert sum(node["node_type"] == "confluence" for node in topology["nodes"]) == 2

    report = client.post("/api/v1/validation/run", json={"dataset_version_id": 1})
    assert report.status_code == 200
    assert report.json()["summary"] == {
        "errors": 0,
        "warnings": 0,
        "passed": 15,
        "is_model_ready": True,
    }

    cases = client.get(
        "/api/v1/model-data/simulation-cases", params={"dataset_version_id": 1}
    ).json()
    snapshot = client.get(f"/api/v1/model-data/simulation-cases/{cases[0]['id']}/input")
    assert snapshot.status_code == 200
    payload = snapshot.json()
    assert payload["schema_version"] == "dayu.model-input.v1"
    assert len(payload["rivers"]) == 3
    assert len(payload["cross_sections"]) == 20
    assert len(payload["segments"]) == 7


def test_river_crud_round_trip_and_conflict_contract() -> None:
    """河道 CRUD 在临时 draft 闭环，并证明 published DEMO 不可写。"""

    frozen = client.post(
        "/api/v1/rivers",
        json={
            "dataset_version_id": 1,
            "name": "不得写入已发布版本",
            "code": "TEST-FROZEN-VERSION",
            "length": 1,
            "level": "channel",
            "status": "planned",
            "geometry": {"type": "LineString", "coordinates": [[120.6, 30.1], [120.61, 30.11]]},
        },
    )
    assert frozen.status_code == 422

    draft = client.post(
        "/api/v1/model-data/dataset-versions",
        json={
            "version": "PYTEST-DRAFT-CRUD",
            "name": "pytest draft",
            "description": "临时可变版本",
            "creator": "pytest",
        },
    )
    assert draft.status_code == 201
    draft_id = draft.json()["id"]

    create = client.post(
        "/api/v1/rivers",
        json={
            "dataset_version_id": draft_id,
            "name": "API 临时测试河道",
            "code": "TEST-RIVER-API",
            "length": 1000,
            "level": "channel",
            "status": "planned",
            "description": "pytest 临时记录",
            "geometry": {
                "type": "LineString",
                "coordinates": [[120.6, 30.1], [120.61, 30.11]],
            },
        },
    )
    assert create.status_code == 201
    river_id = create.json()["id"]

    duplicate = client.post("/api/v1/rivers", json=create.json() | {"id": None, "created_time": None})
    assert duplicate.status_code in {409, 422}

    update = client.put(
        f"/api/v1/rivers/{river_id}",
        json={"status": "active", "description": "已通过接口修改"},
    )
    assert update.status_code == 200
    assert update.json()["status"] == "active"
    assert client.get(f"/api/v1/rivers/{river_id}").status_code == 200
    assert client.delete(f"/api/v1/rivers/{river_id}").status_code == 204
    assert client.get(f"/api/v1/rivers/{river_id}").status_code == 404
    assert client.delete(f"/api/v1/model-data/dataset-versions/{draft_id}").status_code == 204


def test_published_model_configuration_is_immutable() -> None:
    """Freeze model parameters, boundaries, and cases together with GIS core data."""

    parameter = client.get(
        "/api/v1/model-data/parameters", params={"dataset_version_id": 1}
    ).json()[0]
    boundary = client.get(
        "/api/v1/model-data/boundary-conditions", params={"dataset_version_id": 1}
    ).json()[0]
    case = client.get(
        "/api/v1/model-data/simulation-cases", params={"dataset_version_id": 1}
    ).json()[0]

    assert client.post(
        "/api/v1/model-data/parameters",
        json={
            "dataset_version_id": 1,
            "parameter_type": "solver",
            "parameter_name": "forbidden-published-write",
            "value": 1,
            "unit": "1",
        },
    ).status_code == 422
    assert client.put(
        f"/api/v1/model-data/parameters/{parameter['id']}", json={"value": 999}
    ).status_code == 422
    assert client.delete(
        f"/api/v1/model-data/parameters/{parameter['id']}"
    ).status_code == 422
    assert client.put(
        f"/api/v1/model-data/boundary-conditions/{boundary['id']}",
        json={"description": "forbidden"},
    ).status_code == 422
    assert client.delete(
        f"/api/v1/model-data/boundary-conditions/{boundary['id']}"
    ).status_code == 422
    assert client.put(
        f"/api/v1/model-data/simulation-cases/{case['id']}",
        json={"description": "forbidden"},
    ).status_code == 422
    assert client.delete(
        f"/api/v1/model-data/simulation-cases/{case['id']}"
    ).status_code == 422


def test_phase2_physical_tables_revision_and_spatial_indexes() -> None:
    """直接审计物理版本、拓扑表和新增 GIST 索引。"""

    with SessionLocal() as session:
        assert session.scalar(text("SELECT version_num FROM alembic_version")) == "20260814_0012"
        tables = set(
            session.execute(
                text(
                    """
                    SELECT tablename FROM pg_tables
                    WHERE schemaname = 'public'
                      AND tablename IN (
                        'dataset_version', 'river_node', 'river_segment',
                        'river_connection', 'model_parameter',
                        'boundary_condition', 'simulation_case', 'map_annotation'
                      )
                    """
                )
            ).scalars()
        )
        assert tables == {
            "dataset_version",
            "river_node",
            "river_segment",
            "river_connection",
            "model_parameter",
            "boundary_condition",
            "simulation_case",
            "map_annotation",
        }
        indexes = set(
            session.execute(
                text(
                    """
                    SELECT indexname FROM pg_indexes
                    WHERE schemaname = 'public'
                      AND indexname IN (
                        'ix_river_node_geometry_gist',
                        'ix_river_segment_geometry_gist'
                      )
                      AND lower(indexdef) LIKE '%using gist%'
                    """
                )
            ).scalars()
        )
        assert indexes == {"ix_river_node_geometry_gist", "ix_river_segment_geometry_gist"}


def test_excel_template_import_round_trip_is_atomic() -> None:
    """正式模板必须可被真实 Excel 端点导入，并能完整清理测试版本。"""

    version_response = client.post(
        "/api/v1/model-data/dataset-versions",
        json={
            "version": "TEST-IMPORT-V1",
            "name": "Excel 导入临时版本",
            "description": "pytest 后自动清理",
            "creator": "pytest",
        },
    )
    assert version_response.status_code == 201
    version_id = version_response.json()["id"]
    template_path = REPOSITORY_ROOT / "docs/templates/phase2_rivers_template.xlsx"

    with template_path.open("rb") as file_handle:
        response = client.post(
            "/api/v1/import/excel",
            data={"resource": "rivers", "dataset_version_id": str(version_id)},
            files={
                "file": (
                    template_path.name,
                    file_handle,
                    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                )
            },
        )
    assert response.status_code == 200
    assert response.json()["status"] == "success"
    assert response.json()["imported_count"] == 1

    imported = client.get(
        "/api/v1/rivers", params={"dataset_version_id": version_id}
    ).json()["items"]
    assert [item["code"] for item in imported] == ["SAMPLE-RIVER-001"]
    assert client.delete(f"/api/v1/rivers/{imported[0]['id']}").status_code == 204
    assert (
        client.delete(f"/api/v1/model-data/dataset-versions/{version_id}").status_code
        == 204
    )
