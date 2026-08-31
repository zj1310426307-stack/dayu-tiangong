"""Benchmark 01: rectangular steady uniform flow."""

from model.hydraulic_1d import rectangular_manning_discharge
from model.hydraulic_1d.mascaret.adapter import MascaretModelValidator
from tests.benchmark.hydraulic_1d.cases import benchmark_01_uniform_rectangular


def test_uniform_flow_has_a_theoretical_q_h_v_reference() -> None:
    """Prove the frozen Q/H/V values close the same rectangular Manning case."""

    case = benchmark_01_uniform_rectangular()
    MascaretModelValidator().validate(case.model)
    expected_discharge = rectangular_manning_discharge(
        width_m=10.0,
        depth_m=2.0,
        manning_n=0.03,
        slope=0.0001,
    )
    upstream = next(item for item in case.model.boundaries if item.location == "upstream")
    downstream = next(item for item in case.model.boundaries if item.location == "downstream")
    assert upstream.series[0].value == expected_discharge
    assert downstream.series[0].value == 1.9
    assert [item.water_level_m for item in case.model.initial_condition.by_section] == [
        2.0,
        1.95,
        1.9,
    ]
    assert case.reference_velocity_m_s == expected_discharge / 20.0
