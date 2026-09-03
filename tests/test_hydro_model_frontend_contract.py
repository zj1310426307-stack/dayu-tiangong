"""Static frontend contracts for the HYDRO-MODEL-01 minimum browser loop."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
HYDRAULIC_PAGE = ROOT / "frontend/src/pages/hydraulic/HydraulicPages.tsx"
DISPATCH_PAGE = ROOT / "frontend/src/pages/dispatch/DispatchPages.tsx"
MODEL_DATA_PAGE = ROOT / "frontend/src/pages/data-center/DataCenterPages.tsx"
GENERATED_CLIENT = ROOT / "frontend/src/api/generated/client.ts"


def test_hydraulic_pages_use_the_single_standard_1d_mascaret_route() -> None:
    """The browser must expose one solver-neutral input contract and MASCARET route."""

    source = HYDRAULIC_PAGE.read_text(encoding="utf-8")
    assert "const HYDRAULIC_INPUT_SCHEMA = 'dayu.hydraulic-1d.input.v1'" in source
    assert "const HYDRAULIC_ENGINE = 'mascaret'" in source
    assert "getHydraulicReadiness" in source
    assert "previewHydraulicModel" in source
    assert "STANDARD 1D / MASCARET" in source
    assert "dayu.model-input.v" not in source
    assert "D3A" not in source
    assert "/model/v4" not in source


def test_dispatch_detail_exposes_a_non_synthetic_24_hour_structure_view() -> None:
    """The result page must consume generated-client rows and disclose missing hours."""

    source = DISPATCH_PAGE.read_text(encoding="utf-8")
    assert "from '../../api/generated/client'" in source
    assert "getDispatchStructures" in source
    assert "fetch(" not in source
    assert "const DISPATCH_MILESTONES_HOURS = [0, 6, 12, 24] as const" in source
    assert "metric: 'actual_value', title: '闸门开度'" in source
    assert "metric: 'flow', title: '闸门流量'" in source
    assert "metric: 'flow', title: '泵站流量'" in source
    assert "metric: 'energy_kwh', title: '泵站累计能耗'" in source
    assert 'title="闸泵当前运行状态"' in source
    assert "开度 / 原生容量" in source
    assert "控制模式 / 来源" in source
    assert "latestSources.get(key)?.label ?? '固定输入'" in source
    assert "clearResultData();" in source
    assert "activeRunIdRef.current === requestedRunId" in source
    assert "const currentRun = run?.id === id ? run : undefined" in source
    assert (
        "const currentComparison = resultRunId === id ? comparison : undefined"
        in source
    )
    assert "structureCoverage.every" in source
    assert "connectNulls: false" in source
    assert "空缺时段显式断线，不做插值或伪造补齐" in source


def test_hydraulic_ui_exposes_runtime_lifecycle_and_unified_results() -> None:
    """Runtime readiness, lifecycle retries, and unified results stay backend-governed."""

    source = HYDRAULIC_PAGE.read_text(encoding="utf-8")
    for field_name in (
        "execution_attempt_count",
        "manual_retry_count",
        "infrastructure_retry_count",
    ):
        assert field_name in source

    assert "task.retry_count" not in source
    assert "task.retry_eligible" in source
    assert "task.retry_block_reason" in source
    assert "runtime_available" in source
    assert "runtime_identity" in source
    assert "MASCARET 运行时身份" in source
    assert "MASCARET 运行时不可用" in source
    for result_field in (
        "result.depth",
        "result.flow_area",
        "result.wet_area",
        "result.hydraulic_radius",
        "result.top_width",
        "result.froude_number",
    ):
        assert result_field in source

    assert "numerical_retry_count" not in source
    assert "downloadHydraulicV4Artifact" not in source
    assert "/model/v4" not in source


def test_boundary_editor_uses_authoritative_endpoint_and_lateral_fields() -> None:
    """The UI and generated client must share the current Boundary CRUD contract."""

    source = MODEL_DATA_PAGE.read_text(encoding="utf-8")
    generated = GENERATED_CLIENT.read_text(encoding="utf-8")
    for boundary_type in (
        "upstream_discharge",
        "downstream_water_level",
        "lateral_inflow",
    ):
        assert boundary_type in source
        assert boundary_type in generated
    for field_name in ("hydraulic_node_id", "branch_id", "chainage_m"):
        assert field_name in source
        assert f'"{field_name}"?: number | null;' in generated
    assert 'name="hydraulic_node_id"' in source
    assert 'name="branch_id"' in source
    assert 'name="chainage_m"' in source
    assert 'name="target_node_id"' not in source
    assert "upstream_flow" not in source
    assert "downstream_stage" not in source
