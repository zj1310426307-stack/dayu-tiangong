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
        "geoserver/styles/administrative_area_open.sld",
        "geoserver/styles/road_open.sld",
        "geoserver/styles/waterway_open.sld",
        "database/alembic.ini",
        "database/migrations/versions/20260811_0001_phase1_gis.py",
        "database/migrations/versions/20260811_0002_phase2_hydraulic_database.py",
        "database/migrations/versions/20260812_0003_phase3_hydraulic_engine.py",
        "database/migrations/versions/20260812_0004_phase4_dispatch.py",
        "database/migrations/versions/20260814_0011_qgis_governance.py",
        "database/migrations/versions/20260814_0012_publish_geoserver_boundary.py",
        "database/migrations/versions/20260817_0015_gis_reset_geoserver_catalog.py",
        "database/migrations/versions/20260817_0016_guangdong_open_reference_data.py",
        "database/migrations/versions/20260817_0017_high_resolution_imagery.py",
        "database/migrations/versions/20260817_0018_chinese_map_labels.py",
        "database/migrations/versions/20260831_0024_mascaret_unified_result.py",
        "database/import_open_reference_data.py",
        "tests/test_open_reference_chinese_labels.py",
        "database/bootstrap_qgis.py",
        "database/bootstrap_app.py",
        "database/seed/demo_data.py",
        "database/seed/gis_catalog.py",
        "database/gis/schema.sql",
        "database/schema.sql",
        "database/database_design.md",
        "AGENTS.md",
        "model/hydraulic_1d/contracts.py",
        "model/hydraulic_1d/engine.py",
        "model/hydraulic_1d/mascaret/adapter.py",
        "model/hydraulic_1d/mascaret/parser.py",
        "model/hydraulic_1d/mascaret/runtime.py",
        "backend/app/model_engine/router.py",
        "backend/app/model_engine/service.py",
        "backend/app/model_engine/hydraulic_1d_service.py",
        "backend/app/hydraulic/result_geojson.py",
        "backend/app/dispatch/router.py",
        "backend/app/worker/tasks.py",
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
        "frontend/src/gis/MapView.tsx",
        "frontend/src/gis/LayerManager.tsx",
        "frontend/src/gis/Popup.tsx",
        "frontend/src/gis/StyleManager.ts",
        "frontend/src/gis/Coordinate.tsx",
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
        "docker/geoserver.Dockerfile",
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
    map_source = (REPOSITORY_ROOT / "frontend/src/gis/MapView.tsx").read_text(
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

    assert "new OlMap" in map_source
    assert "new TileWMS" in map_source
    assert "getGISCatalog" in map_source
    assert "getGISFeatureInfo" in map_source
    assert "projection: 'EPSG:3857'" in map_source
    assert "Cesium" not in map_source
    assert "/api/v1/gis/rivers" in generated_client
    assert "/api/v1/gis/geoserver/health" in generated_client
    assert "fetch(" not in map_source
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


def test_frontend_dataset_lifecycle_is_reachable_and_fail_safe() -> None:
    """The web app must expose a draft workflow while keeping frozen versions read-only."""

    context_source = (
        REPOSITORY_ROOT / "frontend/src/context/DatasetVersionContext.tsx"
    ).read_text(encoding="utf-8")
    layout_source = (
        REPOSITORY_ROOT / "frontend/src/layout/MainLayout.tsx"
    ).read_text(encoding="utf-8")
    data_pages = (
        REPOSITORY_ROOT / "frontend/src/pages/data-center/DataCenterPages.tsx"
    ).read_text(encoding="utf-8")
    hydraulic_pages = (
        REPOSITORY_ROOT / "frontend/src/pages/hydraulic/HydraulicPages.tsx"
    ).read_text(encoding="utf-8")
    optimization_pages = (
        REPOSITORY_ROOT / "frontend/src/pages/optimization/OptimizationPages.tsx"
    ).read_text(encoding="utf-8")
    dispatch_pages = (
        REPOSITORY_ROOT / "frontend/src/pages/dispatch/DispatchPages.tsx"
    ).read_text(encoding="utf-8")
    router_source = (
        REPOSITORY_ROOT / "frontend/src/router/index.tsx"
    ).read_text(encoding="utf-8")
    home_source = (
        REPOSITORY_ROOT / "frontend/src/pages/HomePage.tsx"
    ).read_text(encoding="utf-8")
    water_trend_source = (
        REPOSITORY_ROOT / "frontend/src/components/WaterTrendChart.tsx"
    ).read_text(encoding="utf-8")
    gis_source = (
        REPOSITORY_ROOT / "frontend/src/pages/GisPage.tsx"
    ).read_text(encoding="utf-8")
    generator = (
        REPOSITORY_ROOT / "frontend/scripts/update-openapi.mjs"
    ).read_text(encoding="utf-8")
    generated_client = (
        REPOSITORY_ROOT / "frontend/src/api/generated/client.ts"
    ).read_text(encoding="utf-8")
    nginx_source = (
        REPOSITORY_ROOT / "docker/nginx.conf"
    ).read_text(encoding="utf-8")

    for token in ["currentVersion", "isMutable", "refreshVersions", "item.status === 'published'"]:
        assert token in context_source
    assert "createDatasetVersion(values)" in layout_source
    assert "新建草稿" in layout_source
    assert "datasetVersionId ?? 1" not in data_pages
    assert "DatasetWriteNotice" in data_pages
    assert "Boolean(datasetVersionId)" in data_pages
    assert "getSimulationCases(datasetVersionId)" in hydraulic_pages
    assert "getSimulationCases(datasetVersionId)" in optimization_pages
    assert "暂无计算方案" in dispatch_pages
    assert "errorElement: <RouteErrorPage />" in router_source
    assert "components/gis/CesiumMap" not in home_source
    assert "echarts" not in water_trend_source
    assert '<svg className="trend-chart"' in water_trend_source
    assert "from '../gis/MapView'" in gis_source
    assert "PostGIS 是唯一数据中心" in gis_source
    assert "QGIS Desktop 仅用于受控数据生产" in gis_source
    assert "location = /index.html" in nginx_source
    assert 'Cache-Control "no-store, no-cache, must-revalidate"' in nginx_source

    generated_functions = [
        "createDatasetVersion",
        "updateDatasetVersion",
        "deleteDatasetVersion",
        "createModelParameter",
        "updateModelParameter",
        "deleteModelParameter",
        "createBoundaryCondition",
        "updateBoundaryCondition",
        "deleteBoundaryCondition",
        "createSimulationCase",
        "updateSimulationCase",
        "deleteSimulationCase",
    ]
    for function_name in generated_functions:
        assert f"export const {function_name}" in generator
        assert f"export const {function_name}" in generated_client


def test_async_task_monitors_use_the_generated_dataset_version_boundary() -> None:
    """Task lists must filter in the API instead of loading every version in the browser."""

    generator = (
        REPOSITORY_ROOT / "frontend/scripts/update-openapi.mjs"
    ).read_text(encoding="utf-8")
    generated_client = (
        REPOSITORY_ROOT / "frontend/src/api/generated/client.ts"
    ).read_text(encoding="utf-8")
    hydraulic_pages = (
        REPOSITORY_ROOT / "frontend/src/pages/hydraulic/HydraulicPages.tsx"
    ).read_text(encoding="utf-8")
    optimization_pages = (
        REPOSITORY_ROOT / "frontend/src/pages/optimization/OptimizationPages.tsx"
    ).read_text(encoding="utf-8")
    dispatch_pages = (
        REPOSITORY_ROOT / "frontend/src/pages/dispatch/DispatchPages.tsx"
    ).read_text(encoding="utf-8")

    for source in (generator, generated_client):
        normalized = source.replace(r"\${", "${").replace(r"\`", "`")
        assert "export interface DatasetTaskListQuery" in normalized
        assert "function datasetTaskListArgs(" in normalized
        assert "paramsOrBaseUrl: DatasetTaskListQuery | string = {}" in normalized
        assert "listHydraulicTasks = (paramsOrBaseUrl:" in normalized
        assert "listOptimizationTasks = (paramsOrBaseUrl:" in normalized
        assert "/api/v1/model/tasks${toQuery(params)}" in normalized
        assert "/api/v1/optimization/tasks${toQuery(params)}" in normalized

    assert "listHydraulicTasks({ dataset_version_id: datasetVersionId })" in hydraulic_pages
    assert "listOptimizationTasks({ dataset_version_id: datasetVersionId })" in optimization_pages
    assert "listDispatchRuns({ dataset_version_id: datasetVersionId" in dispatch_pages
    assert "runPage.items.filter" not in dispatch_pages
    for source in (hydraulic_pages, optimization_pages, dispatch_pages):
        assert "requestSequenceRef" in source
