"""Real MASCARET acceptance for Engineering-03 networks and structures."""

from __future__ import annotations

from json import dumps, loads
from pathlib import Path

import pytest

from model.hydraulic_1d import Hydraulic1DExecutionContext
from model.hydraulic_1d.mascaret import (
    MASCARET_RUNTIME_SKIP_REASON,
    MascaretEngine,
    MascaretRuntimeConfig,
)
from tests.benchmark.hydraulic_1d.network.cases import (
    NETWORK_CASES,
    STRUCTURE_CASES,
)
from tests.benchmark.hydraulic_1d.network.metrics import engineering_metrics


_MANIFEST = loads(
    Path(__file__).with_name("acceptance-manifest.json").read_text(encoding="utf-8")
)
_THRESHOLDS = _MANIFEST["thresholds"]


def _real_engine() -> MascaretEngine:
    """Skip with the shared machine reason instead of substituting numerics."""

    engine = MascaretEngine(MascaretRuntimeConfig.from_environment())
    available, reason = engine.availability()
    if not available:
        pytest.skip(f"{MASCARET_RUNTIME_SKIP_REASON}: {reason}")
    return engine


@pytest.mark.parametrize("case_factory", NETWORK_CASES, ids=lambda item: item().case_id)
@pytest.mark.mascaret_runtime
@pytest.mark.mascaret_numerical
@pytest.mark.mascaret_benchmark
@pytest.mark.engineering_network
def test_real_mascaret_engineering_network(case_factory, tmp_path) -> None:
    """Require topology ownership, direction, continuity, and storage-aware mass balance."""

    case = case_factory()
    result = _real_engine().run(
        case.model,
        Hydraulic1DExecutionContext(job_id=case.case_id, workspace_root=tmp_path),
    )
    metrics = engineering_metrics(case.model, result)
    print(dumps({"case_id": case.case_id, **metrics}, sort_keys=True))

    assert result.engine == "mascaret"
    assert result.engine_version == "v9.1.1"
    assert result.diagnostics["runtime_provenance"]["is_real"] is True
    assert result.diagnostics["runtime_provenance"]["version_verified"] is True
    assert {item.cross_section_id for item in result.records} == {
        item.id for item in case.model.cross_sections
    }
    assert all(value > 0.0 for value in metrics["branch_discharge_m3s"].values())
    assert (
        metrics["node_continuity_residual"]
        <= _THRESHOLDS["node_continuity_residual_max"]
    )
    assert (
        metrics["network_mass_balance_residual"]
        <= _THRESHOLDS["network_mass_balance_residual_max"]
    )
    assert (
        metrics["junction_water_level_spread_m"]
        <= _THRESHOLDS["junction_water_level_spread_m_max"]
    )


@pytest.mark.parametrize(
    "case_factory", STRUCTURE_CASES, ids=lambda item: item().case_id
)
@pytest.mark.mascaret_runtime
@pytest.mark.mascaret_numerical
@pytest.mark.mascaret_benchmark
@pytest.mark.engineering_structure
def test_real_mascaret_verified_structure_changes_solution(
    case_factory, tmp_path
) -> None:
    """Require each VERIFIED structure to execute natively and affect hydraulics."""

    case = case_factory()
    engine = _real_engine()
    result = engine.run(
        case.model,
        Hydraulic1DExecutionContext(job_id=case.case_id, workspace_root=tmp_path),
    )
    baseline_model = case.model.model_copy(update={"structures": ()})
    baseline = engine.run(
        baseline_model,
        Hydraulic1DExecutionContext(
            job_id=f"{case.case_id}-without-structure",
            workspace_root=tmp_path,
        ),
    )
    metrics = engineering_metrics(case.model, result)
    upstream_section_id = case.model.cross_sections[0].id
    structured_stage = max(
        item.water_level_m
        for item in result.records
        if item.cross_section_id == upstream_section_id
    )
    baseline_stage = max(
        item.water_level_m
        for item in baseline.records
        if item.cross_section_id == upstream_section_id
    )

    assert result.diagnostics["runtime_provenance"]["is_real"] is True
    assert structured_stage > baseline_stage + 0.01
    assert (
        metrics["network_mass_balance_residual"]
        <= _THRESHOLDS["network_mass_balance_residual_max"]
    )
    print(
        dumps(
            {
                "case_id": case.case_id,
                **metrics,
                "upstream_stage_delta_m": structured_stage - baseline_stage,
            },
            sort_keys=True,
        )
    )
