"""Engineering metrics calculated only from unified MASCARET result records."""

from __future__ import annotations

from collections import defaultdict
from typing import Any

from model.hydraulic_1d import Hydraulic1DModel, HydraulicResult
from model.hydraulic_1d.network import HydraulicNetworkGraph


def _interpolate(samples: tuple[Any, ...], time_seconds: float) -> float:
    """Linearly interpolate a complete validated hydraulic boundary series."""

    if len(samples) == 1:
        return float(samples[0].value)
    if time_seconds <= samples[0].time_seconds:
        return float(samples[0].value)
    for left, right in zip(samples, samples[1:]):
        if time_seconds <= right.time_seconds:
            fraction = (time_seconds - left.time_seconds) / (
                right.time_seconds - left.time_seconds
            )
            return float(left.value + fraction * (right.value - left.value))
    return float(samples[-1].value)


def engineering_metrics(
    model: Hydraulic1DModel,
    result: HydraulicResult,
) -> dict[str, Any]:
    """Return continuity, storage-aware mass balance, peaks, and ownership metrics."""

    graph = HydraulicNetworkGraph(model)
    sections_by_branch = {
        branch.id: graph.branch_sections(branch.id) for branch in model.branches
    }
    rows: dict[float, dict[str, Any]] = defaultdict(dict)
    for record in result.records:
        rows[float(record.timestamp)][record.cross_section_id] = record
    times = sorted(rows)

    def endpoint_flow(time_seconds: float, branch_id: str, upstream: bool) -> float:
        sections = sections_by_branch[branch_id]
        section = sections[0] if upstream else sections[-1]
        return float(rows[time_seconds][section.id].discharge_m3s)

    unadjusted_continuity_ratios: dict[float, list[float]] = defaultdict(list)
    water_level_spreads: list[float] = []
    internal_nodes = [
        node_id
        for node_id in graph.node_ids
        if graph.incoming_branches(node_id) and graph.outgoing_branches(node_id)
    ]
    for time_seconds in times:
        for node_id in internal_nodes:
            incoming = sum(
                endpoint_flow(time_seconds, branch.id, False)
                for branch in graph.incoming_branches(node_id)
            )
            outgoing = sum(
                endpoint_flow(time_seconds, branch.id, True)
                for branch in graph.outgoing_branches(node_id)
            )
            unadjusted_continuity_ratios[time_seconds].append(
                abs(incoming - outgoing) / max(abs(incoming), abs(outgoing), 1.0)
            )
            stages = [
                float(
                    rows[time_seconds][
                        sections_by_branch[branch.id][-1].id
                    ].water_level_m
                )
                for branch in graph.incoming_branches(node_id)
            ] + [
                float(
                    rows[time_seconds][
                        sections_by_branch[branch.id][0].id
                    ].water_level_m
                )
                for branch in graph.outgoing_branches(node_id)
            ]
            water_level_spreads.append(max(stages) - min(stages))

    # The official listing reports each native 2D confluence control volume,
    # including its initial/final storage and integrated boundary fluxes. Keep
    # the endpoint-only imbalance as a diagnostic, but gate on that native CV.
    node_continuity_residual = float(
        result.diagnostics.get("node_continuity_residual", 0.0)
    )

    def network_volume(time_seconds: float) -> float:
        volume = 0.0
        for branch in model.branches:
            sections = sections_by_branch[branch.id]
            for left, right in zip(sections, sections[1:]):
                left_area = float(rows[time_seconds][left.id].flow_area_m2)
                right_area = float(rows[time_seconds][right.id].flow_area_m2)
                volume += (
                    (left_area + right_area)
                    * 0.5
                    * (right.chainage_m - left.chainage_m)
                )
        return volume

    def external_flux(time_seconds: float) -> tuple[float, float]:
        inflow = 0.0
        outflow = 0.0
        for node_id in graph.node_ids:
            incoming = graph.incoming_branches(node_id)
            outgoing = graph.outgoing_branches(node_id)
            if not incoming:
                inflow += sum(
                    endpoint_flow(time_seconds, branch.id, True) for branch in outgoing
                )
            if not outgoing:
                outflow += sum(
                    endpoint_flow(time_seconds, branch.id, False) for branch in incoming
                )
        inflow += sum(
            _interpolate(boundary.series, time_seconds)
            for boundary in model.boundaries
            if boundary.location == "lateral"
        )
        return inflow, outflow

    net_volume = 0.0
    inflow_volume = 0.0
    for left_time, right_time in zip(times, times[1:]):
        left_in, left_out = external_flux(left_time)
        right_in, right_out = external_flux(right_time)
        delta_time = right_time - left_time
        net_volume += 0.5 * ((left_in - left_out) + (right_in - right_out)) * delta_time
        inflow_volume += 0.5 * (left_in + right_in) * delta_time
    storage_change = network_volume(times[-1]) - network_volume(times[0])
    section_integrated_mass_balance = abs(storage_change - net_volume) / max(
        abs(inflow_volume),
        abs(storage_change),
        1.0,
    )
    peak_discharge = max(result.records, key=lambda item: item.discharge_m3s)
    peak_water_level = max(result.records, key=lambda item: item.water_level_m)
    final_time = times[-1]
    branch_discharge = {
        branch.id: endpoint_flow(final_time, branch.id, False)
        for branch in model.branches
    }
    return {
        "node_continuity_residual": node_continuity_residual,
        "maximum_unadjusted_node_flux_imbalance": max(
            (
                value
                for values in unadjusted_continuity_ratios.values()
                for value in values
            ),
            default=0.0,
        ),
        "network_mass_balance_residual": float(
            result.diagnostics.get(
                "network_mass_balance_residual",
                section_integrated_mass_balance,
            )
        ),
        "mass_balance_source": (
            "mascaret_listing"
            if "network_mass_balance_residual" in result.diagnostics
            else "section_integrated_estimate"
        ),
        "section_integrated_mass_balance_residual_estimate": (
            section_integrated_mass_balance
        ),
        "junction_water_level_spread_m": max(water_level_spreads, default=0.0),
        "branch_discharge_m3s": branch_discharge,
        "peak_discharge_m3s": float(peak_discharge.discharge_m3s),
        "peak_discharge_time_seconds": float(peak_discharge.timestamp),
        "peak_water_level_m": float(peak_water_level.water_level_m),
        "peak_water_level_time_seconds": float(peak_water_level.timestamp),
        "model_build_seconds": float(result.diagnostics["model_build_seconds"]),
        "runtime_seconds": float(result.diagnostics["runtime_seconds"]),
        "parser_seconds": float(result.diagnostics["parser_seconds"]),
        "result_record_count": len(result.records),
    }
