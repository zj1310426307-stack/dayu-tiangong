"""Phase 4 闸门流态、泵站约束、质量转输和能耗定量测试。"""

import pytest

from model.structure.gate import GateControlState, constrain_gate_opening, evaluate_gate
from model.structure.pump import PumpControlState, evaluate_pump, interpolate_curve


def test_gate_closed_flow_zero() -> None:
    """关闭闸门的内部通量必须为零。"""

    result = evaluate_gate(
        width=5.0, requested_opening=0.0, actual_opening=0.0,
        upstream_level=12.0, downstream_level=10.0, crest_elevation=9.0,
    )
    assert result.flow == 0.0
    assert result.regime == "closed"


def test_gate_free_orifice() -> None:
    """低尾水条件必须使用自由孔流公式。"""

    result = evaluate_gate(
        width=4.0, requested_opening=1.0, actual_opening=1.0,
        upstream_level=12.0, downstream_level=9.5, crest_elevation=9.0,
        discharge_coefficient=0.62,
    )
    assert result.regime == "free_orifice"
    assert result.flow == pytest.approx(0.62 * 4.0 * (2 * 9.81 * 3.0) ** 0.5)


def test_gate_submerged_orifice() -> None:
    """高尾水条件必须使用上下游水头差的淹没孔流。"""

    result = evaluate_gate(
        width=4.0, requested_opening=1.0, actual_opening=1.0,
        upstream_level=12.0, downstream_level=11.5, crest_elevation=9.0,
    )
    assert result.regime == "submerged_orifice"
    assert result.flow == pytest.approx(0.62 * 4.0 * (2 * 9.81 * 0.5) ** 0.5)


def test_gate_weir_overflow() -> None:
    """上游水头低于开度时使用闸顶堰流。"""

    result = evaluate_gate(
        width=4.0, requested_opening=2.0, actual_opening=2.0,
        upstream_level=10.0, downstream_level=9.0, crest_elevation=9.0,
    )
    assert result.regime == "weir_overflow"
    assert result.flow == pytest.approx(1.7 * 4.0)


def test_gate_reverse_flow_policy() -> None:
    """默认拒绝倒流，显式允许后应返回负向流量。"""

    blocked = evaluate_gate(
        width=4.0, requested_opening=1.0, actual_opening=1.0,
        upstream_level=10.0, downstream_level=12.0, crest_elevation=9.0,
    )
    allowed = evaluate_gate(
        width=4.0, requested_opening=1.0, actual_opening=1.0,
        upstream_level=10.0, downstream_level=12.0, crest_elevation=9.0,
        allow_reverse_flow=True,
    )
    assert blocked.flow == 0.0
    assert allowed.flow < 0.0


def test_gate_opening_rate_limit() -> None:
    """开度变化不得超过速率乘时间步。"""

    actual, flags = constrain_gate_opening(
        2.0, previous_opening=0.5, elapsed_seconds=10.0,
        minimum_opening=0.1, maximum_opening=3.0, opening_rate_limit=0.05,
        minimum_hold_seconds=0.0, time_since_change=100.0, availability="online",
    )
    assert actual == pytest.approx(1.0)
    assert "opening_rate_limited" in flags


def test_gate_initial_state_is_not_in_hold_period() -> None:
    """t=0 初始指令不得被错误地视为上一动作后的保持期。"""

    state = GateControlState()
    actual, flags = constrain_gate_opening(
        1.0, previous_opening=state.opening, elapsed_seconds=0.0,
        minimum_opening=0.0, maximum_opening=2.0, opening_rate_limit=0.05,
        minimum_hold_seconds=120.0, time_since_change=0.0 - state.last_change_time,
        availability="online",
    )
    assert actual == pytest.approx(1.0)
    assert "minimum_hold_rejected" not in flags


def test_pump_curve_interpolation() -> None:
    """曲线在相邻点之间执行分段线性插值。"""

    assert interpolate_curve([[0.0, 0.6], [0.5, 0.8], [1.0, 0.7]], 0.25) == pytest.approx(0.7)


def test_pump_curve_forbids_extrapolation() -> None:
    """Q-H/Q-η 查询范围外必须显式失败，禁止静默外推。"""

    with pytest.raises(ValueError, match="超出范围"):
        interpolate_curve([[0.0, 6.0], [10.0, 5.0]], 11.0)


def _pump(**overrides):
    """执行一个默认在线单泵时间步。"""

    arguments = dict(
        requested_units=1, target_flow=None, design_flow_per_unit=10.0, head=5.0,
        elapsed_seconds=60.0, state=PumpControlState(), availability="online",
        minimum_running_units=1, maximum_running_units=2, minimum_run_seconds=0.0,
        minimum_stop_seconds=0.0, maximum_starts_per_run=3,
        minimum_operating_head=1.0, maximum_operating_head=8.0,
        efficiency_curve=[[0.0, 0.7], [1.0, 0.8]],
    )
    arguments.update(overrides)
    return evaluate_pump(**arguments)


def test_pump_head_out_of_range() -> None:
    """超过运行扬程范围必须停机并审计。"""

    result = _pump(head=12.0)
    assert result.flow == 0.0
    assert "head_out_of_range" in result.constraint_flags


def test_pump_minimum_run_time() -> None:
    """未满足最短运行时间时停机命令被拒绝。"""

    state = PumpControlState(running_units=1, runtime_seconds=30.0)
    result = _pump(requested_units=0, state=state, minimum_run_seconds=120.0)
    assert result.actual_units == 1
    assert "minimum_run_rejected" in result.constraint_flags


def test_pump_minimum_stop_time() -> None:
    """未满足最短停机时间时启动命令被拒绝。"""

    state = PumpControlState(stop_seconds=30.0)
    result = _pump(state=state, minimum_stop_seconds=120.0)
    assert result.actual_units == 0
    assert "minimum_stop_rejected" in result.constraint_flags


def test_pump_maximum_starts() -> None:
    """达到最大启停次数后不得再次启动。"""

    state = PumpControlState(stop_seconds=1000.0, starts=3)
    result = _pump(state=state, maximum_starts_per_run=3)
    assert result.actual_units == 0
    assert "maximum_starts_rejected" in result.constraint_flags


def test_pump_mass_transfer_and_energy() -> None:
    """单泵流量、功率和 60 秒能耗必须量纲一致。"""

    result = _pump()
    expected_power = 1000.0 * 9.81 * 10.0 * 5.0 / 0.8 / 1000.0
    assert result.flow == pytest.approx(10.0)
    assert result.power_kw == pytest.approx(expected_power)
    assert result.energy_kwh == pytest.approx(expected_power / 60.0)


def test_pump_insufficient_intake_depth() -> None:
    """进水深度低于安全下限时必须停泵并给出审计原因。"""

    result = _pump(intake_depth=0.02, minimum_intake_depth=0.05)
    assert result.flow == 0.0
    assert "insufficient_intake_depth" in result.constraint_flags
