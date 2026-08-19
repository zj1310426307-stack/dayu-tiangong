"""Framework-neutral orchestration for the Phase 3 hydraulic engine."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from model.api.contracts import build_solver_config
from model.boundary.conditions import build_boundary_set
from model.core.errors import HydraulicInputError
from model.core.types import EngineResult
from model.mesh.builder import build_river_meshes
from model.metrics import evaluate_metrics
from model.network import build_network_mesh, solve_network
from model.solver.saint_venant import solve_river
from model.structure.gate import gate_discharge
from model.structure.pump import pump_discharge
from model.adapters import adapt_v3_to_v2, run_v4_lite
from model.result.mvp import MvpHydraulicResult


class HydraulicEngine:
    """Build meshes, bind conditions and execute independent river solves."""

    def run(
        self,
        snapshot: Mapping[str, Any],
        overrides: Mapping[str, Any] | None = None,
        *,
        cancel_check: Any | None = None,
        progress_callback: Any | None = None,
    ) -> EngineResult | MvpHydraulicResult:
        """Run a versioned Phase 2 snapshot and return serialisable time series."""

        if not isinstance(snapshot, Mapping):
            raise TypeError("snapshot must be a mapping")
        if snapshot.get("schema_version") == "dayu.model-input.v4-lite":
            if overrides:
                raise HydraulicInputError(
                    "v4-lite snapshot is frozen and does not accept legacy overrides"
                )
            if cancel_check is not None or progress_callback is not None:
                raise HydraulicInputError(
                    "v4-lite direct execution does not yet support cancellation "
                    "or progress callbacks"
                )
            return run_v4_lite(snapshot)
        if snapshot.get("schema_version") == "dayu.model-input.v3":
            snapshot = adapt_v3_to_v2(snapshot)
        if snapshot.get("schema_version") == "dayu.model-input.v2":
            return self._run_network(
                snapshot,
                overrides,
                cancel_check=cancel_check,
                progress_callback=progress_callback,
            )
        if snapshot.get("schema_version") != "dayu.model-input.v1":
            raise HydraulicInputError(
                "unsupported model input schema: "
                f"{snapshot.get('schema_version')!r}; expected dayu.model-input.v1, "
                "dayu.model-input.v2, dayu.model-input.v3, or dayu.model-input.v4-lite"
            )
        mesh_result = build_river_meshes(snapshot)
        config = build_solver_config(snapshot, overrides)
        boundaries = build_boundary_set(snapshot, mesh_result.meshes)

        all_series = []
        river_diagnostics: dict[str, Any] = {}
        for mesh in mesh_result.meshes:
            solved = solve_river(
                mesh,
                config,
                boundaries.upstream_flow.get(mesh.river_id),
                boundaries.downstream_level.get(mesh.river_id),
                cancel_check=cancel_check,
                progress_callback=progress_callback,
            )
            all_series.extend(solved.series)
            river_diagnostics[mesh.river_code] = solved.diagnostics

        structures = self._structure_preview(snapshot)
        return EngineResult(
            series=tuple(all_series),
            diagnostics={
                "solver": "saint-venant-rusanov-rectangular-v1",
                "coordinate_system": "CGCS2000 (EPSG:4490)",
                "distance_basis": "section station and segment length in metres",
                "river_count": len(mesh_result.meshes),
                "section_count": len(all_series),
                "skipped_rivers": list(mesh_result.skipped_rivers),
                "river_diagnostics": river_diagnostics,
                "structure_coupling": "reserved",
                "structure_preview": structures,
            },
        )

    def _run_network(
        self,
        snapshot: Mapping[str, Any],
        overrides: Mapping[str, Any] | None,
        *,
        cancel_check: Any | None = None,
        progress_callback: Any | None = None,
    ) -> EngineResult:
        """执行 v2 有向河网同步计算并返回扩展结果契约。"""

        network = build_network_mesh(snapshot)
        config = build_solver_config(snapshot, overrides)
        meshes = tuple(branch.mesh for branch in network.branches)
        boundaries = build_boundary_set(snapshot, meshes)
        raw_plan = snapshot.get("dispatch_plan")
        event_times = ()
        if isinstance(raw_plan, Mapping):
            actions = raw_plan.get("actions", [])
            if isinstance(actions, list):
                event_times = tuple(
                    sorted(
                        {
                            float(item["time_seconds"])
                            for item in actions
                            if "time_seconds" in item
                        }
                    )
                )
        solved = solve_network(
            network,
            config,
            boundaries,
            event_times=event_times,
            snapshot=snapshot,
            cancel_check=cancel_check,
            progress_callback=progress_callback,
        )
        provenance = dict(snapshot.get("provenance", {}))
        provenance["input_schema_version"] = snapshot.get(
            "_source_schema_version", "dayu.model-input.v2"
        )
        plan = snapshot.get("dispatch_plan")
        evaluation_config = {}
        if isinstance(plan, Mapping):
            plan_record = plan.get("plan", {})
            if isinstance(plan_record, Mapping):
                evaluation_config = dict(plan_record.get("evaluation_config", {}))
        section_rows = [item.to_dict() for item in solved.series]
        structure_rows = list(solved.structure_series)
        metrics = evaluate_metrics(
            section_series=section_rows,
            structure_series=structure_rows,
            diagnostics=solved.diagnostics,
            evaluation_config=evaluation_config,
        )
        return EngineResult(
            series=solved.series,
            node_series=solved.node_series,
            structure_series=solved.structure_series,
            dispatch_events=solved.dispatch_events,
            diagnostics={
                **solved.diagnostics,
                "coordinate_system": "CGCS2000 (EPSG:4490)",
                "distance_basis": "section station and segment length in metres",
                "structure_coupling": "network interface/source-sink",
            },
            schema_version="dayu.hydraulic-result.v2",
            water_balance=dict(solved.diagnostics.get("water_balance", {})),
            metrics=metrics,
            provenance=provenance,
        )

    @staticmethod
    def _structure_preview(snapshot: Mapping[str, Any]) -> dict[str, Any]:
        """Evaluate configured gate/pump capacity without coupling it to cells."""

        gates = snapshot.get("gates", [])
        pumps = snapshot.get("pumps", [])
        if not isinstance(gates, list) or not isinstance(pumps, list):
            raise HydraulicInputError("gates and pumps must be arrays")

        gate_items = []
        for item in gates:
            is_online = str(item.get("status", "offline")) == "online"
            opening = float(item.get("opening", item.get("height", 0.0)) or 0.0)
            if not is_online:
                opening = 0.0
            width = float(item.get("width", 0.0) or 0.0)
            bottom = float(item.get("bottom_elevation", 0.0) or 0.0)
            head = float(item.get("design_head", item.get("height", 0.0)) or 0.0)
            maximum = item.get("max_discharge", item.get("max_flow"))
            gate_items.append(
                {
                    "id": item.get("id"),
                    "code": item.get("code", item.get("gate_code")),
                    "estimated_discharge": gate_discharge(
                        width=width,
                        opening=opening,
                        upstream_level=bottom + head,
                        downstream_level=bottom,
                        bottom_elevation=bottom,
                        maximum_flow=float(maximum) if maximum is not None else None,
                    ),
                }
            )

        pump_items = [
            {
                "id": item.get("id"),
                "code": item.get("code", item.get("pump_code")),
                "estimated_discharge": pump_discharge(
                    design_flow=float(item.get("design_flow", 0.0) or 0.0),
                    enabled=str(item.get("status", "offline")) == "online",
                    status=str(item.get("status", "offline")),
                ),
            }
            for item in pumps
        ]
        return {"gates": gate_items, "pumps": pump_items}
