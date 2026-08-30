"""Long-running D3A RC1 FIX1A spatial and temporal convergence gate."""

from __future__ import annotations

import json
import math
import os
from functools import lru_cache
from pathlib import Path

import pytest

from tests.reference.d3a_final_convergence_fix1 import (
    build_final_convergence_fix1a_report,
    build_grid_manifest,
)

pytestmark = pytest.mark.d3a_shipping_science


@lru_cache(maxsize=1)
def _report() -> dict[str, object]:
    """Run the expensive pre-frozen matrix once for all assertions."""

    return build_final_convergence_fix1a_report()


def test_fix1_grid_family_is_prefrozen_nested_and_exactly_aligned() -> None:
    """Reject location drift or a result-selected replacement grid."""

    manifests = [build_grid_manifest(level) for level in range(3)]
    assert [row["cell_count"] for row in manifests] == [18, 54, 162]
    assert [row["mesh_sha256"] for row in manifests] == [
        "7f65fd66aa5f58bc1e605c3775dc9bdc0660b5938f568dd68fa3b6341d0f5349",
        "221ac5e93d132a4da34cabb032a0835011e71a4cd3d6daa87c4326c42490a724",
        "eeac4f93b9a33130387b3988c90d241f53e11687e0595558b5a3896e2541676f",
    ]
    for row in manifests:
        assert row["grid_family_id"] == "structure-aligned-voronoi-odd3-v1"
        assert math.isclose(
            sum(row["cell_lengths_m"]),
            7600.0,
            rel_tol=0.0,
            abs_tol=1.0e-9,
        )
        for binding in ("gate", "pump", "monitor"):
            assert row[binding]["location_error_m"] == 0.0
    for parent, child in zip(manifests, manifests[1:]):
        assert set(parent["section_chainages_m"]).issubset(
            child["section_chainages_m"]
        )
        assert set(parent["face_chainages_m"]).issubset(
            child["face_chainages_m"]
        )


def test_fix1_levels_share_physics_controls_and_structure_locations() -> None:
    """Only the predeclared space/time resolution may differ."""

    report = _report()
    spatial = report["levels"][:3]
    assert report["schema_version"] == "dayu.d3a-final-convergence.v3"
    assert report["scenario_id"] == "d3a-rc1-fix1a-structure-aligned-v1"
    assert [row["manifest"]["cell_count"] for row in spatial] == [18, 54, 162]
    assert report["level_selection"]["refinement_ratios"] == [3.0, 3.0]
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
    for row in spatial:
        assert row["manifest"]["gate"]["location_error_m"] == 0.0
        assert row["manifest"]["pump"]["location_error_m"] == 0.0
        assert row["manifest"]["monitor"]["location_error_m"] == 0.0


def test_fix1_smooth_metrics_have_positive_order_and_richardson_error() -> None:
    """Require decreasing differences and finite positive empirical orders."""

    report = _report()
    assert "peak_monitor_discharge_m3s" in report["comparisons"][
        "smooth_metrics"
    ]
    assert "peak_discharge_m3s" not in report["comparisons"]["smooth_metrics"]
    for metric, values in report["comparisons"]["smooth_metrics"].items():
        assert values["trend_status"] == "pass", metric
        assert values["medium_fine_absolute"] < values[
            "coarse_medium_absolute"
        ], metric
        assert math.isfinite(values["observed_order"]), metric
        assert values["observed_order"] > 0.0, metric
        assert math.isfinite(values["asymptotic_limit"]), metric
        assert values["fine_grid_estimated_error"] >= 0.0, metric


def test_fix1a_global_peak_q_argmax_drift_is_non_smooth() -> None:
    """Record global peak coordinates and reject smooth-Q interpretation."""

    report = _report()
    values = report["comparisons"]["non_smooth_metrics"][
        "global_peak_discharge_m3s"
    ]
    assert values["classification"] == "non-smooth-global-extremum"
    assert values["argmax_drift_detected"] is True
    assert values["argmax_time_drift_detected"] is True
    assert values["argmax_chainage_drift_detected"] is True
    assert values["used_as_smooth_spatial_convergence_evidence"] is False
    observations = values["argmax_observations"]
    assert [row["time_s"] for row in observations] == [7200.0, 4500.0, 4500.0]
    assert [row["section_chainage_m"] for row in observations] == pytest.approx(
        [250.0, 1250.0, 972.2222222222222],
        rel=0.0,
        abs=1.0e-12,
    )
    assert [row["absolute_discharge_m3s"] for row in observations] == pytest.approx(
        [0.22199067209519152, 0.2454131571144132, 0.26221666161760204]
    )
    legacy = values["legacy_fix1_richardson_diagnostic"]
    assert legacy["observed_order"] == pytest.approx(0.30229863314305244)
    assert legacy["fine_grid_estimated_relative_error"] == pytest.approx(
        0.1399220503200914
    )
    limitation = report["known_limitations"][0]
    assert limitation[
        "fix1_legacy_fine_grid_estimated_relative_error_percent"
    ] == 13.99


def test_fix1a_fixed_monitor_q_has_positive_spatial_order() -> None:
    """Use peak Q at the exact 2850 m monitor as the comparable Q metric."""

    report = _report()
    spatial = report["levels"][:3]
    for row in spatial:
        observation = row["fixed_monitor_peak_discharge"]
        assert observation["section_chainage_m"] == 2850.0
        assert observation["control_volume_centroid_m"] == 2850.0
        assert observation["discharge_m3s"] == row[
            "peak_monitor_discharge_m3s"
        ]
    convergence = report["comparisons"]["smooth_metrics"][
        "peak_monitor_discharge_m3s"
    ]
    assert convergence["trend_status"] == "pass"
    assert convergence["observed_order"] > 0.7


def test_fix1_event_spatial_error_is_separate_from_locator_tolerance() -> None:
    """Gate-event spatial convergence must stand without the 5 s locator gate."""

    report = _report()
    values = report["comparisons"]["event_metrics"]["gate_open_time_s"]
    assert values["classification"] == "non-smooth-threshold-event"
    assert values["locator_tolerance_seconds"] == 5.0
    assert values["locator_tolerance_is_spatial_error"] is False
    assert values["trend_status"] == "pass"
    assert values["medium_fine_absolute"] < values["coarse_medium_absolute"]
    assert values["fine_grid_estimated_error"] is not None
    pump = report["comparisons"]["schedule_locked_events"]["pump_start_time_s"]
    assert pump["used_as_spatial_convergence_evidence"] is False


def test_fix1_envelope_residuals_and_friction_retry_ratio_all_pass() -> None:
    """Every level independently satisfies the unchanged science gates."""

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


def test_fix1_time_refinement_reduces_actual_dt_without_degradation() -> None:
    """Half CFL must halve accepted dt and preserve converged observables."""

    report = _report()
    fine, refined = report["levels"][2:]
    tolerances = report["frozen_tolerances"]
    assert refined["accepted_maximum_dt_s"] <= 0.51 * fine[
        "accepted_maximum_dt_s"
    ]
    assert abs(refined["gate_open_time_s"] - fine["gate_open_time_s"]) <= tolerances[
        "event_locator_tolerance_s"
    ]
    assert refined["pump_start_time_s"] == fine["pump_start_time_s"]
    assert abs(
        refined["gate_transfer_volume_m3"] - fine["gate_transfer_volume_m3"]
    ) / abs(fine["gate_transfer_volume_m3"]) <= tolerances[
        "time_gate_transfer_relative"
    ]
    for metric in (
        "peak_monitor_discharge_m3s",
        "peak_discharge_m3s",
        "pump_external_volume_m3",
        "pump_input_energy_kwh",
    ):
        assert abs(refined[metric] - fine[metric]) / abs(fine[metric]) <= tolerances[
            "time_other_integral_relative"
        ]
    for metric in (
        "gate_downstream_peak_stage_m",
        "pump_source_peak_stage_m",
    ):
        assert abs(refined[metric] - fine[metric]) <= tolerances[
            "time_stage_absolute_m"
        ]


def test_fix1_completion_status_and_artifact_emission() -> None:
    """Emit the report when requested and require every FIX1 completion gate."""

    report = _report()
    target = os.environ.get("D3A_FINAL_CONVERGENCE_FIX1A_ARTIFACT")
    if target:
        path = Path(target)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(report, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        assert path.is_file()
    assert report["status"] == "pass"
    assert all(report["completion_gates"].values())
