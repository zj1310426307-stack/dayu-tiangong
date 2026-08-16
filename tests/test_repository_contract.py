"""在完整仓库边界中验证目录、前端路由与数据库基线契约。"""

from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]


def test_required_phase1_files_exist() -> None:
    """Phase 1 任务书要求的目录与关键文件必须全部存在。"""

    expected_paths = [
        "frontend/package.json",
        "frontend/src/router/index.tsx",
        "backend/app/main.py",
        "backend/app/api/router.py",
        "backend/app/services/system_service.py",
        "backend/app/gis/models.py",
        "backend/app/gis/router.py",
        "backend/app/gis/service.py",
        "backend/app/geoserver/router.py",
        "backend/app/geoserver/service.py",
        "backend/app/gis_governance/errors.py",
        "backend/app/gis_governance/hashing.py",
        "backend/app/gis_governance/repository.py",
        "backend/app/gis_governance/router.py",
        "backend/app/gis_governance/schemas.py",
        "backend/app/gis_governance/service.py",
        "backend/app/gis_governance/state.py",
        "backend/app/gis_governance/validation.py",
        "geoserver/bootstrap.py",
        "geoserver/verify.py",
        "geoserver/styles/river.sld",
        "geoserver/styles/river_segment.sld",
        "geoserver/styles/river_node.sld",
        "geoserver/styles/cross_section.sld",
        "geoserver/styles/gate.sld",
        "geoserver/styles/pump.sld",
        "database/alembic.ini",
        "database/migrations/versions/20260811_0001_phase1_gis.py",
        "database/migrations/versions/20260811_0002_phase2_hydraulic_database.py",
        "database/migrations/versions/20260812_0003_phase3_hydraulic_engine.py",
        "database/migrations/versions/20260812_0004_phase4_dispatch.py",
        "database/migrations/versions/20260814_0011_qgis_governance.py",
        "database/migrations/versions/20260814_0012_publish_geoserver_boundary.py",
        "database/bootstrap_qgis.py",
        "database/bootstrap_app.py",
        "database/seed/demo_data.py",
        "database/schema.sql",
        "database/database_design.md",
        "model/hydraulic_model.py",
        "model/engine.py",
        "model/solver/saint_venant.py",
        "backend/app/model_engine/router.py",
        "backend/app/model_engine/service.py",
        "backend/app/dispatch/router.py",
        "backend/app/worker/tasks.py",
        "model/network/solver.py",
        "model/control/rules.py",
        "frontend/src/pages/hydraulic/HydraulicPages.tsx",
        "optimization/optimizer.py",
        "ai/assistant/core.py",
        "ai/retrieval/engine.py",
        "ai/guardrails/policy.py",
        "ai/report/renderer.py",
        "backend/app/ai/router.py",
        "backend/app/ai/service.py",
        "frontend/src/pages/ai/AIAssistantPage.tsx",
        "docs/project_introduction.md",
        "docs/architecture.md",
        "docs/coordinate_system.md",
        "docs/review/phase1_gis_review.md",
        "docs/review/phase2_database_review.md",
        "docs/adr/ADR-0011-qgis-controlled-production.md",
        "qgis/README.md",
        "qgis/Start_Dayu_QGIS.cmd",
        "qgis/Start_Dayu_QGIS.ps1",
        "qgis/projects/dayu_tiangong_ltr.qgs",
        "qgis/styles/staging_river.qml",
        "qgis/styles/staging_cross_section.qml",
        "qgis/styles/staging_gate.qml",
        "qgis/styles/staging_pump.qml",
        "docker/docker-compose.yml",
        "README.md",
    ]

    missing_paths = [path for path in expected_paths if not (REPOSITORY_ROOT / path).is_file()]
    assert missing_paths == []


def test_frontend_and_database_static_contracts() -> None:
    """前端 GIS 路由、生成客户端与四张空间表必须保留在源码契约中。"""

    router_source = (REPOSITORY_ROOT / "frontend/src/router/index.tsx").read_text(
        encoding="utf-8"
    )
    schema_source = (REPOSITORY_ROOT / "database/schema.sql").read_text(
        encoding="utf-8"
    ).lower()
    cesium_source = (REPOSITORY_ROOT / "frontend/src/components/gis/CesiumMap.tsx").read_text(
        encoding="utf-8"
    )
    generated_client = (
        REPOSITORY_ROOT / "frontend/src/api/generated/client.ts"
    ).read_text(encoding="utf-8")

    for route_path in ["'/'", "'/gis'", "'rivers'", "'/data-center/rivers'", "'/data-center/cross-sections'", "'/data-center/gates'", "'/data-center/pumps'", "'/data-center/imports'", "'/data-center/validation'", "'/data-center/model-data'", "'/dispatch'", "'/hydraulic'", "'hydraulic/config'", "'hydraulic/tasks'", "'hydraulic/results'", "'/optimization'", "'/ai-assistant'"]:
        assert route_path in router_source

    assert "create extension if not exists postgis" in schema_source
    for table_name in ["river", "cross_section", "gate", "pump"]:
        assert f"create table {table_name}" in schema_source

    assert "MapPlaceholder" not in cesium_source
    assert "GisAdapterRuntime" in cesium_source
    assert "getGISCatalog" in cesium_source
    adapter_source = (
        REPOSITORY_ROOT / "frontend/src/gis/adapters/imagery.ts"
    ).read_text(encoding="utf-8")
    assert "WebMapServiceImageryProvider" in adapter_source
    assert "QgisWmsAdapter" in adapter_source
    assert "WebMapTileServiceImageryProvider" in adapter_source
    assert "ArcGisMapServerImageryProvider.fromUrl" not in cesium_source
    assert "World_Imagery/MapServer" not in cesium_source
    assert "getGeoServerConfig" not in cesium_source
    selection_source = (
        REPOSITORY_ROOT / "frontend/src/gis/selection/identity.ts"
    ).read_text(encoding="utf-8")
    assert "getRiver" in selection_source
    assert "getCrossSection" in selection_source
    assert "/api/v1/gis/rivers" in generated_client
    assert "/api/v1/gis/geoserver/health" in generated_client
    assert "fetch(" not in cesium_source
    assert "/api/v1/rivers" in generated_client
    assert "/api/v1/import/${kind}" in generated_client
    assert "/api/v1/validation/run" in generated_client
    assert "/api/v1/model/tasks" in generated_client
    assert "/api/v1/model/results/" in generated_client
    assert "/api/v1/ai/chat" in generated_client
    assert "/api/v1/ai/report/generate" in generated_client
    assert "/api/v1/gis-governance/batches" in generated_client
    assert "/api/v1/gis-governance/publications" in generated_client
    assert "export class ApiError extends Error" in generated_client
    assert "readonly code?: string" in generated_client
    assert "readonly context?: Record<string, unknown>" in generated_client
    assert "throw new ApiError(response.status, decodeApiError(payload))" in generated_client


def test_dgis_postgis_ui_forwards_governance_provenance() -> None:
    """DGIS raw landing must collect and forward the governed entity identity and actor."""

    data_manager = (
        REPOSITORY_ROOT / "frontend/src/components/dgis/DataManager.tsx"
    ).read_text(encoding="utf-8")
    generator = (
        REPOSITORY_ROOT / "frontend/scripts/update-openapi.mjs"
    ).read_text(encoding="utf-8")
    generated_client = (
        REPOSITORY_ROOT / "frontend/src/api/generated/client.ts"
    ).read_text(encoding="utf-8")

    for entity_type in ["river", "cross_section", "gate", "pump"]:
        assert f"value: '{entity_type}'" in data_manager
    for field in ["entityType", "parentVersionId", "operator"]:
        assert field in data_manager
    for form_field in ["entity_type", "parent_version_id", "operator"]:
        assert f"fields.{form_field}" in generator
        assert f"fields.{form_field}" in generated_client
    assert "optionsOrTargetSrid?: DGISPostGISImportOptions | number" in generator
    assert "optionsOrTargetSrid?: DGISPostGISImportOptions | number" in generated_client
