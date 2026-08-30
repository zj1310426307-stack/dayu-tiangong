"""Long-running D3A RC1 FINAL spatial and temporal convergence gate."""

from __future__ import annotations

import json
import os
from functools import lru_cache
from pathlib import Path

import pytest

from tests.reference.d3a_final_convergence import build_final_convergence_report

pytestmark = pytest.mark.d3a_shipping_science


@lru_cache(maxsize=1)
def _report() -> dict[str, object]:
    """Run the expensive matrix once for all independent assertions."""

    return build_final_convergence_report()


def test_final_levels_share_physics_controls_and_chainage_mapping() -> None:
    """Only spatial/time resolution may differ between FINAL levels."""

    report = _report()
    levels = report["levels"]
    spatial = levels[:3]
    assert [row["manifest"]["cell_count"] for row in spatial] == [60, 70, 80]
    assert len(
        {
            json.dumps(
                row["manifest"]["physical_functions"],
                sort_keys=True,
                separators=(",", ":"),
            )
            for row in spatial
        }
    ) == 1
    assert {
        row["manifest"]["boundary_and_control_identity"] for row in spatial
    } == {"d3a-rc1-final-boundary-control-v1"}
    assert all(
        row["manifest"]["gate"]["mapped_face_chainage_m"]
        == row["manifest"]["gate"]["target_chainage_m"]
        for row in spatial
    )


def test_final_smooth_metrics_converge_and_events_meet_frozen_tolerance() -> None:
    """Smooth differences decrease and non-smooth events remain within policy."""

    report = _report()
    comparisons = report["comparisons"]
    for metric, values in comparisons["smooth_metrics"].items():
        assert values["medium_fine_absolute"] < values[
            "coarse_medium_absolute"
        ], metric
    tolerance = report["frozen_tolerances"]["event_time_tolerance_s"]
    for metric, values in comparisons["event_metrics"].items():
        assert values["medium_fine_absolute_s"] <= values[
            "coarse_medium_absolute_s"
        ], metric
        assert values["medium_fine_absolute_s"] <= tolerance, metric
    coarse, medium, fine = report["levels"][:3]
    assert abs(
        fine["gate_upstream_peak_stage_m"]
        - medium["gate_upstream_peak_stage_m"]
    ) <= 5.0e-6
    assert abs(
        medium["gate_upstream_peak_stage_m"]
        - coarse["gate_upstream_peak_stage_m"]
    ) <= 5.0e-6


def test_final_envelope_residuals_and_friction_retry_ratio_all_pass() -> None:
    """Every level independently satisfies the frozen science gates."""

    report = _report()
    tolerances = report["frozen_tolerances"]
    for row in report["levels"]:
        assert row["runtime_envelope_status"] == "pass"
        assert row["minimum_water_depth_m"] > tolerances[
            "minimum_water_depth_m"
        ]
        assert row["minimum_discharge_m3s"] >= -tolerances[
            "reverse_flow_tolerance_m3s"
        ]
        assert row["maximum_froude_number"] <= tolerances[
            "maximum_froude_number"
        ]
        assert row["maximum_friction_number"] <= tolerances[
            "maximum_friction_number"
        ]
        assert (
            row["friction_retry_count"] / row["accepted_step_count"]
            < tolerances["maximum_friction_retry_ratio"]
        )
        assert row["relative_water_balance_error"] <= tolerances[
            "water_balance_relative"
        ]
        assert row["gate_maximum_energy_residual_m"] <= tolerances[
            "structure_residual_m"
        ]
        assert row["pump_maximum_head_residual_m"] <= tolerances[
            "structure_residual_m"
        ]


def test_final_time_refinement_reduces_actual_dt_without_material_degradation() -> None:
    """Half CFL must halve accepted dt and preserve the converged observables."""

    report = _report()
    fine, refined = report["levels"][2:]
    assert refined["accepted_maximum_dt_s"] < 0.51 * fine[
        "accepted_maximum_dt_s"
    ]
    assert abs(refined["gate_open_time_s"] - fine["gate_open_time_s"]) <= report[
        "frozen_tolerances"
    ]["event_time_tolerance_s"]
    assert refined["pump_start_time_s"] == fine["pump_start_time_s"]
    assert abs(
        refined["gate_transfer_volume_m3"] - fine["gate_transfer_volume_m3"]
    ) / fine["gate_transfer_volume_m3"] <= 0.005
    for metric in (
        "peak_discharge_m3s",
        "pump_external_volume_m3",
        "pump_input_energy_kwh",
    ):
        assert abs(refined[metric] - fine[metric]) / abs(fine[metric]) <= 0.002
    for metric in (
        "gate_downstream_peak_stage_m",
        "pump_source_peak_stage_m",
    ):
        assert abs(refined[metric] - fine[metric]) <= 0.002


def test_shipping_science_may_emit_the_validated_final_artifact() -> None:
    """Write the cached report only when the hosted science job requests it."""

    target = os.environ.get("D3A_FINAL_CONVERGENCE_ARTIFACT")
    if not target:
        pytest.skip("artifact emission is enabled only by shipping science")
    path = Path(target)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(_report(), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    assert path.is_file()
