"""Shared metric schema and real-runtime gate for all five benchmark families."""

from math import isfinite

import pytest

from model.hydraulic_1d import (
    Hydraulic1DExecutionContext,
    HydraulicBenchmarkMetrics,
    evaluate_hydraulic_benchmark,
)
from model.hydraulic_1d.mascaret import (
    MASCARET_RUNTIME_SKIP_REASON,
    MascaretEngine,
    MascaretRuntimeConfig,
)
from tests.benchmark.hydraulic_1d.acceptance import assert_case_acceptance
from tests.benchmark.hydraulic_1d.cases import ALL_BENCHMARKS


def test_standard_metric_contract_contains_every_required_measure() -> None:
    """Keep benchmark artifact field names stable across engines and cases."""

    metrics = HydraulicBenchmarkMetrics(0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.1)
    assert set(metrics.to_dict()) == {
        "water_level_error",
        "discharge_error",
        "velocity_error",
        "peak_error",
        "peak_time_error",
        "mass_balance_error",
        "runtime",
    }


@pytest.mark.parametrize("case_factory", ALL_BENCHMARKS, ids=lambda item: item.__name__)
@pytest.mark.mascaret_runtime
def test_real_mascaret_benchmark_runtime_is_never_substituted(
    case_factory,
    tmp_path,
) -> None:
    """Execute each case and calculate all metrics only with the official runtime."""

    engine = MascaretEngine(MascaretRuntimeConfig.from_environment())
    available, reason = engine.availability()
    if not available:
        pytest.skip(f"{MASCARET_RUNTIME_SKIP_REASON}: {reason}")
    case = case_factory()
    result = engine.run(
        case.model,
        Hydraulic1DExecutionContext(
            job_id=case.benchmark_id,
            workspace_root=tmp_path,
        ),
    )
    metrics = evaluate_hydraulic_benchmark(
        case.model,
        result,
        reference_velocity_m_s=case.reference_velocity_m_s,
    )
    comparison_result = None
    comparison_metrics = None
    if case.comparison_model is not None:
        comparison_result = engine.run(
            case.comparison_model,
            Hydraulic1DExecutionContext(
                job_id=f"{case.benchmark_id}-comparison",
                workspace_root=tmp_path,
            ),
        )
        comparison_metrics = evaluate_hydraulic_benchmark(
            case.comparison_model,
            comparison_result,
        )

    assert result.engine == "mascaret"
    assert {item.cross_section_id for item in result.records} == {
        item.id for item in case.model.cross_sections
    }
    assert all(isfinite(value) and value >= 0.0 for value in metrics.to_dict().values())
    assert_case_acceptance(
        case,
        result,
        metrics,
        comparison_result=comparison_result,
        comparison_metrics=comparison_metrics,
    )
