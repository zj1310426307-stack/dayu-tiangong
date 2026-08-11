"""验证系统接口的 HTTP 契约和健康语义。"""

from fastapi.testclient import TestClient

from app.main import app


client = TestClient(app)


def test_root_returns_expected_system_information() -> None:
    """根接口必须严格返回任务书约定的四个字段。"""

    response = client.get("/")

    assert response.status_code == 200
    assert response.json() == {
        "name": "大禹·天工",
        "version": "2.0.0",
        "description": "河网智能调度与数字孪生水利平台",
        "status": "running",
    }


def test_health_endpoint_reports_application_health() -> None:
    """应用健康端点必须返回可供部署探针消费的稳定结构。"""

    response = client.get("/api/v1/health")

    assert response.status_code == 200
    assert response.json() == {
        "status": "healthy",
        "service": "dayu-tiangong-api",
        "version": "2.0.0",
    }


def test_openapi_contains_system_and_gis_routes() -> None:
    """OpenAPI 必须暴露系统与 GIS 契约，供前端生成唯一客户端。"""

    schema = client.get("/openapi.json").json()

    assert "/" in schema["paths"]
    assert "/api/v1/health" in schema["paths"]
    for resource in ["rivers", "gates", "pumps", "cross_sections"]:
        assert f"/api/v1/gis/{resource}" in schema["paths"]
        detail_path = f"/api/v1/gis/{resource}/{{{resource.removesuffix('s')}_id}}"
        if resource == "cross_sections":
            detail_path = "/api/v1/gis/cross_sections/{section_id}"
        assert detail_path in schema["paths"]

    assert "/api/v1/gis/health" in schema["paths"]
    assert "/api/v1/gis/stats" in schema["paths"]
    for path in [
        "/api/v1/rivers",
        "/api/v1/cross-sections",
        "/api/v1/gates",
        "/api/v1/pumps",
        "/api/v1/import/excel",
        "/api/v1/validation/run",
        "/api/v1/model-data/dataset-versions",
    ]:
        assert path in schema["paths"]
