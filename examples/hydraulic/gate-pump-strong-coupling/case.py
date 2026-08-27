"""Frozen HYDRO-MODEL-02-D1 six-hour Gate/Pump example."""

from __future__ import annotations

import json
import sys
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from model import HydraulicEngine


def _section(section_id: int) -> dict:
    """Build one member of the frozen prismatic 20-section mesh."""

    return {
        "section_id": section_id,
        "section_code": f"CS{section_id:02d}",
        "branch_id": 21,
        "chainage_m": 400.0 * (section_id - 1),
        "profile_id": 100 + section_id,
        "profile_hash": f"{section_id:064x}",
        "default_manning_n": 0.0,
        "points": [
            {"offset_m": 0.0, "elevation_m": 12.0},
            {"offset_m": 10.0, "elevation_m": 9.0},
            {"offset_m": 20.0, "elevation_m": 12.0},
        ],
    }


def build_case() -> dict:
    """Return the JSON-shaped v4-lite-7 benchmark input without side effects."""

    return {
        "schema_version": "dayu.model-input.v4-lite",
        "dataset_version": {
            "id": 1,
            "content_hash": "a" * 64,
        },
        "coordinate_reference": {
            "engineering_crs": "EPSG:4547",
            "horizontal_unit": "m",
            "vertical_datum": "1985 National Height Datum",
            "vertical_unit": "m",
        },
        "solver": {
            "type": "saint-venant",
            "scheme": "finite-volume-hll",
            "time_integrator": "ssp-rk2",
            "friction_method": "manning-semi-implicit",
            "duration_seconds": 21600.0,
            "maximum_time_step_seconds": 60.0,
            "minimum_time_step_seconds": 0.001,
            "output_interval_seconds": 900.0,
            "cfl_number": 0.7,
            "dry_depth_m": 0.001,
            "maximum_retries": 8,
            "maximum_steps": 100000,
            "water_balance_tolerance": 1.0e-10,
            "geometry_policy": "absolute-prismatic-v1",
            "geometry_source": "hydrostatic-reconstruction-v1",
            "bed_elevation_source": "profile-minimum-elevation-v1",
            "equilibrium_policy": "standard-v1",
            "boundary_closure": "subcritical-characteristic-v1",
            "boundary_spatial_support": "nearest-section-cell-face-v1",
            "structure_event_policy": (
                "bracketed-conservative-replay-right-end-v1"
            ),
            "event_time_tolerance_seconds": 5.0,
            "maximum_event_refinements": 40,
            "control_spatial_support": "bound-section-cell-center-v1",
            "gate_coupling_policy": "submerged-orifice-energy-momentum-v1",
            "gate_equation_tolerance_m": 1.0e-10,
            "gate_maximum_iterations": 80,
            "gate_spatial_support": "bound-internal-section-face-v1",
            "pump_coupling_policy": "qh-operating-point-external-sink-v1",
            "pump_curve_policy": "piecewise-linear-qh-v1",
            "pump_efficiency_policy": "piecewise-linear-q-efficiency-v1",
            "pump_system_loss_policy": "quadratic-q-v1",
            "pump_control_policy": "stage-hysteresis-min-runtime-v1",
            "pump_momentum_policy": "local-advective-external-sink-v1",
            "pump_head_residual_tolerance_m": 1.0e-10,
            "pump_maximum_iterations": 100,
            "pump_spatial_support": "bound-section-cell-center-v1",
        },
        "river": {
            "network_id": 11,
            "branch_id": 21,
            "branch_code": "B-001",
            "upstream_node_id": 31,
            "downstream_node_id": 32,
            "start_chainage_m": 0.0,
            "end_chainage_m": 7600.0,
            "direction_status": "confirmed",
        },
        "sections": [_section(section_id) for section_id in range(1, 21)],
        "initial_state": {
            "type": "by-section",
            "values": [
                {
                    "section_id": section_id,
                    "water_level_m": 10.0,
                    "discharge_m3_s": 0.0,
                }
                for section_id in range(1, 21)
            ],
        },
        "boundary": {
            "upstream": {
                "identity": {
                    "namespace": "public.boundary_condition",
                    "id": 41,
                },
                "type": "discharge-series",
                "target_node_id": 31,
                "time_seconds": [
                    0.0,
                    1800.0,
                    5400.0,
                    9000.0,
                    12600.0,
                    16200.0,
                    21600.0,
                ],
                "flow_m3_s": [0.10, 0.15, 0.25, 0.25, 0.12, 0.06, 0.06],
                "interpolation": "linear",
                "extrapolation": "error",
            },
            "downstream": {
                "identity": {
                    "namespace": "public.boundary_condition",
                    "id": 42,
                },
                "type": "stage-series",
                "target_node_id": 32,
                "time_seconds": [0.0, 1800.0, 21600.0],
                "water_level_m": [10.0, 9.98, 9.98],
                "interpolation": "linear",
                "extrapolation": "error",
            },
        },
        "structures": {
            "gates": [
                {
                    "identity": {"namespace": "public.gate", "id": 51},
                    "branch_id": 21,
                    "interface": {
                        "upstream_section_id": 8,
                        "downstream_section_id": 9,
                    },
                    "opening_m": 0.05,
                    "width_m": 4.0,
                    "height_m": 2.0,
                    "discharge_coefficient": 0.62,
                    "allow_reverse_flow": False,
                    "control": {
                        "type": "one-shot-stage-above-bracketed-v1",
                        "threshold_water_level_m": 10.02,
                    },
                    "sill_elevation_m": 9.0,
                }
            ],
            "pumps": [
                {
                    "pump_model": "hydraulic-qh-external-sink-v1",
                    "identity": {"namespace": "public.pump", "id": 61},
                    "branch_id": 21,
                    "section_id": 16,
                    "outlet": "external",
                    "status": "off",
                    "head_curve": {
                        "points": [
                            {"flow_m3s": 0.0001, "head_m": 2.2},
                            {"flow_m3s": 0.0030, "head_m": 1.8},
                            {"flow_m3s": 0.0100, "head_m": 1.0},
                        ]
                    },
                    "efficiency_curve": {
                        "points": [
                            {"flow_m3s": 0.0001, "efficiency": 0.55},
                            {"flow_m3s": 0.0030, "efficiency": 0.82},
                            {"flow_m3s": 0.0100, "efficiency": 0.70},
                        ]
                    },
                    "unit_configuration": {
                        "total_units": 1,
                        "running_units": 1,
                        "minimum_running_units": 1,
                        "maximum_running_units": 1,
                    },
                    "system_loss": {
                        "static_loss_m": 0.1,
                        "quadratic_loss_coefficient_s2_m5": 1.0,
                    },
                    "outlet_stage": {
                        "time_seconds": [0.0, 21600.0],
                        "water_level_m": [11.5, 11.5],
                    },
                    "control": {
                        "type": "stage-hysteresis-min-runtime-v1",
                        "start_level_m": 9.982,
                        "stop_level_m": 9.978,
                        "minimum_run_seconds": 600.0,
                        "minimum_stop_seconds": 3000.0,
                        "maximum_starts": 2,
                    },
                }
            ],
        },
        "provenance": {
            "engine_version": "dayu-hydraulic-mvp",
            "engine_commit": "example-d1-frozen",
            "validation_policy_version": "v4-lite-7",
        },
    }


def main() -> None:
    """Run the frozen example and print a compact auditable summary."""

    document = HydraulicEngine().run(build_case()).to_dict()
    summary = {
        "events": [
            {
                "time": event["time"],
                "structure_type": event["structure_type"],
                "action": event["action"],
            }
            for event in document["control_events"]
        ],
        "step_count": document["diagnostics"]["step_count"],
        "relative_water_balance_error": document["water_balance"][
            "relative_water_balance_error"
        ],
        "pump_external_volume_m3": document["pump_coupling_evidence"][0][
            "total_external_volume_m3"
        ],
        "pump_input_energy_kwh": document["pump_coupling_evidence"][0][
            "total_input_energy_kwh"
        ],
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
