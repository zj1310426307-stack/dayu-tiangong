"""共同节点水位与连续性约束下的同步河网路由求解。

本实现将有向 `river_segment` 作为水量传递边，按统一输出/调度时刻计算。
节点严格满足质量连续，汇流直接相加，分流按下游河段输水权重分配；节点
水位由下游定水位和 Manning 沿程损失反向计算。它没有完整求解节点动量/
能量兼容，属于 Phase 4 的明确最低耦合实现。
"""

from __future__ import annotations

import math
from collections import defaultdict, deque
from collections.abc import Mapping
from typing import Any

from model.boundary.conditions import BoundarySet
from model.core.errors import HydraulicCancelledError, HydraulicInputError, HydraulicStabilityError
from model.core.types import SectionSeries, SolverConfig
from model.diagnostics import evaluate_water_balance
from model.network.types import NetworkEdge, NetworkMesh, NetworkSolveResult
from model.control.constraints import validate_control_target
from model.control.policy import CompositeControlPolicy, HydraulicObservation
from model.control.rules import ThresholdRule, ThresholdRulePolicy
from model.control.schedule import ManualSchedulePolicy, ScheduledAction
from model.structure.gate import GateControlState, constrain_gate_opening, evaluate_gate
from model.structure.pump import PumpControlState, evaluate_pump, interpolate_curve


def _topological_order(network: NetworkMesh) -> tuple[int, ...]:
    """返回稳定的 DAG 节点顺序，并拒绝当前显式路由不支持的有向环。"""

    incoming_count: dict[int, int] = {item.node_id: 0 for item in network.nodes}
    downstream: dict[int, list[int]] = defaultdict(list)
    for edge in network.edges:
        incoming_count[edge.downstream_node_id] += 1
        downstream[edge.upstream_node_id].append(edge.downstream_node_id)
    queue = deque(sorted(node for node, count in incoming_count.items() if count == 0))
    order: list[int] = []
    while queue:
        node = queue.popleft()
        order.append(node)
        for target in sorted(downstream.get(node, [])):
            incoming_count[target] -= 1
            if incoming_count[target] == 0:
                queue.append(target)
    if len(order) != len(network.nodes):
        raise HydraulicInputError("Phase 4 显式河网路由暂不支持有向环")
    return tuple(order)


def _edge_weights(network: NetworkMesh) -> dict[int, float]:
    """以长度倒数作为分流输水权重，避免任意按列表顺序分配。"""

    return {edge.segment_id: 1.0 / edge.length for edge in network.edges}


def _route_flows(
    network: NetworkMesh,
    order: tuple[int, ...],
    boundaries: BoundarySet,
    time_seconds: float,
    node_sources: Mapping[int, float] | None = None,
    edge_overrides: Mapping[int, float] | None = None,
) -> tuple[dict[int, float], list[dict[str, float | int]]]:
    """沿 DAG 传播外边界和源汇流量，严格保持每个内部节点连续。"""

    incoming_edges: dict[int, list[NetworkEdge]] = defaultdict(list)
    outgoing_edges: dict[int, list[NetworkEdge]] = defaultdict(list)
    for edge in network.edges:
        incoming_edges[edge.downstream_node_id].append(edge)
        outgoing_edges[edge.upstream_node_id].append(edge)
    weights = _edge_weights(network)
    flows: dict[int, float] = {}
    node_rows: list[dict[str, float | int]] = []
    sources = dict(node_sources or {})
    overrides = dict(edge_overrides or {})
    for node_id in order:
        inflow = sum(flows[edge.segment_id] for edge in incoming_edges[node_id])
        signal = boundaries.by_node.get(node_id)
        if signal is not None and signal.boundary_type == "upstream_flow":
            inflow += signal.value_at(time_seconds)
        source_sink = float(sources.get(node_id, 0.0))
        available = inflow + source_sink
        outgoing = outgoing_edges[node_id]
        if outgoing:
            fixed = [edge for edge in outgoing if edge.segment_id in overrides]
            variable = [edge for edge in outgoing if edge.segment_id not in overrides]
            fixed_total = 0.0
            for edge in fixed:
                applied = math.copysign(
                    min(abs(overrides[edge.segment_id]), max(abs(available), 0.0)),
                    overrides[edge.segment_id],
                )
                flows[edge.segment_id] = applied
                fixed_total += applied
            remaining = available - fixed_total
            denominator = sum(weights[edge.segment_id] for edge in variable)
            for edge in variable:
                flows[edge.segment_id] = (
                    remaining * weights[edge.segment_id] / denominator
                    if denominator > 0
                    else 0.0
                )
            outflow = sum(flows[edge.segment_id] for edge in outgoing)
        else:
            outflow = available
        residual = inflow + source_sink - outflow
        node_rows.append(
            {
                "node_id": node_id,
                "inflow": inflow,
                "outflow": outflow,
                "source_sink": source_sink,
                "balance_residual": residual,
            }
        )
    return flows, node_rows


def _representative_hydraulics(network: NetworkMesh) -> dict[int, tuple[float, float, float]]:
    """按河道提取糙率、代表面积和水力半径，用于 Manning 水面损失。"""

    result: dict[int, tuple[float, float, float]] = {}
    for branch in network.branches:
        section = branch.mesh.sections[len(branch.mesh.sections) // 2]
        stage = section.bed_elevation + 1.0
        area = section.geometry.area(stage)
        radius = section.geometry.hydraulic_radius(stage)
        result[branch.mesh.river_id] = (section.roughness, area, radius)
    return result


def _node_levels(
    network: NetworkMesh,
    order: tuple[int, ...],
    boundaries: BoundarySet,
    flows: Mapping[int, float],
    time_seconds: float,
) -> dict[int, float]:
    """由下游定水位和 Manning 损失反推所有节点的共同水位。"""

    outgoing: dict[int, list[NetworkEdge]] = defaultdict(list)
    for edge in network.edges:
        outgoing[edge.upstream_node_id].append(edge)
    hydraulics = _representative_hydraulics(network)
    levels: dict[int, float] = {}
    for node_id in reversed(order):
        signal = boundaries.by_node.get(node_id)
        if signal is not None and signal.boundary_type == "downstream_water_level":
            levels[node_id] = signal.value_at(time_seconds)
            continue
        candidates: list[float] = []
        for edge in outgoing.get(node_id, []):
            if edge.downstream_node_id not in levels:
                continue
            roughness, area, radius = hydraulics[edge.river_id]
            slope = (
                roughness**2 * flows[edge.segment_id] * abs(flows[edge.segment_id])
                / max(area**2 * radius ** (4.0 / 3.0), 1.0e-12)
            )
            candidates.append(levels[edge.downstream_node_id] + slope * edge.length)
        if candidates:
            levels[node_id] = max(candidates)
        else:
            levels[node_id] = max(
                section.bed_elevation + 1.0
                for branch in network.branches
                for section in branch.mesh.sections
            )
    return levels


def _build_control_policy(plan: Mapping[str, Any] | None) -> tuple[CompositeControlPolicy, tuple[float, ...]]:
    """把冻结计划 JSON 转换为纯领域策略，并返回必须对齐的动作时刻。"""

    if not isinstance(plan, Mapping):
        return CompositeControlPolicy(()), ()
    actions = tuple(
        ScheduledAction(
            id=int(item["id"]) if item.get("id") is not None else None,
            time_seconds=float(item["time_seconds"]),
            structure_type=str(item["structure_type"]),
            structure_id=int(item.get("gate_id") or item.get("pump_id") or item["structure_id"]),
            command_type=str(item["command_type"]),
            target_value=float(item["target_value"]),
            interpolation=str(item.get("interpolation", "step")),
            priority=int(item.get("priority", 0)),
        )
        for item in plan.get("actions", [])
    )
    rules = tuple(
        ThresholdRule(
            id=int(item["id"]) if item.get("id") is not None else None,
            name=str(item["name"]),
            enabled=bool(item.get("enabled", True)),
            observation_type=str(item["observation_type"]),
            observation_object_id=(
                int(item["observation_object_id"])
                if item.get("observation_object_id") is not None
                else None
            ),
            operator=str(item["operator"]),
            threshold=float(item["threshold"]),
            hysteresis=float(item.get("hysteresis", 0.0)),
            minimum_hold_seconds=float(item.get("minimum_hold_seconds", 0.0)),
            cooldown_seconds=float(item.get("cooldown_seconds", 0.0)),
            action_template=dict(item["action_template"]),
            priority=int(item.get("priority", 0)),
        )
        for item in plan.get("rules", [])
    )
    schedule = ManualSchedulePolicy(actions)
    policies: list[Any] = [schedule]
    if rules:
        policies.append(ThresholdRulePolicy(rules))
    return CompositeControlPolicy(tuple(policies)), schedule.event_times


def _structure_controls(
    snapshot: Mapping[str, Any],
    policy: CompositeControlPolicy,
    time_seconds: float,
    elapsed_seconds: float,
    levels: Mapping[int, float],
    gate_states: dict[int, GateControlState],
    pump_states: dict[int, PumpControlState],
    node_bed_levels: Mapping[int, float],
    minimum_depth: float,
    section_observations: Mapping[int, float],
) -> tuple[dict[int, float], dict[int, float], list[dict[str, Any]], list[dict[str, Any]]]:
    """计算闸门边通量和泵站节点源汇，并记录每条命令的实际执行结果。"""

    observations: dict[tuple[str, int | None], float] = {
        ("node_water_level", node_id): level for node_id, level in levels.items()
    }
    observations.update(
        {("section_water_level", section_id): level for section_id, level in section_observations.items()}
    )
    for gate in snapshot.get("gates", []):
        up = gate.get("upstream_node_id")
        down = gate.get("downstream_node_id")
        if up in levels and down in levels:
            observations[("gate_head_difference", int(gate["id"]))] = levels[int(up)] - levels[int(down)]
    for pump in snapshot.get("pumps", []):
        intake = pump.get("intake_node_id")
        if intake in levels:
            observations[("pump_intake_level", int(pump["id"]))] = levels[int(intake)]
    targets = policy.targets_at(time_seconds, HydraulicObservation(time_seconds, observations))
    by_asset = {(item.structure_type, item.structure_id, item.command_type): item for item in targets}
    edge_overrides: dict[int, float] = {}
    node_sources: dict[int, float] = defaultdict(float)
    structure_rows: list[dict[str, Any]] = []
    events: list[dict[str, Any]] = []
    for component in policy.policies:
        if not isinstance(component, ThresholdRulePolicy):
            continue
        for audit in component.consume_audit_events():
            template = dict(audit["action_template"])
            events.append({
                "time_seconds": audit["time_seconds"], "source_type": "rule",
                "source_id": audit["rule_id"],
                "structure_type": template["structure_type"],
                "structure_id": int(template["structure_id"]),
                "requested_command": {
                    "command_type": template["command_type"],
                    "target_value": template["target_value"],
                },
                "applied_command": None, "outcome": audit["event_type"],
                "reason": f"rule_{audit['event_type']}",
            })

    for gate in snapshot.get("gates", []):
        gate_id = int(gate["id"])
        up = gate.get("upstream_node_id")
        down = gate.get("downstream_node_id")
        segment_id = gate.get("river_segment_id")
        if up not in levels or down not in levels or segment_id is None:
            continue
        state = gate_states.setdefault(gate_id, GateControlState())
        target = by_asset.get(("gate", gate_id, "gate_opening_m"))
        ratio_target = by_asset.get(("gate", gate_id, "gate_opening_ratio"))
        # A structure only becomes an internal hydraulic control when the
        # frozen dispatch plan actually addresses it.  The baseline task must
        # preserve the natural river connection for a fair comparison.
        if target is None and ratio_target is None:
            continue
        requested = state.opening
        if target is not None:
            requested = target.target_value
        elif ratio_target is not None:
            requested = ratio_target.target_value * float(gate.get("maximum_opening") or gate.get("height") or 0.0)
            target = ratio_target
        valid, reason = validate_control_target(
            target, str(gate.get("status", "offline"))
        ) if target is not None else (True, None)
        actual, flags = constrain_gate_opening(
            requested if valid else state.opening,
            previous_opening=state.opening,
            elapsed_seconds=elapsed_seconds,
            minimum_opening=float(gate.get("minimum_opening") or 0.0),
            maximum_opening=float(gate.get("maximum_opening") or gate.get("height") or 0.0),
            opening_rate_limit=float(gate.get("opening_rate_limit") or 1.0e9),
            minimum_hold_seconds=float(gate.get("minimum_hold_seconds") or 0.0),
            time_since_change=time_seconds - state.last_change_time,
            availability=str(gate.get("status", "offline")),
        )
        hydraulic = evaluate_gate(
            width=float(gate["width"]), requested_opening=requested,
            actual_opening=actual, upstream_level=levels[int(up)],
            downstream_level=levels[int(down)],
            crest_elevation=float(gate.get("crest_elevation") or gate.get("bottom_elevation") or 0.0),
            discharge_coefficient=float(gate.get("discharge_coefficient") or 0.62),
            maximum_flow=float(gate.get("max_flow")) if gate.get("max_flow") is not None else None,
            allow_reverse_flow=bool(gate.get("allow_reverse_flow", False)),
        )
        if not math.isclose(actual, state.opening):
            state.opening = actual
            state.last_change_time = time_seconds
        edge_overrides[int(segment_id)] = hydraulic.flow
        all_flags = list(flags) + list(hydraulic.constraint_flags)
        structure_rows.append({
            "time_seconds": time_seconds, "structure_type": "gate", "structure_id": gate_id,
            "requested_value": requested, "actual_value": actual, "flow": hydraulic.flow,
            "upstream_level": levels[int(up)], "downstream_level": levels[int(down)],
            "head_difference": hydraulic.head_difference,
            "power_kw": 0.0, "energy_kwh": 0.0, "regime": hydraulic.regime,
            "constraint_flags": all_flags,
        })
        if target is not None:
            events.append({
                "time_seconds": time_seconds, "source_type": target.source_type,
                "source_id": target.source_id, "structure_type": "gate", "structure_id": gate_id,
                "requested_command": {"command_type": target.command_type, "target_value": target.target_value},
                "applied_command": {"opening_m": actual},
                "outcome": "rejected" if not valid else ("limited" if all_flags else "applied"),
                "reason": reason or (",".join(all_flags) if all_flags else None),
            })

    for pump in snapshot.get("pumps", []):
        pump_id = int(pump["id"])
        intake = pump.get("intake_node_id")
        outlet = pump.get("outlet_node_id")
        transfer_type = str(pump.get("transfer_type") or "internal_transfer")
        if transfer_type == "internal_transfer" and (intake not in levels or outlet not in levels):
            continue
        if transfer_type == "external_outflow" and intake not in levels:
            continue
        if transfer_type == "external_inflow" and outlet not in levels:
            continue
        state = pump_states.setdefault(pump_id, PumpControlState())
        unit_target = by_asset.get(("pump", pump_id, "pump_unit_count"))
        enabled_target = by_asset.get(("pump", pump_id, "pump_enabled"))
        flow_target = by_asset.get(("pump", pump_id, "pump_target_flow"))
        target = unit_target or enabled_target or flow_target
        if target is None:
            continue
        requested_units = state.running_units
        if unit_target is not None:
            requested_units = int(round(unit_target.target_value))
        elif enabled_target is not None:
            requested_units = int(pump.get("maximum_running_units") or pump.get("unit_count") or 1) if enabled_target.target_value >= 0.5 else 0
        elif flow_target is not None:
            requested_units = int(pump.get("maximum_running_units") or pump.get("unit_count") or 1)
        intake_level = levels[int(intake)] if intake in levels else None
        outlet_level = levels[int(outlet)] if outlet in levels else None
        static_head = max(
            (outlet_level if outlet_level is not None else intake_level or 0.0)
            - (intake_level if intake_level is not None else outlet_level or 0.0),
            0.0,
        )
        nominal_units = max(requested_units, 1)
        requested_flow = (
            max(float(flow_target.target_value), 0.0)
            if flow_target is not None
            else nominal_units * float(pump.get("design_flow") or 0.0)
            / max(int(pump.get("unit_count") or 1), 1)
        )
        curve_points = list((pump.get("head_curve") or {}).get("points", []))
        curve_error = False
        try:
            curve_head = (
                interpolate_curve(curve_points, requested_flow)
                if curve_points
                else float(pump.get("head") or 0.0)
            )
        except ValueError:
            curve_error = True
            curve_head = float(pump.get("maximum_operating_head") or 0.0) + 1.0
        # 对节点水位给出的正扬程采用系统扬程；顺坡/等水位的简化网络则采用
        # 当前请求流量在 Q-H 曲线上的扬程，避免把正在运行的泵错误计为零功率。
        head = static_head if static_head > 1.0e-9 else curve_head
        result = evaluate_pump(
            requested_units=requested_units,
            target_flow=flow_target.target_value if flow_target is not None else None,
            design_flow_per_unit=float(pump.get("design_flow") or 0.0) / max(int(pump.get("unit_count") or 1), 1),
            head=head, elapsed_seconds=elapsed_seconds, state=state,
            availability=str(pump.get("status", "offline")),
            minimum_running_units=int(pump.get("minimum_running_units") or 1),
            maximum_running_units=int(pump.get("maximum_running_units") or pump.get("unit_count") or 1),
            minimum_run_seconds=float(pump.get("minimum_run_seconds") or 0.0),
            minimum_stop_seconds=float(pump.get("minimum_stop_seconds") or 0.0),
            maximum_starts_per_run=int(pump.get("maximum_starts_per_run") or 999999),
            minimum_operating_head=float(pump.get("minimum_operating_head") or 0.0),
            maximum_operating_head=float(pump.get("maximum_operating_head") or 1.0e9),
            efficiency_curve=list((pump.get("efficiency_curve") or {"points": [[0, 0.7], [1, 0.8]]})["points"]),
            intake_depth=(
                intake_level - node_bed_levels[int(intake)]
                if intake in node_bed_levels and intake_level is not None
                else None
            ),
            minimum_intake_depth=minimum_depth,
        )
        if state.running_units == 0 and result.actual_units > 0:
            state.starts += 1
            state.runtime_seconds = 0.0
        if result.actual_units > 0:
            state.runtime_seconds += elapsed_seconds
            state.stop_seconds = 0.0
        else:
            state.stop_seconds += elapsed_seconds
        state.running_units = result.actual_units
        state.energy_kwh += result.energy_kwh
        if intake is not None:
            node_sources[int(intake)] -= result.flow
        if outlet is not None:
            node_sources[int(outlet)] += result.flow
        result_flags = [*result.constraint_flags]
        if curve_error:
            result_flags.append("head_curve_out_of_range")
        structure_rows.append({
            "time_seconds": time_seconds, "structure_type": "pump", "structure_id": pump_id,
            "requested_value": requested_units, "actual_value": result.actual_units,
            "flow": result.flow, "upstream_level": intake_level,
            "downstream_level": outlet_level, "head_difference": result.head,
            "power_kw": result.power_kw, "energy_kwh": state.energy_kwh,
            "regime": result.regime, "constraint_flags": result_flags,
            "transfer_type": transfer_type,
        })
        if target is not None:
            events.append({
                "time_seconds": time_seconds, "source_type": target.source_type,
                "source_id": target.source_id, "structure_type": "pump", "structure_id": pump_id,
                "requested_command": {"command_type": target.command_type, "target_value": target.target_value},
                "applied_command": {"unit_count": result.actual_units, "flow": result.flow},
                "outcome": "limited" if result_flags else "applied",
                "reason": ",".join(result_flags) if result_flags else None,
            })
    return edge_overrides, dict(node_sources), structure_rows, events


def _river_edge_ranges(network: NetworkMesh) -> dict[int, list[tuple[float, float, NetworkEdge]]]:
    """按拓扑顺序为每条河道建立累计桩号区间。"""

    result: dict[int, list[tuple[float, float, NetworkEdge]]] = {}
    for branch in network.branches:
        river_edges = [edge for edge in network.edges if edge.river_id == branch.mesh.river_id]
        by_upstream = {edge.upstream_node_id: edge for edge in river_edges}
        ordered: list[NetworkEdge] = []
        node = branch.upstream_node_id
        visited: set[int] = set()
        while node in by_upstream:
            edge = by_upstream[node]
            if edge.segment_id in visited:
                raise HydraulicInputError(f"河道 {branch.mesh.river_code} 河段形成环")
            visited.add(edge.segment_id)
            ordered.append(edge)
            node = edge.downstream_node_id
        if len(ordered) != len(river_edges):
            raise HydraulicInputError(f"河道 {branch.mesh.river_code} 河段方向不连续")
        cursor = 0.0
        ranges: list[tuple[float, float, NetworkEdge]] = []
        for edge in ordered:
            ranges.append((cursor, cursor + edge.length, edge))
            cursor += edge.length
        result[branch.mesh.river_id] = ranges
    return result


def _network_cfl_step(network: NetworkMesh, config: SolverConfig) -> tuple[float, float]:
    """以所有河段和代表断面计算统一保守 CFL 步长与实际 CFL。"""

    representative = _representative_hydraulics(network)
    maximum_wave_speed = 0.0
    for branch in network.branches:
        _, area, _ = representative[branch.mesh.river_id]
        section = branch.mesh.sections[len(branch.mesh.sections) // 2]
        depth = max(area / max(section.width, 1.0e-12), config.minimum_depth)
        velocity = abs(config.initial_flow) / max(area, 1.0e-12)
        maximum_wave_speed = max(maximum_wave_speed, velocity + math.sqrt(9.81 * depth))
    minimum_length = min(edge.length for edge in network.edges)
    stability_step = config.cfl_number * minimum_length / max(maximum_wave_speed, 1.0e-12)
    step = min(config.requested_time_step, stability_step)
    actual_cfl = maximum_wave_speed * step / minimum_length
    return step, actual_cfl


def solve_network(
    network: NetworkMesh,
    config: SolverConfig,
    boundaries: BoundarySet,
    *,
    event_times: tuple[float, ...] = (),
    snapshot: Mapping[str, Any] | None = None,
    cancel_check: object | None = None,
    progress_callback: object | None = None,
) -> NetworkSolveResult:
    """在统一时刻计算河网流量、共同节点水位、断面状态和质量残差。"""

    order = _topological_order(network)
    source_nodes = {item.node_id for item in network.nodes if item.is_external_source}
    sink_nodes = {item.node_id for item in network.nodes if item.is_external_sink}
    missing_sources = [node for node in source_nodes if node not in boundaries.by_node]
    missing_sinks = [node for node in sink_nodes if node not in boundaries.by_node]
    if missing_sources or missing_sinks:
        raise HydraulicInputError(
            f"正式河网缺少外边界：source={missing_sources}, sink={missing_sinks}"
        )
    policy, plan_event_times = _build_control_policy(
        snapshot.get("dispatch_plan") if isinstance(snapshot, Mapping) else None
    )
    times = {0.0, config.duration_seconds, *event_times, *plan_event_times}
    cursor = config.output_interval
    while cursor < config.duration_seconds:
        times.add(cursor)
        cursor += config.output_interval
    ordered_times = tuple(sorted(time for time in times if 0 <= time <= config.duration_seconds))
    synchronized_time_step, network_cfl = _network_cfl_step(network, config)
    ranges = _river_edge_ranges(network)
    series = tuple(
        SectionSeries(section=section)
        for branch in network.branches
        for section in branch.mesh.sections
    )
    series_by_section = {item.section.id: item for item in series}
    node_series: list[dict[str, Any]] = []
    external_inflow_volume = 0.0
    external_outflow_volume = 0.0
    gate_transfer_volume = 0.0
    pump_transfer_volume = 0.0
    previous_time = ordered_times[0]
    previous_inflow = 0.0
    previous_outflow = 0.0
    maximum_node_residual = 0.0
    structure_series: list[dict[str, Any]] = []
    dispatch_events: list[dict[str, Any]] = []
    emitted_event_signatures: set[tuple[Any, ...]] = set()
    gate_states: dict[int, GateControlState] = {}
    pump_states: dict[int, PumpControlState] = {}
    node_bed_levels: dict[int, float] = {}
    for branch in network.branches:
        branch_bed = min(item.bed_elevation for item in branch.mesh.sections)
        for edge in network.edges:
            if edge.river_id == branch.mesh.river_id:
                for node_id in (edge.upstream_node_id, edge.downstream_node_id):
                    node_bed_levels[node_id] = min(
                        node_bed_levels.get(node_id, branch_bed), branch_bed
                    )
    gate_segments = {
        int(item["id"]): int(item["river_segment_id"])
        for item in (snapshot or {}).get("gates", [])
        if item.get("river_segment_id") is not None
    }
    previous_section_levels = {
        section.id: max(
            section.bed_elevation + config.minimum_depth,
            config.initial_water_level
            if config.initial_water_level is not None
            else section.bed_elevation + 1.0,
        )
        for branch in network.branches
        for section in branch.mesh.sections
    }

    for time_seconds in ordered_times:
        if callable(cancel_check) and cancel_check():
            raise HydraulicCancelledError("hydraulic task cancelled cooperatively")
        base_flows, _ = _route_flows(network, order, boundaries, time_seconds)
        base_levels = _node_levels(network, order, boundaries, base_flows, time_seconds)
        edge_overrides, node_sources, structure_rows, events = _structure_controls(
            snapshot or {}, policy, time_seconds, time_seconds - previous_time,
            base_levels, gate_states, pump_states, node_bed_levels, config.minimum_depth,
            previous_section_levels,
        )
        flows, node_rows = _route_flows(
            network, order, boundaries, time_seconds,
            node_sources=node_sources, edge_overrides=edge_overrides,
        )
        # 闸门方程给出请求通量，节点连续性仍可能受上游可用流量约束。
        # 持久化和体积积分必须使用路由后的实际边通量，而不是未应用的请求值。
        for row in structure_rows:
            if row["structure_type"] == "gate":
                segment_id = gate_segments.get(int(row["structure_id"]))
                if segment_id in flows:
                    requested_flow = float(row["flow"])
                    row["flow"] = flows[segment_id]
                    if not math.isclose(requested_flow, float(row["flow"])):
                        row["constraint_flags"] = [
                            *row["constraint_flags"], "available_flow_limited"
                        ]
        levels = _node_levels(network, order, boundaries, flows, time_seconds)
        structure_series.extend(structure_rows)
        for event in events:
            signature = (
                event.get("source_type"), event.get("source_id"),
                event.get("structure_type"), event.get("structure_id"),
                event.get("outcome"), event.get("reason"),
                tuple(sorted((event.get("requested_command") or {}).items())),
                tuple(sorted((event.get("applied_command") or {}).items())),
            )
            if signature not in emitted_event_signatures:
                emitted_event_signatures.add(signature)
                dispatch_events.append(event)
        if callable(progress_callback):
            progress_callback(time_seconds, network_cfl)
        current_inflow = sum(
            float(boundaries.by_node[node].value_at(time_seconds)) for node in source_nodes
        )
        current_outflow = sum(
            float(row["outflow"]) for row in node_rows if int(row["node_id"]) in sink_nodes
        )
        current_inflow += sum(
            float(row["flow"]) for row in structure_rows
            if row.get("structure_type") == "pump"
            and row.get("transfer_type") == "external_inflow"
        )
        current_outflow += sum(
            float(row["flow"]) for row in structure_rows
            if row.get("structure_type") == "pump"
            and row.get("transfer_type") == "external_outflow"
        )
        dt = time_seconds - previous_time
        if dt > 0:
            external_inflow_volume += 0.5 * (previous_inflow + current_inflow) * dt
            external_outflow_volume += 0.5 * (previous_outflow + current_outflow) * dt
            gate_transfer_volume += sum(
                abs(float(row["flow"])) * dt
                for row in structure_rows
                if row["structure_type"] == "gate"
            )
            pump_transfer_volume += sum(
                abs(float(row["flow"])) * dt
                for row in structure_rows
                if row["structure_type"] == "pump"
            )
        previous_time = time_seconds
        previous_inflow = current_inflow
        previous_outflow = current_outflow
        for row in node_rows:
            row["time_seconds"] = time_seconds
            row["water_level"] = levels[int(row["node_id"])]
            maximum_node_residual = max(
                maximum_node_residual, abs(float(row["balance_residual"]))
            )
            node_series.append(row)

        for branch in network.branches:
            edge_ranges = ranges[branch.mesh.river_id]
            scale = edge_ranges[-1][1] / max(branch.mesh.sections[-1].station, 1.0e-12)
            for section in branch.mesh.sections:
                network_station = section.station * scale
                start, end, edge = next(
                    (item for item in edge_ranges if item[0] <= network_station <= item[1]),
                    edge_ranges[-1],
                )
                ratio = (network_station - start) / max(end - start, 1.0e-12)
                stage = levels[edge.upstream_node_id] + ratio * (
                    levels[edge.downstream_node_id] - levels[edge.upstream_node_id]
                )
                stage = max(stage, section.bed_elevation + config.minimum_depth)
                try:
                    area = section.geometry.area(stage)
                except HydraulicInputError as exc:
                    raise HydraulicStabilityError(
                        f"河网水位 {stage} 超出断面 {section.code} 查算范围"
                    ) from exc
                series_by_section[section.id].append(
                    time_seconds, area, flows[edge.segment_id]
                )
                previous_section_levels[section.id] = stage

    balance = evaluate_water_balance(
        initial_storage=0.0,
        final_storage=0.0,
        external_inflow_volume=external_inflow_volume,
        external_outflow_volume=external_outflow_volume,
        gate_transfer_volume=gate_transfer_volume,
        pump_transfer_volume=pump_transfer_volume,
    )
    normaliser = max(max(abs(previous_inflow), abs(previous_outflow)), 1.0)
    return NetworkSolveResult(
        series=series,
        node_series=tuple(node_series),
        structure_series=tuple(structure_series),
        dispatch_events=tuple(dispatch_events),
        diagnostics={
            "solver": "synchronous-network-continuity-manning-v1",
            "junction_condition": "common stage plus discharge continuity",
            "momentum_compatibility": "not implemented",
            "time_axis": list(ordered_times),
            "maximum_node_balance_residual": maximum_node_residual,
            "maximum_normalized_node_residual": maximum_node_residual / normaliser,
            "maximum_cfl": network_cfl,
            "minimum_time_step": synchronized_time_step,
            "water_balance": balance.to_dict(),
            "topology": network.diagnostics,
            "geometry_types": sorted(
                {
                    section.geometry.geometry_type
                    for branch in network.branches
                    for section in branch.mesh.sections
                }
            ),
            "rule_trigger_count": sum(
                item.trigger_count
                for item in policy.policies
                if isinstance(item, ThresholdRulePolicy)
            ),
            "conflict_resolution_count": policy.conflict_count,
        },
    )
