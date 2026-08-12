"""支持变床静水保持和水量平衡的一维 Saint-Venant 求解器。

空间离散使用一阶 Rusanov 有限体积通量。界面先执行 hydrostatic
reconstruction，再用左右压力修正与床坡源项保持一致；该方法对矩形、
同宽变床的 lake-at-rest 状态精确平衡。表格化断面采用局部水面宽压力
近似，适用于 Phase 4 软件基准，不代表已经工程率定。
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from model.boundary.conditions import BoundarySignal
from model.core.errors import HydraulicCancelledError, HydraulicInputError, HydraulicStabilityError
from model.core.types import RiverMesh, Section, SectionSeries, SolverConfig
from model.diagnostics.water_balance import evaluate_water_balance
from model.geometry import SectionGeometry

GRAVITY = 9.81
_EPSILON = 1.0e-12


@dataclass(frozen=True)
class RiverSolveResult:
    """保存单河道时序、稳定性诊断和控制体水量平衡。"""

    series: tuple[SectionSeries, ...]
    diagnostics: dict[str, object]


@dataclass(frozen=True)
class _InterfaceFlux:
    """保存界面公共质量通量及对左右控制体分别平衡的动量通量。"""

    mass: float
    momentum_left: float
    momentum_right: float


def _validate_config(config: SolverConfig) -> None:
    """在分配时间推进状态前拒绝无效数值控制。"""

    if config.duration_seconds <= 0:
        raise HydraulicInputError("duration_seconds 必须大于零")
    if config.requested_time_step <= 0:
        raise HydraulicInputError("time_step_seconds 必须大于零")
    if config.output_interval <= 0:
        raise HydraulicInputError("output_interval_seconds 必须大于零")
    if not 0 < config.cfl_number <= 1:
        raise HydraulicInputError("cfl_number 必须位于 (0, 1]")
    if config.minimum_depth <= 0:
        raise HydraulicInputError("minimum_depth 必须大于零")
    if config.maximum_steps <= 0:
        raise HydraulicInputError("maximum_steps 必须大于零")


def _stage(geometry: SectionGeometry, area: float) -> float:
    """在求解器中统一调用面积反函数。"""

    return geometry.stage_from_area(max(area, 0.0))


def _pressure(area: float, geometry: SectionGeometry) -> float:
    """返回静水压力通量 `g I1`；矩形为精确式，非规则断面为局部宽度近似。"""

    if area <= _EPSILON:
        return 0.0
    stage = _stage(geometry, area)
    width = max(geometry.top_width(stage), _EPSILON)
    return GRAVITY * area * area / (2.0 * width)


def _wave_speed(area: float, discharge: float, geometry: SectionGeometry) -> float:
    """返回 `|u| + sqrt(g A/T)` 的局部特征速度（m/s）。"""

    if area <= _EPSILON:
        return 0.0
    stage = _stage(geometry, area)
    top_width = max(geometry.top_width(stage), _EPSILON)
    return abs(discharge / area) + math.sqrt(GRAVITY * area / top_width)


def _physical_flux(
    area: float, discharge: float, geometry: SectionGeometry
) -> tuple[float, float]:
    """返回质量和动量物理通量。"""

    safe_area = max(area, _EPSILON)
    return discharge, discharge * discharge / safe_area + _pressure(area, geometry)


def _reconstructed_area(
    geometry: SectionGeometry, stage: float, interface_bed: float
) -> float:
    """截去界面较高床面以下的静水面积，构造非负界面状态。"""

    if stage <= interface_bed:
        return 0.0
    full = geometry.area(stage)
    clipped_stage = max(interface_bed, geometry.minimum_stage)
    return max(full - geometry.area(clipped_stage), 0.0)


def _hydrostatic_flux(
    left_area: float,
    left_discharge: float,
    left: Section,
    right_area: float,
    right_discharge: float,
    right: Section,
) -> _InterfaceFlux:
    """计算 hydrostatic reconstruction Rusanov 通量及床坡压力修正。"""

    left_stage = _stage(left.geometry, left_area)
    right_stage = _stage(right.geometry, right_area)
    interface_bed = max(left.bed_elevation, right.bed_elevation)
    left_star = _reconstructed_area(left.geometry, left_stage, interface_bed)
    right_star = _reconstructed_area(right.geometry, right_stage, interface_bed)
    left_q_star = left_discharge * left_star / max(left_area, _EPSILON)
    right_q_star = right_discharge * right_star / max(right_area, _EPSILON)
    left_flux = _physical_flux(left_star, left_q_star, left.geometry)
    right_flux = _physical_flux(right_star, right_q_star, right.geometry)
    spectral_radius = max(
        _wave_speed(left_star, left_q_star, left.geometry),
        _wave_speed(right_star, right_q_star, right.geometry),
    )
    mass = 0.5 * (left_flux[0] + right_flux[0]) - 0.5 * spectral_radius * (
        right_star - left_star
    )
    momentum = 0.5 * (left_flux[1] + right_flux[1]) - 0.5 * spectral_radius * (
        right_q_star - left_q_star
    )
    return _InterfaceFlux(
        mass=mass,
        momentum_left=momentum + _pressure(left_area, left.geometry) - _pressure(left_star, left.geometry),
        momentum_right=momentum + _pressure(right_area, right.geometry) - _pressure(right_star, right.geometry),
    )


def _safe_area(geometry: SectionGeometry, stage: float, minimum_depth: float) -> float:
    """把目标水位限制到最低水深并显式拒绝超出表格化断面上限。"""

    target = max(stage, geometry.minimum_stage + minimum_depth)
    return geometry.area(target)


def _apply_boundaries(
    mesh: RiverMesh,
    areas: list[float],
    discharges: list[float],
    time_seconds: float,
    minimum_areas: list[float],
    upstream_flow: BoundarySignal | None,
    downstream_level: BoundarySignal | None,
) -> None:
    """以水位零梯度构造边界状态，并用显式边界信号覆盖相应变量。"""

    upstream_stage = _stage(mesh.sections[1].geometry, areas[1])
    downstream_stage = _stage(mesh.sections[-2].geometry, areas[-2])
    areas[0] = max(
        _safe_area(mesh.sections[0].geometry, upstream_stage, 0.0), minimum_areas[0]
    )
    discharges[0] = discharges[1]
    areas[-1] = max(
        _safe_area(mesh.sections[-1].geometry, downstream_stage, 0.0), minimum_areas[-1]
    )
    discharges[-1] = discharges[-2]
    if upstream_flow is not None:
        discharges[0] = upstream_flow.value_at(time_seconds)
    if downstream_level is not None:
        areas[-1] = max(
            _safe_area(
                mesh.sections[-1].geometry,
                downstream_level.value_at(time_seconds),
                0.0,
            ),
            minimum_areas[-1],
        )


def _initial_state(
    mesh: RiverMesh,
    config: SolverConfig,
    downstream_level: BoundarySignal | None,
) -> tuple[list[float], list[float], float, bool]:
    """构造有限、满足最低水深且在断面查算范围内的初始状态。"""

    requested_stage = config.initial_water_level
    if requested_stage is None and downstream_level is not None:
        requested_stage = downstream_level.value_at(0.0)
    if requested_stage is None:
        requested_stage = max(item.bed_elevation for item in mesh.sections) + 1.0
    safe_stage = max(
        requested_stage,
        max(item.bed_elevation + config.minimum_depth for item in mesh.sections),
    )
    adjusted = not math.isclose(safe_stage, requested_stage)
    try:
        areas = [item.geometry.area(safe_stage) for item in mesh.sections]
    except HydraulicInputError as exc:
        raise HydraulicInputError(
            f"河道 {mesh.river_code} 初始水位 {safe_stage} 超出断面查算范围"
        ) from exc
    discharges = [config.initial_flow for _ in mesh.sections]
    return areas, discharges, safe_stage, adjusted


def _record(
    series: tuple[SectionSeries, ...],
    time_seconds: float,
    areas: list[float],
    discharges: list[float],
) -> None:
    """向所有断面追加一个对齐输出帧。"""

    for item, area, discharge in zip(series, areas, discharges):
        item.append(time_seconds, area, discharge)


def _interior_storage(mesh: RiverMesh, areas: list[float]) -> float:
    """计算实际推进的内部控制体库容（m³），不计边界 ghost 状态。"""

    return sum(
        areas[index]
        * 0.5
        * (mesh.element_lengths[index - 1] + mesh.element_lengths[index])
        for index in range(1, len(areas) - 1)
    )


def solve_river(
    mesh: RiverMesh,
    config: SolverConfig,
    upstream_flow: BoundarySignal | None = None,
    downstream_level: BoundarySignal | None = None,
    cancel_check: object | None = None,
    progress_callback: object | None = None,
) -> RiverSolveResult:
    """在统一时间轴上推进一条至少含三个物理断面的河道。"""

    _validate_config(config)
    if len(mesh.sections) < 3 or len(mesh.element_lengths) != len(mesh.sections) - 1:
        raise HydraulicInputError("可计算河道至少需要三个有序物理断面")

    areas, discharges, initial_stage, initial_stage_adjusted = _initial_state(
        mesh, config, downstream_level
    )
    minimum_areas = [
        item.geometry.area(item.bed_elevation + config.minimum_depth)
        for item in mesh.sections
    ]
    series = tuple(SectionSeries(section=item) for item in mesh.sections)
    _apply_boundaries(
        mesh, areas, discharges, 0.0, minimum_areas, upstream_flow, downstream_level
    )
    _record(series, 0.0, areas, discharges)

    time_seconds = 0.0
    next_output = min(config.output_interval, config.duration_seconds)
    step_count = 0
    reduction_count = 0
    dry_clamp_count = 0
    minimum_used_step = config.requested_time_step
    maximum_cfl = 0.0
    maximum_wave = 0.0
    external_inflow_volume = 0.0
    external_outflow_volume = 0.0
    initial_storage = _interior_storage(mesh, areas)

    while time_seconds < config.duration_seconds - 1.0e-9:
        if callable(cancel_check) and cancel_check():
            raise HydraulicCancelledError("hydraulic task cancelled cooperatively")
        if step_count >= config.maximum_steps:
            raise HydraulicStabilityError(
                f"河道 {mesh.river_code} 超过 maximum_steps={config.maximum_steps}"
            )
        wave_speeds = [
            _wave_speed(area, discharge, section.geometry)
            for area, discharge, section in zip(areas, discharges, mesh.sections)
        ]
        max_wave = max(wave_speeds)
        if not math.isfinite(max_wave) or max_wave <= 0:
            raise HydraulicStabilityError(f"河道 {mesh.river_code} 波速无效")
        maximum_wave = max(maximum_wave, max_wave)
        cfl_step = config.cfl_number * min(mesh.element_lengths) / max_wave
        remaining = config.duration_seconds - time_seconds
        until_output = max(next_output - time_seconds, 0.0)
        candidate = min(config.requested_time_step, cfl_step, remaining)
        if until_output > 1.0e-9:
            candidate = min(candidate, until_output)
        if not math.isfinite(candidate) or candidate <= 1.0e-9:
            raise HydraulicStabilityError(
                f"河道 {mesh.river_code} 需要非有限或可忽略时间步"
            )
        if candidate < config.requested_time_step - 1.0e-9:
            reduction_count += 1
        dt = candidate
        minimum_used_step = min(minimum_used_step, dt)
        maximum_cfl = max(maximum_cfl, max_wave * dt / min(mesh.element_lengths))

        interface_fluxes = [
            _hydrostatic_flux(
                areas[index],
                discharges[index],
                mesh.sections[index],
                areas[index + 1],
                discharges[index + 1],
                mesh.sections[index + 1],
            )
            for index in range(len(mesh.sections) - 1)
        ]
        next_areas = areas.copy()
        next_discharges = discharges.copy()
        for index in range(1, len(mesh.sections) - 1):
            control_length = 0.5 * (
                mesh.element_lengths[index - 1] + mesh.element_lengths[index]
            )
            left_flux = interface_fluxes[index - 1]
            right_flux = interface_fluxes[index]
            next_area = areas[index] - dt / control_length * (
                right_flux.mass - left_flux.mass
            )
            stage = _stage(mesh.sections[index].geometry, areas[index])
            hydraulic_radius = mesh.sections[index].geometry.hydraulic_radius(stage)
            friction_slope = (
                mesh.sections[index].roughness**2
                * discharges[index]
                * abs(discharges[index])
                / max(areas[index] ** 2 * hydraulic_radius ** (4.0 / 3.0), _EPSILON)
            )
            next_discharge = discharges[index] - dt / control_length * (
                right_flux.momentum_left - left_flux.momentum_right
            ) - dt * GRAVITY * areas[index] * friction_slope
            if not math.isfinite(next_area) or not math.isfinite(next_discharge):
                raise HydraulicStabilityError(
                    f"河道 {mesh.river_code} 产生非有限状态"
                )
            if next_area < minimum_areas[index]:
                next_area = minimum_areas[index]
                next_discharge = 0.0
                dry_clamp_count += 1
            next_areas[index] = next_area
            next_discharges[index] = next_discharge

        left_mass = interface_fluxes[0].mass
        right_mass = interface_fluxes[-1].mass
        external_inflow_volume += max(left_mass, 0.0) * dt + max(-right_mass, 0.0) * dt
        external_outflow_volume += max(-left_mass, 0.0) * dt + max(right_mass, 0.0) * dt
        time_seconds += dt
        step_count += 1
        if callable(progress_callback) and step_count % 10 == 0:
            progress_callback(time_seconds, maximum_cfl)
        areas = next_areas
        discharges = next_discharges
        _apply_boundaries(
            mesh,
            areas,
            discharges,
            time_seconds,
            minimum_areas,
            upstream_flow,
            downstream_level,
        )
        if time_seconds >= next_output - 1.0e-8:
            _record(series, time_seconds, areas, discharges)
            next_output = min(next_output + config.output_interval, config.duration_seconds)

    if series[0].time[-1] < config.duration_seconds - 1.0e-8:
        _record(series, config.duration_seconds, areas, discharges)

    water_balance = evaluate_water_balance(
        initial_storage=initial_storage,
        final_storage=_interior_storage(mesh, areas),
        external_inflow_volume=external_inflow_volume,
        external_outflow_volume=external_outflow_volume,
    )
    return RiverSolveResult(
        series=series,
        diagnostics={
            "step_count": step_count,
            "requested_time_step": config.requested_time_step,
            "minimum_used_time_step": minimum_used_step,
            "time_step_reduction_count": reduction_count,
            "maximum_cfl": maximum_cfl,
            "maximum_wave_speed": maximum_wave,
            "dry_clamp_count": dry_clamp_count,
            "initial_water_level": initial_stage,
            "initial_water_level_adjusted": initial_stage_adjusted,
            "has_upstream_flow_boundary": upstream_flow is not None,
            "has_downstream_level_boundary": downstream_level is not None,
            "geometry_types": sorted(
                {item.geometry.geometry_type for item in mesh.sections}
            ),
            "water_balance": water_balance.to_dict(),
        },
    )
