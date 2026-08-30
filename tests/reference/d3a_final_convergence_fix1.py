"""Pre-frozen structure-aligned D3A FINAL convergence evidence.

This FIX1 reference intentionally lives beside, rather than replacing, the
pre-FIX1 60/70/80 reference.  The old case remains useful as a historical
smoke test, but it is not release convergence evidence.
"""

from __future__ import annotations

import hashlib
import json
import math
import runpy
import time
from copy import deepcopy
from fractions import Fraction
from pathlib import Path
from typing import Final

from model import HydraulicEngine


DOMAIN_LENGTH_M: Final = 7_600.0
GATE_CHAINAGE_M: Final = 3_040.0
PUMP_CHAINAGE_M: Final = 6_000.0
MONITOR_CHAINAGE_M: Final = 2_850.0
EVENT_LOCATOR_TOLERANCE_S: Final = 5.0
GRID_FAMILY_ID: Final = "structure-aligned-voronoi-odd3-v1"
BOUNDARY_CONTROL_ID: Final = "d3a-rc1-final-boundary-control-v1"

# Frozen before any FIX1 simulation.  The monitor site and its neighbours are
# symmetric (2470/2850/3230); its right face is therefore the exact Gate face.
# The Pump site and neighbours are symmetric (5700/6000/6300).  Endpoint
# distances are half their adjacent site gaps, which makes boundary refinement
# exactly self-similar under the odd factor-three rule.
_BASE_SECTION_SITES: Final = (
    Fraction(250),
    Fraction(750),
    Fraction(1_250),
    Fraction(1_750),
    Fraction(2_150),
    Fraction(2_470),
    Fraction(2_850),
    Fraction(3_230),
    Fraction(3_600),
    Fraction(4_200),
    Fraction(4_800),
    Fraction(5_400),
    Fraction(5_700),
    Fraction(6_000),
    Fraction(6_300),
    Fraction(6_600),
    Fraction(6_900),
    Fraction(22_100, 3),
)
_SPATIAL_LEVELS: Final = (
    ("coarse", 0),
    ("medium", 1),
    ("fine", 2),
)
_FIX1A_SMOOTH_METRICS: Final = (
    "gate_downstream_peak_stage_m",
    "pump_source_peak_stage_m",
    "peak_monitor_discharge_m3s",
    "gate_transfer_volume_m3",
    "pump_external_volume_m3",
    "pump_input_energy_kwh",
)


def bed_elevation_m(chainage_m: float) -> float:
    """Return the frozen physical descending-bed function."""

    return 9.0 - 1.0e-7 * chainage_m


def profile_width_m(chainage_m: float) -> float:
    """Return the frozen gradual contraction/expansion function."""

    return 20.0 * (
        1.0 - 0.12 * math.sin(math.pi * chainage_m / DOMAIN_LENGTH_M)
    )


def manning_n(chainage_m: float) -> float:
    """Return the frozen section-effective Manning function."""

    if not 0.0 <= chainage_m <= DOMAIN_LENGTH_M:
        raise ValueError("Manning chainage lies outside the FIX1 FINAL domain")
    return 0.025


def initial_water_level_m(chainage_m: float) -> float:
    """Return the frozen two-pool initial stage separated by the Gate."""

    return 10.0 if chainage_m < GATE_CHAINAGE_M else 9.8


def _base_case() -> dict:
    """Load established D3A-3 controls while replacing only mesh data."""

    path = (
        Path(__file__).parents[2]
        / "examples"
        / "hydraulic"
        / "gate-pump-engineering-profiles"
        / "case.py"
    )
    return runpy.run_path(str(path))["build_case"]()


def _refine_sites_once(sites: tuple[Fraction, ...]) -> tuple[Fraction, ...]:
    """Keep every parent site/face and split every site gap by three."""

    if len(sites) < 2:
        raise ValueError("FIX1 grid needs at least two section sites")
    refined = [sites[0] / 3]
    for left, right in zip(sites, sites[1:]):
        gap = right - left
        refined.extend((left, left + gap / 3, left + 2 * gap / 3))
    boundary = Fraction(int(DOMAIN_LENGTH_M))
    refined.extend((sites[-1], boundary - (boundary - sites[-1]) / 3))
    result = tuple(refined)
    if len(result) != 3 * len(sites):
        raise AssertionError("odd3 refinement did not triple the section count")
    if any(right <= left for left, right in zip(result, result[1:])):
        raise AssertionError("odd3 refinement produced unordered sites")
    return result


def section_sites(refinement_level: int) -> tuple[Fraction, ...]:
    """Return the pre-frozen exact-rational section sites for one level."""

    if refinement_level not in (0, 1, 2):
        raise ValueError("FIX1 refinement_level must be 0, 1, or 2")
    sites = _BASE_SECTION_SITES
    for _ in range(refinement_level):
        sites = _refine_sites_once(sites)
    return sites


def _mesh_coordinates(
    sites: tuple[Fraction, ...],
) -> tuple[tuple[Fraction, ...], tuple[Fraction, ...], tuple[Fraction, ...]]:
    """Build the exact faces, cell lengths and geometric centroids."""

    boundary = Fraction(int(DOMAIN_LENGTH_M))
    faces = (
        Fraction(0),
        *((left + right) / 2 for left, right in zip(sites, sites[1:])),
        boundary,
    )
    lengths = tuple(right - left for left, right in zip(faces, faces[1:]))
    centroids = tuple((left + right) / 2 for left, right in zip(faces, faces[1:]))
    if any(length <= 0 for length in lengths):
        raise AssertionError("FIX1 mesh contains a non-positive control volume")
    if sum(lengths) != boundary:
        raise AssertionError("FIX1 mesh does not preserve the Branch length")
    return faces, lengths, centroids


def _canonical_sha256(value: object) -> str:
    """Hash one deterministic canonical-JSON value."""

    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _find_exact(values: tuple[Fraction, ...], target: int, label: str) -> int:
    """Resolve an exact physical coordinate without nearest-neighbour logic."""

    matches = [index for index, value in enumerate(values) if value == target]
    if len(matches) != 1:
        raise AssertionError(f"FIX1 {label} must have exactly one exact binding")
    return matches[0]


def _fixed_monitor_peak_discharge_observation(
    monitor: dict[str, object],
    manifest: dict[str, object],
) -> dict[str, object]:
    """Locate peak signed Q at the exact fixed monitor and record its time."""

    section_id = int(monitor["section_id"])
    samples = tuple(
        (sample_index, float(time_s), float(discharge_m3s))
        for sample_index, (time_s, discharge_m3s) in enumerate(
            zip(monitor["time"], monitor["flow"], strict=True)
        )
    )
    sample_index, time_s, discharge_m3s = max(
        samples,
        key=lambda sample: sample[2],
    )
    return {
        "discharge_m3s": discharge_m3s,
        "time_s": time_s,
        "sample_index": sample_index,
        "section_id": section_id,
        "section_chainage_m": float(
            manifest["section_chainages_m"][section_id - 1]
        ),
        "control_volume_centroid_m": float(
            manifest["control_volume_centroids_m"][section_id - 1]
        ),
    }


def _global_peak_discharge_observation(
    sections: list[dict[str, object]],
    manifest: dict[str, object],
) -> dict[str, object]:
    """Locate the deterministic global abs(Q) argmax in space and time."""

    samples = tuple(
        (
            abs(float(discharge_m3s)),
            float(discharge_m3s),
            float(time_s),
            int(section["section_id"]),
            sample_index,
        )
        for section in sections
        for sample_index, (time_s, discharge_m3s) in enumerate(
            zip(section["time"], section["flow"], strict=True)
        )
    )
    absolute_m3s, signed_m3s, time_s, section_id, sample_index = max(
        samples,
        key=lambda sample: sample[0],
    )
    exact_tie_count = sum(
        sample[0] == absolute_m3s for sample in samples
    )
    return {
        "absolute_discharge_m3s": absolute_m3s,
        "signed_discharge_m3s": signed_m3s,
        "time_s": time_s,
        "sample_index": sample_index,
        "section_id": section_id,
        "section_chainage_m": float(
            manifest["section_chainages_m"][section_id - 1]
        ),
        "control_volume_centroid_m": float(
            manifest["control_volume_centroids_m"][section_id - 1]
        ),
        "exact_tie_count": exact_tie_count,
        "selection_policy": (
            "maximum absolute discharge; first section/time sample on exact tie"
        ),
    }


def build_grid_manifest(refinement_level: int) -> dict[str, object]:
    """Build the complete coordinate manifest used by payload and artifact."""

    sites = section_sites(refinement_level)
    faces, lengths, centroids = _mesh_coordinates(sites)
    gate_face_index = _find_exact(faces, int(GATE_CHAINAGE_M), "Gate face")
    pump_index = _find_exact(centroids, int(PUMP_CHAINAGE_M), "Pump centroid")
    monitor_index = _find_exact(
        centroids,
        int(MONITOR_CHAINAGE_M),
        "monitor centroid",
    )
    coordinate_manifest = {
        "schema_version": "dayu.d3a-grid-manifest.v1",
        "grid_family_id": GRID_FAMILY_ID,
        "refinement_level": refinement_level,
        "refinement_factor": 3,
        "cell_count": len(sites),
        "domain_start_m": 0.0,
        "domain_end_m": DOMAIN_LENGTH_M,
        "section_chainages_m": [float(value) for value in sites],
        "face_chainages_m": [float(value) for value in faces],
        "cell_lengths_m": [float(value) for value in lengths],
        "control_volume_centroids_m": [float(value) for value in centroids],
    }
    mesh_hash = _canonical_sha256(coordinate_manifest)
    return {
        **coordinate_manifest,
        "mesh_sha256": mesh_hash,
        "representative_spacing_m": DOMAIN_LENGTH_M / len(sites),
        "minimum_cell_length_m": float(min(lengths)),
        "maximum_cell_length_m": float(max(lengths)),
        "physical_functions": {
            "bed_elevation_m": "9.0 - 1e-7*x",
            "profile_width_m": "20*(1 - 0.12*sin(pi*x/7600))",
            "manning_n": "0.025",
            "initial_water_level_m": "10.0 if x<3040 else 9.8",
        },
        "gate": {
            "binding": "exact-internal-face",
            "target_chainage_m": GATE_CHAINAGE_M,
            "mapped_face_chainage_m": float(faces[gate_face_index]),
            "location_error_m": float(faces[gate_face_index]) - GATE_CHAINAGE_M,
            "face_index": gate_face_index,
            "upstream_section_id": gate_face_index,
            "downstream_section_id": gate_face_index + 1,
        },
        "pump": {
            "binding": "exact-control-volume-centroid",
            "target_chainage_m": PUMP_CHAINAGE_M,
            "mapped_control_volume_centroid_m": float(centroids[pump_index]),
            "section_chainage_m": float(sites[pump_index]),
            "location_error_m": float(centroids[pump_index]) - PUMP_CHAINAGE_M,
            "section_id": pump_index + 1,
            "control_volume_bounds_m": [
                float(faces[pump_index]),
                float(faces[pump_index + 1]),
            ],
        },
        "monitor": {
            "binding": "exact-control-volume-centroid",
            "target_chainage_m": MONITOR_CHAINAGE_M,
            "mapped_control_volume_centroid_m": float(centroids[monitor_index]),
            "section_chainage_m": float(sites[monitor_index]),
            "location_error_m": float(centroids[monitor_index]) - MONITOR_CHAINAGE_M,
            "section_id": monitor_index + 1,
            "control_volume_bounds_m": [
                float(faces[monitor_index]),
                float(faces[monitor_index + 1]),
            ],
        },
        "boundary_and_control_identity": BOUNDARY_CONTROL_ID,
    }


def build_final_case_fix1(
    refinement_level: int,
    *,
    maximum_time_step_seconds: float = 60.0,
    cfl_number: float = 0.7,
) -> tuple[dict, dict[str, object]]:
    """Sample the frozen physical case on one structure-aligned mesh."""

    if maximum_time_step_seconds <= 0.0:
        raise ValueError("maximum_time_step_seconds must be positive")
    if not 0.0 < cfl_number <= 1.0:
        raise ValueError("cfl_number must lie in (0, 1]")
    payload = deepcopy(_base_case())
    manifest = build_grid_manifest(refinement_level)
    chainages = tuple(float(value) for value in section_sites(refinement_level))
    cell_count = len(chainages)
    sections: list[dict[str, object]] = []
    initial_values: list[dict[str, float | int]] = []
    for index, chainage in enumerate(chainages):
        section_id = index + 1
        bed = bed_elevation_m(chainage)
        width = profile_width_m(chainage)
        sections.append(
            {
                "section_id": section_id,
                "section_code": f"FIX1-{cell_count}-{section_id:03d}",
                "branch_id": 21,
                "chainage_m": chainage,
                "profile_id": 1_000_000 + cell_count * 1_000 + section_id,
                "profile_hash": f"{1_000_000 + cell_count * 1000 + section_id:064x}",
                "default_manning_n": manning_n(chainage),
                "bed_elevation_m": bed,
                "bed_elevation_source": "synthetic",
                "bed_elevation_confirmed_by": "HYDRO-MODEL-02-D3A-RC1-FIX1",
                "bed_elevation_confirmed_at": "2026-08-30T00:00:00Z",
                "points": [
                    {"offset_m": 0.0, "elevation_m": bed + 3.0},
                    {"offset_m": 0.5 * width, "elevation_m": bed},
                    {"offset_m": width, "elevation_m": bed + 3.0},
                ],
            }
        )
        initial_values.append(
            {
                "section_id": section_id,
                "water_level_m": initial_water_level_m(chainage),
                "discharge_m3_s": 0.0,
            }
        )
    payload["sections"] = sections
    payload["initial_state"] = {"type": "by-section", "values": initial_values}
    payload["solver"]["maximum_time_step_seconds"] = maximum_time_step_seconds
    payload["solver"]["cfl_number"] = cfl_number
    payload["structures"]["gates"][0]["control"][
        "threshold_water_level_m"
    ] = 10.02
    payload["structures"]["gates"][0]["interface"] = {
        "upstream_section_id": manifest["gate"]["upstream_section_id"],
        "downstream_section_id": manifest["gate"]["downstream_section_id"],
    }
    payload["structures"]["gates"][0]["sill_elevation_m"] = 9.0
    payload["structures"]["pumps"][0]["section_id"] = manifest["pump"][
        "section_id"
    ]
    pump_control = payload["structures"]["pumps"][0]["control"]
    pump_control["start_level_m"] = 9.7
    pump_control["stop_level_m"] = 9.69
    upstream = payload["boundary"]["upstream"]
    upstream["time_seconds"] = [
        0.0,
        1800.0,
        4000.0,
        5400.0,
        9000.0,
        12600.0,
        16200.0,
        21600.0,
    ]
    upstream["flow_m3_s"] = [
        0.10,
        0.15,
        0.15 + (0.25 - 0.15) * (4000.0 - 1800.0) / (5400.0 - 1800.0),
        0.25,
        0.25,
        0.12,
        0.06,
        0.06,
    ]
    downstream = payload["boundary"]["downstream"]
    downstream["time_seconds"] = [0.0, 1800.0, 4000.0, 21600.0]
    downstream["water_level_m"] = [9.79, 9.79, 9.79, 9.79]
    payload["provenance"]["engine_commit"] = "d3a-rc1-fix1-final-convergence"
    manifest["maximum_time_step_seconds"] = maximum_time_step_seconds
    manifest["cfl_number"] = cfl_number
    manifest["event_locator_tolerance_seconds"] = payload["solver"][
        "event_time_tolerance_seconds"
    ]
    return payload, manifest


def run_final_level_fix1(
    level: str,
    refinement_level: int,
    *,
    maximum_time_step_seconds: float = 60.0,
    cfl_number: float = 0.7,
) -> dict[str, object]:
    """Execute one FIX1 level and collect release observables."""

    payload, manifest = build_final_case_fix1(
        refinement_level,
        maximum_time_step_seconds=maximum_time_step_seconds,
        cfl_number=cfl_number,
    )
    started = time.perf_counter()
    document = HydraulicEngine().run(payload).to_dict()
    runtime_seconds = time.perf_counter() - started
    monitor_id = int(manifest["monitor"]["section_id"])
    monitor = next(
        section
        for section in document["sections"]
        if section["section_id"] == monitor_id
    )
    events = {
        f"{event['structure_type']}_{event['action']}_time_s": event["time"]
        for event in document["control_events"]
    }
    gate = document["controlled_gate_coupling_evidence"][0]
    pump = document["pump_coupling_evidence"][0]
    fixed_monitor_peak = _fixed_monitor_peak_discharge_observation(
        monitor,
        manifest,
    )
    global_peak = _global_peak_discharge_observation(
        document["sections"],
        manifest,
    )
    accepted_dts = tuple(
        row["dt"] for row in pump["stage_evaluations"] if row["rk_stage"] == 1
    )
    diagnostics = document["diagnostics"]
    return {
        "level": level,
        "manifest": manifest,
        "runtime_seconds": runtime_seconds,
        "accepted_step_count": diagnostics["step_count"],
        "accepted_minimum_dt_s": diagnostics["minimum_dt"],
        "accepted_maximum_dt_s": max(accepted_dts),
        "retry_count": diagnostics["retry_count"],
        "friction_retry_count": diagnostics["friction_retry_count"],
        "friction_predictor_reduction_count": diagnostics[
            "friction_predictor_reduction_count"
        ],
        "runtime_envelope_retry_count": diagnostics[
            "runtime_envelope_retry_count"
        ],
        "positivity_or_stage_stability_retry_count": (
            diagnostics["retry_count"]
            - diagnostics["friction_retry_count"]
            - diagnostics["runtime_envelope_retry_count"]
        ),
        "runtime_envelope_status": diagnostics["runtime_envelope_status"],
        "minimum_water_depth_m": diagnostics["minimum_water_depth_m"],
        "minimum_discharge_m3s": diagnostics["minimum_discharge_m3s"],
        "maximum_froude_number": diagnostics["maximum_froude_number"],
        "maximum_friction_number": diagnostics["maximum_friction_number"],
        "peak_monitor_stage_m": max(monitor["water_level"]),
        "peak_monitor_discharge_m3s": fixed_monitor_peak["discharge_m3s"],
        "peak_monitor_discharge_time_s": fixed_monitor_peak["time_s"],
        "fixed_monitor_peak_discharge": fixed_monitor_peak,
        "peak_discharge_m3s": global_peak["absolute_discharge_m3s"],
        "global_peak_discharge_argmax": global_peak,
        "gate_upstream_peak_stage_m": max(
            row["upstream_stage"] for row in gate["stage_evaluations"]
        ),
        "gate_downstream_peak_stage_m": max(
            row["downstream_stage"] for row in gate["stage_evaluations"]
        ),
        "pump_source_peak_stage_m": max(
            row["source_stage_m"] for row in pump["stage_evaluations"]
        ),
        "final_monitor_stage_m": monitor["water_level"][-1],
        "final_monitor_discharge_m3s": monitor["flow"][-1],
        "gate_transfer_volume_m3": gate["total_transfer_volume"],
        "pump_external_volume_m3": pump["total_external_volume_m3"],
        "pump_input_energy_kwh": pump["total_input_energy_kwh"],
        "relative_water_balance_error": document["water_balance"][
            "relative_water_balance_error"
        ],
        "gate_maximum_energy_residual_m": gate[
            "maximum_absolute_energy_residual"
        ],
        "pump_maximum_head_residual_m": pump[
            "maximum_absolute_head_residual_m"
        ],
        **events,
    }


def _convergence_entry(
    coarse_value: float,
    medium_value: float,
    fine_value: float,
    *,
    units: str,
) -> dict[str, object]:
    """Calculate differences, empirical order and Richardson fine error."""

    coarse_medium = abs(medium_value - coarse_value)
    medium_fine = abs(fine_value - medium_value)
    trend_pass = (
        math.isfinite(coarse_medium)
        and math.isfinite(medium_fine)
        and coarse_medium > 0.0
        and medium_fine > 0.0
        and medium_fine < coarse_medium
    )
    if not trend_pass:
        return {
            "units": units,
            "coarse_medium_absolute": coarse_medium,
            "medium_fine_absolute": medium_fine,
            "difference_ratio": None,
            "observed_order": None,
            "asymptotic_limit": None,
            "fine_grid_estimated_error": None,
            "fine_grid_estimated_relative_error": None,
            "trend_status": "fail",
        }
    difference_ratio = coarse_medium / medium_fine
    observed_order = math.log(difference_ratio) / math.log(3.0)
    denominator = 3.0**observed_order - 1.0
    limit = fine_value + (fine_value - medium_value) / denominator
    estimated_error = abs(limit - fine_value)
    relative_error = (
        estimated_error / abs(limit) if abs(limit) > 0.0 else None
    )
    finite_positive_order = math.isfinite(observed_order) and observed_order > 0.0
    return {
        "units": units,
        "coarse_medium_absolute": coarse_medium,
        "medium_fine_absolute": medium_fine,
        "difference_ratio": difference_ratio,
        "observed_order": observed_order,
        "preferred_order_at_least_0_7": observed_order >= 0.7,
        "asymptotic_limit": limit,
        "fine_grid_estimated_error": estimated_error,
        "fine_grid_estimated_relative_error": relative_error,
        "trend_status": "pass" if finite_positive_order else "fail",
    }


def _level_gate_status(row: dict[str, object], tolerances: dict[str, float]) -> bool:
    """Apply the unchanged envelope, friction, balance and residual gates."""

    return bool(
        row["runtime_envelope_status"] == "pass"
        and row["minimum_water_depth_m"] > tolerances["minimum_water_depth_m"]
        and row["minimum_discharge_m3s"]
        >= -tolerances["reverse_flow_tolerance_m3s"]
        and row["maximum_froude_number"]
        <= tolerances["maximum_froude_number"]
        and row["maximum_friction_number"]
        <= tolerances["maximum_friction_number"]
        and row["friction_retry_count"] / row["accepted_step_count"]
        < tolerances["maximum_friction_retry_ratio"]
        and row["relative_water_balance_error"]
        <= tolerances["water_balance_relative"]
        and row["gate_maximum_energy_residual_m"]
        <= tolerances["structure_residual_m"]
        and row["pump_maximum_head_residual_m"]
        <= tolerances["structure_residual_m"]
    )


def build_final_convergence_fix1a_report() -> dict[str, object]:
    """Run the frozen matrix and return the FIX1A version-three artifact."""

    levels = tuple(
        run_final_level_fix1(label, refinement)
        for label, refinement in _SPATIAL_LEVELS
    ) + (run_final_level_fix1("fine-time-refined", 2, cfl_number=0.35),)
    coarse, medium, fine, refined = levels
    smooth = {
        metric: _convergence_entry(
            float(coarse[metric]),
            float(medium[metric]),
            float(fine[metric]),
            units=(
                "m"
                if metric.endswith("stage_m")
                else "m3/s"
                if metric.endswith("discharge_m3s")
                else "m3"
                if metric.endswith("volume_m3")
                else "kWh"
            ),
        )
        for metric in _FIX1A_SMOOTH_METRICS
    }
    legacy_global_peak_q = _convergence_entry(
        float(coarse["peak_discharge_m3s"]),
        float(medium["peak_discharge_m3s"]),
        float(fine["peak_discharge_m3s"]),
        units="m3/s",
    )
    argmax_observations = [
        {
            "level": row["level"],
            **deepcopy(row["global_peak_discharge_argmax"]),
        }
        for row in levels[:3]
    ]
    argmax_time_drift = len(
        {row["time_s"] for row in argmax_observations}
    ) > 1
    argmax_chainage_drift = len(
        {row["section_chainage_m"] for row in argmax_observations}
    ) > 1
    argmax_drift = argmax_time_drift or argmax_chainage_drift
    legacy_relative_error = legacy_global_peak_q[
        "fine_grid_estimated_relative_error"
    ]
    legacy_relative_error_percent = (
        round(float(legacy_relative_error) * 100.0, 2)
        if legacy_relative_error is not None
        else None
    )
    global_peak_q = {
        "classification": (
            "non-smooth-global-extremum"
            if argmax_drift
            else "smooth-candidate-requires-additional-refinement"
        ),
        "argmax_drift_detected": argmax_drift,
        "argmax_time_drift_detected": argmax_time_drift,
        "argmax_chainage_drift_detected": argmax_chainage_drift,
        "argmax_observations": argmax_observations,
        "used_as_smooth_spatial_convergence_evidence": False,
        "no_drift_action": (
            "fail closed and add a pre-frozen finer level before acceptance"
        ),
        "legacy_fix1_richardson_diagnostic": legacy_global_peak_q,
        "legacy_fix1_diagnostic_is_valid_smooth_error_bound": False,
    }
    gate_event = _convergence_entry(
        float(coarse["gate_open_time_s"]),
        float(medium["gate_open_time_s"]),
        float(fine["gate_open_time_s"]),
        units="s",
    )
    gate_event.update(
        {
            "classification": "non-smooth-threshold-event",
            "order_interpretation": "empirical event trend, not smooth PDE order",
            "locator_tolerance_seconds": EVENT_LOCATOR_TOLERANCE_S,
            "locator_tolerance_is_spatial_error": False,
        }
    )
    time_metrics = tuple(
        dict.fromkeys(
            (
                *_FIX1A_SMOOTH_METRICS,
                "peak_discharge_m3s",
                "gate_open_time_s",
                "pump_start_time_s",
            )
        )
    )
    time_comparison = {
        "accepted_maximum_dt_ratio": (
            float(refined["accepted_maximum_dt_s"])
            / float(fine["accepted_maximum_dt_s"])
        ),
        **{
            f"{metric}_absolute": abs(
                float(refined[metric]) - float(fine[metric])
            )
            for metric in time_metrics
        },
        "global_peak_q_argmax": {
            "fine": deepcopy(fine["global_peak_discharge_argmax"]),
            "fine_time_refined": deepcopy(
                refined["global_peak_discharge_argmax"]
            ),
            "same_section_chainage": (
                fine["global_peak_discharge_argmax"]["section_chainage_m"]
                == refined["global_peak_discharge_argmax"]["section_chainage_m"]
            ),
            "time_absolute_difference_s": abs(
                float(fine["global_peak_discharge_argmax"]["time_s"])
                - float(refined["global_peak_discharge_argmax"]["time_s"])
            ),
        },
    }
    tolerances = {
        "event_locator_tolerance_s": EVENT_LOCATOR_TOLERANCE_S,
        "maximum_froude_number": 0.8,
        "minimum_water_depth_m": 1.0e-3,
        "reverse_flow_tolerance_m3s": 1.0e-12,
        "maximum_friction_number": 0.1,
        "maximum_friction_retry_ratio": 0.25,
        "water_balance_relative": 1.0e-10,
        "structure_residual_m": 1.0e-10,
        "time_gate_transfer_relative": 0.005,
        "time_other_integral_relative": 0.002,
        "time_stage_absolute_m": 0.002,
    }
    time_status = bool(
        time_comparison["accepted_maximum_dt_ratio"] <= 0.51
        and time_comparison["gate_open_time_s_absolute"]
        <= tolerances["event_locator_tolerance_s"]
        and refined["pump_start_time_s"] == fine["pump_start_time_s"]
        and time_comparison["gate_transfer_volume_m3_absolute"]
        / abs(float(fine["gate_transfer_volume_m3"]))
        <= tolerances["time_gate_transfer_relative"]
        and all(
            time_comparison[f"{metric}_absolute"] / abs(float(fine[metric]))
            <= tolerances["time_other_integral_relative"]
            for metric in (
                "peak_monitor_discharge_m3s",
                "peak_discharge_m3s",
                "pump_external_volume_m3",
                "pump_input_energy_kwh",
            )
        )
        and all(
            time_comparison[f"{metric}_absolute"]
            <= tolerances["time_stage_absolute_m"]
            for metric in (
                "gate_downstream_peak_stage_m",
                "pump_source_peak_stage_m",
            )
        )
    )
    location_status = all(
        row["manifest"][binding]["location_error_m"] == 0.0
        for row in levels
        for binding in ("gate", "pump", "monitor")
    )
    fixed_monitor_status = all(
        row["fixed_monitor_peak_discharge"]["section_chainage_m"]
        == MONITOR_CHAINAGE_M
        and row["fixed_monitor_peak_discharge"][
            "control_volume_centroid_m"
        ]
        == MONITOR_CHAINAGE_M
        for row in levels
    )
    spatial_counts = [row["manifest"]["cell_count"] for row in levels[:3]]
    refinement_status = bool(
        spatial_counts == [18, 54, 162]
        and [
            fine_count / coarse_count
            for coarse_count, fine_count in zip(
                spatial_counts,
                spatial_counts[1:],
            )
        ]
        == [3.0, 3.0]
    )
    smooth_status = all(row["trend_status"] == "pass" for row in smooth.values())
    event_status = gate_event["trend_status"] == "pass"
    global_peak_classification_status = bool(
        argmax_drift
        and global_peak_q["classification"] == "non-smooth-global-extremum"
        and global_peak_q["used_as_smooth_spatial_convergence_evidence"] is False
    )
    known_limitation_status = legacy_relative_error_percent == 13.99
    envelope_status = all(_level_gate_status(row, tolerances) for row in levels)
    completion_gates = {
        "grid_locations_exact": location_status,
        "refinement_ratio_at_least_1_5": refinement_status,
        "fixed_monitor_q_spatial_convergence": fixed_monitor_status
        and smooth["peak_monitor_discharge_m3s"]["trend_status"] == "pass",
        "smooth_spatial_convergence": smooth_status,
        "global_peak_q_argmax_classified": global_peak_classification_status,
        "known_limitation_13_99_percent_recorded": known_limitation_status,
        "event_spatial_convergence": event_status,
        "event_locator_error_separated": True,
        "fine_grid_time_refinement": time_status,
        "envelope_balance_residual_friction": envelope_status,
    }
    status = "pass" if all(completion_gates.values()) else "fail"
    return {
        "schema_version": "dayu.d3a-final-convergence.v3",
        "scenario_id": "d3a-rc1-fix1a-structure-aligned-v1",
        "status": status,
        "pre_fix1_artifact": {
            "path": "outputs/d3a/final-convergence.json",
            "classification": "superseded-pre-FIX1",
        },
        "pre_fix1a_artifact": {
            "path": "outputs/d3a/final-convergence-fix1.json",
            "classification": "superseded-FIX1-peak-Q-interpretation",
        },
        "level_selection": {
            "grid_family_id": GRID_FAMILY_ID,
            "cell_counts": [18, 54, 162],
            "refinement_ratios": [3.0, 3.0],
            "selection_timing": "frozen-before-FIX1-simulation; unchanged in FIX1A",
            "reason": (
                "odd factor-three refinement preserves both parent sites and "
                "parent faces; an even refinement cannot simultaneously preserve "
                "the exact Pump/monitor centroids and exact Gate face"
            ),
            "time_refinement": "fine CFL target 0.7 -> 0.35",
        },
        "frozen_tolerances": tolerances,
        "levels": list(levels),
        "comparisons": {
            "smooth_metrics": smooth,
            "non_smooth_metrics": {
                "global_peak_discharge_m3s": global_peak_q,
            },
            "event_metrics": {"gate_open_time_s": gate_event},
            "schedule_locked_events": {
                "pump_start_time_s": {
                    "classification": "boundary-knot/schedule-locked",
                    "values_s": [row["pump_start_time_s"] for row in levels[:3]],
                    "used_as_spatial_convergence_evidence": False,
                }
            },
            "fine_time_refinement": time_comparison,
        },
        "known_limitations": [
            {
                "id": "global-peak-Q-argmax-drift",
                "status": "active",
                "classification": "non-smooth-global-extremum",
                "fix1_legacy_observed_order": legacy_global_peak_q[
                    "observed_order"
                ],
                "fix1_legacy_fine_grid_estimated_relative_error": (
                    legacy_relative_error
                ),
                "fix1_legacy_fine_grid_estimated_relative_error_percent": (
                    legacy_relative_error_percent
                ),
                "interpretation": (
                    "13.99% is retained as a known historical diagnostic; "
                    "argmax drift invalidates it as a smooth Richardson error bound"
                ),
            }
        ],
        "completion_gates": completion_gates,
    }


def build_final_convergence_fix1_report() -> dict[str, object]:
    """Return the current FIX1A report through the legacy helper entry point."""

    return build_final_convergence_fix1a_report()


__all__ = [
    "BOUNDARY_CONTROL_ID",
    "DOMAIN_LENGTH_M",
    "EVENT_LOCATOR_TOLERANCE_S",
    "GATE_CHAINAGE_M",
    "GRID_FAMILY_ID",
    "MONITOR_CHAINAGE_M",
    "PUMP_CHAINAGE_M",
    "bed_elevation_m",
    "build_final_case_fix1",
    "build_final_convergence_fix1a_report",
    "build_final_convergence_fix1_report",
    "build_grid_manifest",
    "initial_water_level_m",
    "manning_n",
    "profile_width_m",
    "run_final_level_fix1",
    "section_sites",
]
