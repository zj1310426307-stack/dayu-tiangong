"""Static frontend contracts for the HYDRO-MODEL-01 minimum browser loop."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
HYDRAULIC_PAGE = ROOT / "frontend/src/pages/hydraulic/HydraulicPages.tsx"
DISPATCH_PAGE = ROOT / "frontend/src/pages/dispatch/DispatchPages.tsx"


def test_hydraulic_tasks_default_to_model_input_v3() -> None:
    """The browser must freeze the v3 snapshot instead of silently requesting v2."""

    source = HYDRAULIC_PAGE.read_text(encoding="utf-8")
    assert source.count("input_schema_version: 'dayu.model-input.v3'") == 2
    assert "input_schema_version: 'dayu.model-input.v2'" not in source


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
    assert "开度 / 运行机组" in source
    assert "控制模式 / 来源" in source
    assert "latestSources.get(key)?.label ?? '固定输入'" in source
    assert "clearResultData();" in source
    assert "activeRunIdRef.current === requestedRunId" in source
    assert "const currentRun = run?.id === id ? run : undefined" in source
    assert "const currentComparison = resultRunId === id ? comparison : undefined" in source
    assert "structureCoverage.every" in source
    assert "connectNulls: false" in source
    assert "空缺时段显式断线，不做插值或伪造补齐" in source
