"""HYDRO-MODEL-02-B 断面静水压力矩合同测试。"""

import math

import pytest

from model.core.errors import HydraulicInputError
from model.geometry.sections import (
    RectangularSectionGeometry,
    SectionGeometry,
    TabulatedSectionGeometry,
)


def test_section_geometry_contract_exposes_pressure_moment() -> None:
    """新增 I1 合同后，内置断面仍满足可运行时协议。"""

    rectangle = RectangularSectionGeometry(width=4.0, bed_elevation=10.0)
    tabulated = TabulatedSectionGeometry.from_points(
        [[0.0, 2.0], [1.0, 0.0], [3.0, 0.0], [4.0, 2.0]]
    )

    assert isinstance(rectangle, SectionGeometry)
    assert isinstance(tabulated, SectionGeometry)


def test_rectangular_pressure_moment_matches_analytic_solution() -> None:
    """矩形断面必须满足 I1 = b h² / 2，且参数是绝对水位。"""

    geometry = RectangularSectionGeometry(width=4.0, bed_elevation=10.0)

    assert geometry.pressure_moment(13.0) == pytest.approx(18.0)
    assert geometry.pressure_moment(13.0) == pytest.approx(
        geometry.area(13.0) * (13.0 - geometry.bed_elevation) / 2.0
    )
    assert geometry.pressure_moment(10.0) == 0.0
    assert geometry.pressure_moment(9.0) == 0.0


@pytest.mark.parametrize("stage", [math.nan, math.inf, -math.inf])
def test_rectangular_pressure_moment_rejects_non_finite_stage(stage: float) -> None:
    """矩形断面不得把非有限水位传入通量计算。"""

    geometry = RectangularSectionGeometry(width=4.0, bed_elevation=10.0)

    with pytest.raises(HydraulicInputError, match="水位必须有限"):
        geometry.pressure_moment(stage)


def test_rectangular_pressure_moment_rejects_finite_input_that_overflows() -> None:
    """有限输入即使可能溢出，也不得返回 Inf。"""

    geometry = RectangularSectionGeometry(width=4.0, bed_elevation=10.0)

    with pytest.raises(HydraulicInputError, match="静水压力矩必须有限"):
        geometry.pressure_moment(1.0e308)


def test_tabulated_pressure_moment_integrates_piecewise_linear_profile_exactly() -> None:
    """梯形折线的分段解析积分必须与闭式结果一致。"""

    geometry = TabulatedSectionGeometry.from_points(
        [[0.0, 2.0], [1.0, 0.0], [3.0, 0.0], [4.0, 2.0]]
    )

    # H=1 m 时 b(z)=2+z，I1=∫₀¹(1-z)(2+z)dz=7/6 m³。
    assert geometry.pressure_moment(1.0) == pytest.approx(7.0 / 6.0)
    assert geometry.pressure_moment(geometry.maximum_stage) == pytest.approx(16.0 / 3.0)


def test_tabulated_pressure_moment_is_independent_of_lookup_vertical_step() -> None:
    """I1 必须来自原始折线，而不是随 A/T/P 查算步长漂移。"""

    points = [[0.0, 4.0], [2.0, 1.0], [5.0, 0.0], [9.0, 1.5], [12.0, 4.0]]
    coarse = TabulatedSectionGeometry.from_points(points, vertical_step=0.5)
    fine = TabulatedSectionGeometry.from_points(points, vertical_step=0.01)

    assert coarse.pressure_moment(2.75) == pytest.approx(
        fine.pressure_moment(2.75), abs=1.0e-12
    )
    assert math.isfinite(coarse.pressure_moment(2.75))


def test_tabulated_hydraulics_are_invariant_under_large_datum_shift() -> None:
    """A 1e6 m datum must not absorb a real 0.0005 m Profile breakpoint."""

    points = (
        (0.0, 2.0),
        (1.0, 0.0005),
        (2.0, 0.0),
        (3.0, 0.0),
        (4.0, 2.0),
    )
    datum = 1_000_000.0
    base = TabulatedSectionGeometry.from_points(points)
    shifted = TabulatedSectionGeometry.from_points(
        tuple((offset, elevation + datum) for offset, elevation in points)
    )

    for relative_stage in (0.0, 1.0):
        base_stage = relative_stage
        shifted_stage = datum + relative_stage
        assert shifted.area(shifted_stage) == pytest.approx(
            base.area(base_stage),
            abs=1.0e-9,
        )
        assert shifted.top_width(shifted_stage) == pytest.approx(
            base.top_width(base_stage),
            abs=1.0e-9,
        )
        assert shifted.wetted_perimeter(shifted_stage) == pytest.approx(
            base.wetted_perimeter(base_stage),
            abs=1.0e-9,
        )
        assert shifted.pressure_moment(shifted_stage) == pytest.approx(
            base.pressure_moment(base_stage),
            abs=1.0e-8,
        )

    assert base.top_width(base.minimum_stage) == pytest.approx(1.0)
    assert shifted.top_width(shifted.minimum_stage) == pytest.approx(1.0)


def test_pressure_moment_stage_derivative_matches_area_at_table_stage() -> None:
    """用 dI1/dH=A 校验压力矩和面积共用同一断面定义。"""

    geometry = TabulatedSectionGeometry.from_points(
        [[0.0, 2.0], [1.0, 0.0], [3.0, 0.0], [4.0, 2.0]],
        vertical_step=0.05,
    )
    stage = 0.8
    epsilon = 1.0e-6
    derivative = (
        geometry.pressure_moment(stage + epsilon)
        - geometry.pressure_moment(stage - epsilon)
    ) / (2.0 * epsilon)

    assert derivative == pytest.approx(geometry.area(stage), rel=1.0e-8)


@pytest.mark.parametrize("stage", [-0.1, 2.1, math.nan, math.inf, -math.inf])
def test_tabulated_pressure_moment_rejects_out_of_range_or_non_finite_stage(
    stage: float,
) -> None:
    """表格断面干床定义在最低高程，范围外不静默外推。"""

    geometry = TabulatedSectionGeometry.from_points(
        [[0.0, 2.0], [1.0, 0.0], [3.0, 0.0], [4.0, 2.0]]
    )

    assert geometry.pressure_moment(geometry.minimum_stage) == 0.0
    with pytest.raises(HydraulicInputError):
        geometry.pressure_moment(stage)
