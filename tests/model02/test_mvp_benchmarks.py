"""HYDRO-MODEL-02-B 五个分级合成 Benchmark。

Case 001 是变床矩形河道的严格静水科学门；Case 002 同时
保留可执行的 MVP 行为回归与不得误报通过的科学候选门。
Case 003--005 只验证 MVP 传播、结构源汇和质量记账行为，
不代表外部模型精度、强动量耦合或泵站 Q-H 工作点验收。
"""

from __future__ import annotations

import math

import pytest

from model.geometry import RectangularSectionGeometry, TabulatedSectionGeometry
from model.solver.finite_volume import (
    GRAVITY,
    BoundaryPair,
    BoundarySeries,
    DownstreamStageBoundary,
    FiniteVolumeCell,
    FiniteVolumeMesh,
    FixedGate,
    HydraulicState,
    OnOffPump,
    SingleBranchConfig,
    SingleBranchResult,
    UpstreamDischargeBoundary,
    solve_single_branch,
)


def _boundaries(
    *,
    times: tuple[float, ...],
    discharges: tuple[float, ...],
    stages: tuple[float, ...],
) -> BoundaryPair:
    """创建覆盖完整计算时域、禁止外推的 Q/H 边界。"""

    return BoundaryPair(
        upstream=UpstreamDischargeBoundary(
            BoundarySeries(times, discharges, "discharge")
        ),
        downstream=DownstreamStageBoundary(BoundarySeries(times, stages, "stage")),
    )


def _rectangular_mesh(
    beds: list[float],
    *,
    width: float,
    dx: float,
    manning_n: float,
) -> FiniteVolumeMesh:
    """构造一条断面等宽、床面高程可变的单河网格。"""

    return FiniteVolumeMesh(
        tuple(
            FiniteVolumeCell(
                cell_id=f"cell-{index:02d}",
                dx=dx,
                section_id=f"section-{index:02d}",
                bed_elevation=bed,
                geometry=RectangularSectionGeometry(width, bed),
                manning_n=manning_n,
            )
            for index, bed in enumerate(beds)
        )
    )


def _initial_state(
    mesh: FiniteVolumeMesh,
    *,
    stages: tuple[float, ...],
    discharges: tuple[float, ...],
    dry_depth: float = 1.0e-3,
) -> HydraulicState:
    """从逐 cell 绝对水位和流量创建守恒初态。"""

    return HydraulicState.from_conserved(
        mesh=mesh,
        time=0.0,
        area=tuple(
            cell.geometry.area(stage) for cell, stage in zip(mesh.cells, stages)
        ),
        discharge=discharges,
        dry_depth=dry_depth,
    )


def _assert_common_quality(
    result: SingleBranchResult,
    mesh: FiniteVolumeMesh,
    config: SingleBranchConfig,
    *,
    balance_tolerance: float,
    expected_retries: int = 0,
) -> None:
    """统一检查时间、有限性、正性、CFL 和动态水量账。"""

    output_times = [state.time for state in result.states]
    assert output_times[0] == pytest.approx(0.0)
    assert output_times[-1] == pytest.approx(config.end_time)
    assert all(right > left for left, right in zip(output_times, output_times[1:]))

    step_times = [step.state.time for step in result.steps]
    assert step_times
    assert step_times[-1] == pytest.approx(config.end_time)
    assert all(right > left for left, right in zip(step_times, step_times[1:]))
    assert all(math.isfinite(step.dt) and step.dt > 0.0 for step in result.steps)

    accepted_states = (*result.states, *(step.state for step in result.steps))
    for state in accepted_states:
        assert len(state.area) == len(mesh.cells)
        for area, discharge, depth, velocity, wet in zip(
            state.area,
            state.discharge,
            state.water_depth,
            state.velocity,
            state.wet_mask,
        ):
            assert all(math.isfinite(value) for value in (area, discharge, depth, velocity))
            assert area >= 0.0
            assert depth >= -1.0e-12
            if not wet:
                assert abs(discharge) <= 1.0e-12

    diagnostics = result.diagnostics
    assert diagnostics.maximum_cfl <= config.cfl_number + 1.0e-12
    assert math.isfinite(diagnostics.minimum_dt) and diagnostics.minimum_dt > 0.0
    assert diagnostics.retry_count == expected_retries
    assert diagnostics.step_count == len(result.steps)
    assert result.steps[-1].state.diagnostics.stage_count == 2 * len(result.steps)
    assert diagnostics.water_balance_status == "pass"
    assert diagnostics.relative_water_balance_error <= balance_tolerance

    storage_change = diagnostics.final_storage - diagnostics.initial_storage
    expected_change = (
        diagnostics.upstream_boundary_volume
        - diagnostics.downstream_boundary_volume
        - diagnostics.pump_outflow_volume
    )
    residual = storage_change - expected_change
    scale = max(
        abs(diagnostics.initial_storage),
        abs(storage_change),
        abs(diagnostics.upstream_boundary_volume)
        + abs(diagnostics.downstream_boundary_volume)
        + abs(diagnostics.pump_outflow_volume),
        1.0,
    )
    assert diagnostics.water_balance_residual == pytest.approx(residual, abs=1.0e-10)
    assert diagnostics.relative_water_balance_error == pytest.approx(
        abs(residual) / scale,
        abs=1.0e-15,
    )


def test_case001_scientific_lake_at_rest_over_variable_bed() -> None:
    """同宽矩形变床河道必须严格保持水平自由水面。"""

    beds = [
        0.0,
        0.1,
        0.25,
        0.4,
        0.3,
        0.15,
        0.05,
        0.2,
        0.35,
        0.25,
        0.1,
        0.0,
        0.15,
        0.3,
        0.2,
        0.05,
        0.0,
        0.1,
        0.2,
        0.0,
    ]
    stage = 2.0
    mesh = _rectangular_mesh(beds, width=10.0, dx=50.0, manning_n=0.0)
    initial = _initial_state(
        mesh,
        stages=(stage,) * len(mesh.cells),
        discharges=(0.0,) * len(mesh.cells),
    )
    config = SingleBranchConfig(
        end_time=600.0,
        maximum_dt=10.0,
        output_interval=60.0,
        cfl_number=0.7,
    )
    result = solve_single_branch(
        mesh=mesh,
        initial_state=initial,
        boundaries=_boundaries(
            times=(0.0, config.end_time),
            discharges=(0.0, 0.0),
            stages=(stage, stage),
        ),
        config=config,
    )

    _assert_common_quality(result, mesh, config, balance_tolerance=1.0e-10)
    maximum_velocity = max(
        abs(velocity) for state in result.states for velocity in state.velocity
    )
    maximum_stage_drift = max(
        abs(cell.bed_elevation + depth - stage)
        for state in result.states
        for cell, depth in zip(mesh.cells, state.water_depth)
    )
    assert maximum_velocity <= 1.0e-8
    assert maximum_stage_drift <= 1.0e-8


@pytest.fixture(scope="module")
def _case002_manning_run() -> tuple[
    SingleBranchResult,
    FiniteVolumeMesh,
    SingleBranchConfig,
    float,
    float,
]:
    """运行一次 Q=50 m³/s 的矩形 Manning 正常水深案例。"""

    width = 10.0
    normal_depth = 2.0
    discharge = 50.0
    manning_n = 0.03
    dx = 50.0
    cell_count = 40
    area = width * normal_depth
    hydraulic_radius = area / (width + 2.0 * normal_depth)
    bed_slope = (
        discharge
        * manning_n
        / (area * hydraulic_radius ** (2.0 / 3.0))
    ) ** 2
    beds = [10.0 - bed_slope * (index + 0.5) * dx for index in range(cell_count)]
    mesh = _rectangular_mesh(
        beds,
        width=width,
        dx=dx,
        manning_n=manning_n,
    )
    initial = _initial_state(
        mesh,
        stages=tuple(bed + normal_depth for bed in beds),
        discharges=(discharge,) * cell_count,
    )
    config = SingleBranchConfig(
        end_time=600.0,
        maximum_dt=2.0,
        output_interval=60.0,
        cfl_number=0.5,
    )
    result = solve_single_branch(
        mesh=mesh,
        initial_state=initial,
        boundaries=_boundaries(
            times=(0.0, config.end_time),
            discharges=(discharge, discharge),
            stages=(beds[-1] + normal_depth,) * 2,
        ),
        config=config,
    )
    return result, mesh, config, discharge, normal_depth


def _case002_errors(
    run: tuple[
        SingleBranchResult,
        FiniteVolumeMesh,
        SingleBranchConfig,
        float,
        float,
    ],
) -> tuple[float, float, float]:
    """返回排除两端边界 cell 后的 Q 和水深误差。"""

    result, mesh, _, reference_flow, reference_depth = run
    final = result.states[-1]
    interior = range(2, len(mesh.cells) - 2)
    relative_flow_error = max(
        abs(final.discharge[index] - reference_flow) / reference_flow
        for index in interior
    )
    absolute_depth_error = max(
        abs(final.water_depth[index] - reference_depth) for index in interior
    )
    relative_depth_error = absolute_depth_error / reference_depth
    return relative_flow_error, absolute_depth_error, relative_depth_error


def test_case002_mvp_behavior_manning_flow_remains_bounded(
    _case002_manning_run: tuple[
        SingleBranchResult,
        FiniteVolumeMesh,
        SingleBranchConfig,
        float,
        float,
    ],
) -> None:
    """当前 MVP 在中等时域内不得偏离 Manning 初态到失稳。"""

    result, mesh, config, _, _ = _case002_manning_run
    _assert_common_quality(result, mesh, config, balance_tolerance=1.0e-6)
    flow_error, depth_error, _ = _case002_errors(_case002_manning_run)
    assert flow_error < 0.05
    assert depth_error < 0.1
    assert all(value > 0.0 for value in result.states[-1].discharge[2:-2])


@pytest.mark.xfail(
    strict=True,
    reason=(
        "MVP subcritical boundary closure and per-stage friction are not yet the "
        "frozen characteristic/IMEX scientific scheme; current Q=50 case remains "
        "outside the 0.1% Manning candidate threshold"
    ),
)
def test_case002_scientific_candidate_manning_normal_depth(
    _case002_manning_run: tuple[
        SingleBranchResult,
        FiniteVolumeMesh,
        SingleBranchConfig,
        float,
        float,
    ],
) -> None:
    """保留候选科学门，不把 5% 行为容差宣称为正常水深验证。"""

    result, _, _, _, _ = _case002_manning_run
    flow_error, depth_error, relative_depth_error = _case002_errors(
        _case002_manning_run
    )
    assert flow_error <= 1.0e-3
    assert depth_error <= 0.01
    assert relative_depth_error <= 1.0e-3
    assert result.diagnostics.relative_water_balance_error <= 1.0e-6


def test_case003_mvp_behavior_flood_peak_propagates_downstream() -> None:
    """无解析参考时只验证洪峰的传播因果、有限性与水量。"""

    cell_count = 40
    geometry = TabulatedSectionGeometry.from_points(
        [[0.0, 4.0], [5.0, 0.0], [15.0, 0.0], [20.0, 4.0]]
    )
    mesh = FiniteVolumeMesh(
        tuple(
            FiniteVolumeCell(
                cell_id=f"flood-{index:02d}",
                dx=50.0,
                section_id=f"flood-section-{index:02d}",
                bed_elevation=0.0,
                geometry=geometry,
                manning_n=0.0,
            )
            for index in range(cell_count)
        )
    )
    initial_stage = 2.0
    initial_flow = 20.0
    initial = _initial_state(
        mesh,
        stages=(initial_stage,) * cell_count,
        discharges=(initial_flow,) * cell_count,
    )
    boundary_times = (0.0, 300.0, 600.0, 900.0, 1800.0)
    config = SingleBranchConfig(
        end_time=boundary_times[-1],
        maximum_dt=2.0,
        output_interval=30.0,
        cfl_number=0.5,
    )
    result = solve_single_branch(
        mesh=mesh,
        initial_state=initial,
        boundaries=_boundaries(
            times=boundary_times,
            discharges=(20.0, 20.0, 60.0, 20.0, 20.0),
            stages=(initial_stage,) * len(boundary_times),
        ),
        config=config,
    )

    _assert_common_quality(result, mesh, config, balance_tolerance=1.0e-3)
    step_times = [step.state.time for step in result.steps]
    for breakpoint in boundary_times[1:-1]:
        assert any(math.isclose(time, breakpoint, abs_tol=1.0e-9) for time in step_times)

    near_index = 9
    far_index = 29
    response_threshold = 22.0

    def first_response(index: int) -> float:
        return next(
            state.time
            for state in result.states
            if state.discharge[index] > response_threshold
        )

    def peak_time(index: int) -> float:
        return max(result.states, key=lambda state: state.discharge[index]).time

    assert max(state.discharge[near_index] for state in result.states) > response_threshold
    assert max(state.discharge[far_index] for state in result.states) > response_threshold
    assert first_response(near_index) < first_response(far_index)
    assert peak_time(near_index) <= peak_time(far_index)
    assert max(state.water_depth[near_index] for state in result.states) > initial_stage
    assert max(state.water_depth[far_index] for state in result.states) > initial_stage


def test_case004_mvp_behavior_fixed_gate_transfers_internal_mass() -> None:
    """固定开度 Gate 必须按当前水头计算流量并保持全域质量。"""

    cell_count = 20
    mesh = _rectangular_mesh(
        [0.0] * cell_count,
        width=10.0,
        dx=50.0,
        manning_n=0.0,
    )
    initial = _initial_state(
        mesh,
        stages=(2.0,) * 10 + (1.5,) * 10,
        discharges=(0.0,) * cell_count,
    )
    config = SingleBranchConfig(
        end_time=60.0,
        maximum_dt=2.0,
        output_interval=10.0,
        cfl_number=0.5,
    )
    boundaries = _boundaries(
        times=(0.0, config.end_time),
        discharges=(0.0, 0.0),
        stages=(1.5, 1.5),
    )
    open_gate = FixedGate(
        gate_id="gate-1",
        face_index=9,
        opening=0.5,
        width=2.0,
        height=1.0,
        discharge_coefficient=0.62,
    )
    closed_gate = FixedGate(
        gate_id="gate-1",
        face_index=9,
        opening=0.0,
        width=2.0,
        height=1.0,
        discharge_coefficient=0.62,
    )
    opened = solve_single_branch(
        mesh=mesh,
        initial_state=initial,
        boundaries=boundaries,
        config=config,
        gates=(open_gate,),
    )
    closed = solve_single_branch(
        mesh=mesh,
        initial_state=initial,
        boundaries=boundaries,
        config=config,
        gates=(closed_gate,),
    )

    _assert_common_quality(opened, mesh, config, balance_tolerance=1.0e-6)
    _assert_common_quality(closed, mesh, config, balance_tolerance=1.0e-6)
    expected_initial_flow = 0.62 * 2.0 * 0.5 * math.sqrt(2.0 * GRAVITY * 0.5)
    first_stage_flow = opened.steps[0].budget.gate_stage_flows[0]
    assert first_stage_flow.flow == pytest.approx(expected_initial_flow, rel=1.0e-12)
    assert first_stage_flow.state["opening"] == pytest.approx(0.5)

    open_stage_flows = [
        flow
        for step in opened.steps
        for flow in step.budget.gate_stage_flows
    ]
    assert len(open_stage_flows) == 2 * len(opened.steps)
    assert all(math.isfinite(flow.flow) and flow.flow >= 0.0 for flow in open_stage_flows)
    open_transfer = sum(
        volume
        for step in opened.steps
        for structure_id, volume in step.budget.gate_transfer_volume
        if structure_id == "gate-1"
    )
    closed_transfer = sum(
        volume
        for step in closed.steps
        for structure_id, volume in step.budget.gate_transfer_volume
        if structure_id == "gate-1"
    )
    assert open_transfer > 0.0
    assert closed_transfer == pytest.approx(0.0, abs=1.0e-12)
    assert opened.states[-1].area[9] < closed.states[-1].area[9]
    assert opened.states[-1].area[10] > closed.states[-1].area[10]
    assert (
        "structure_momentum_closure_mass_only_mvp"
        in opened.diagnostics.diagnostic_flags
    )


def test_case005_mvp_behavior_on_off_pump_is_external_sink() -> None:
    """固定 ON/OFF Pump 必须按设计流量外排并进入动态水量账。"""

    cell_count = 20
    mesh = _rectangular_mesh(
        [0.0] * cell_count,
        width=10.0,
        dx=50.0,
        manning_n=0.0,
    )
    initial = _initial_state(
        mesh,
        stages=(2.0,) * cell_count,
        discharges=(0.0,) * cell_count,
    )
    config = SingleBranchConfig(
        end_time=300.0,
        maximum_dt=2.0,
        output_interval=30.0,
        cfl_number=0.5,
    )
    boundaries = _boundaries(
        times=(0.0, config.end_time),
        discharges=(0.0, 0.0),
        stages=(2.0, 2.0),
    )
    design_flow = 0.5
    enabled = solve_single_branch(
        mesh=mesh,
        initial_state=initial,
        boundaries=boundaries,
        config=config,
        pumps=(OnOffPump("pump-1", 9, design_flow, True),),
    )
    disabled = solve_single_branch(
        mesh=mesh,
        initial_state=initial,
        boundaries=boundaries,
        config=config,
        pumps=(OnOffPump("pump-1", 9, design_flow, False),),
    )

    _assert_common_quality(enabled, mesh, config, balance_tolerance=1.0e-6)
    _assert_common_quality(disabled, mesh, config, balance_tolerance=1.0e-6)
    assert enabled.diagnostics.pump_outflow_volume == pytest.approx(
        design_flow * config.end_time,
        abs=1.0e-10,
    )
    assert disabled.diagnostics.pump_outflow_volume == pytest.approx(0.0, abs=1.0e-12)

    enabled_stage_flows = [
        flow
        for step in enabled.steps
        for flow in step.budget.pump_stage_flows
    ]
    disabled_stage_flows = [
        flow
        for step in disabled.steps
        for flow in step.budget.pump_stage_flows
    ]
    assert all(flow.flow == pytest.approx(design_flow) for flow in enabled_stage_flows)
    assert all(flow.state["enabled"] is True for flow in enabled_stage_flows)
    assert all(flow.flow == pytest.approx(0.0) for flow in disabled_stage_flows)
    assert all(flow.state["enabled"] is False for flow in disabled_stage_flows)
    assert min(state.water_depth[9] for state in enabled.states) < min(
        state.water_depth[9] for state in disabled.states
    )
