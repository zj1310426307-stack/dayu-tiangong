"""D1 v4-lite Gate/Pump strong-coupling integration and failure gates."""

from __future__ import annotations

import copy

import pytest

import model.solver.finite_volume.integrator as integrator_module
from model import HydraulicEngine
from model.api import parse_v4_lite_input
from model.core.errors import HydraulicInputError
from model.result import MvpHydraulicResult
from model.solver.finite_volume import NumericalStateError, StabilityError
from tests.model02.test_v4_lite_controlled_gate_completed_interface import (
    make_v4_lite_controlled_completed_gate_payload,
)


def make_v4_lite_d1_payload() -> dict:
    """Return one short v7 Gate plus hydraulic external-Pump reference."""

    payload = make_v4_lite_controlled_completed_gate_payload()
    payload["provenance"]["validation_policy_version"] = "v4-lite-7"
    payload["solver"].update(
        {
            "pump_coupling_policy": "qh-operating-point-external-sink-v1",
            "pump_curve_policy": "piecewise-linear-qh-v1",
            "pump_efficiency_policy": "piecewise-linear-q-efficiency-v1",
            "pump_system_loss_policy": "quadratic-q-v1",
            "pump_control_policy": "stage-hysteresis-min-runtime-v1",
            "pump_momentum_policy": "local-advective-external-sink-v1",
            "pump_head_residual_tolerance_m": 1.0e-10,
            "pump_maximum_iterations": 100,
            "pump_spatial_support": "bound-section-cell-center-v1",
            "water_balance_tolerance": 1.0e-10,
        }
    )
    template = payload["sections"][0]
    payload["sections"] = [
        {
            **copy.deepcopy(template),
            "section_id": section_id,
            "section_code": f"CS{section_id:03d}",
            "chainage_m": 250.0 * (section_id - 1),
            "profile_id": 100 + section_id,
            "profile_hash": f"{section_id:064x}",
        }
        for section_id in range(1, 6)
    ]
    payload["initial_state"]["values"] = [
        {
            "section_id": section_id,
            "water_level_m": 10.0,
            "discharge_m3_s": 0.0,
        }
        for section_id in range(1, 6)
    ]
    payload["structures"]["gates"][0]["interface"] = {
        "upstream_section_id": 2,
        "downstream_section_id": 3,
    }
    payload["structures"]["gates"][0]["control"][
        "threshold_water_level_m"
    ] = 10.000000001
    payload["structures"]["pumps"] = [
        {
            "pump_model": "hydraulic-qh-external-sink-v1",
            "identity": {"namespace": "public.pump", "id": 61},
            "branch_id": 21,
            "section_id": 1,
            "outlet": "external",
            "status": "off",
            "head_curve": {
                "points": [
                    {"flow_m3s": 0.001, "head_m": 2.5},
                    {"flow_m3s": 0.005, "head_m": 2.0},
                    {"flow_m3s": 0.010, "head_m": 1.0},
                ]
            },
            "efficiency_curve": {
                "points": [
                    {"flow_m3s": 0.001, "efficiency": 0.50},
                    {"flow_m3s": 0.005, "efficiency": 0.80},
                    {"flow_m3s": 0.010, "efficiency": 0.70},
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
                "quadratic_loss_coefficient_s2_m5": 0.1,
            },
            "outlet_stage": {
                "time_seconds": [0.0, 1.0],
                "water_level_m": [11.5, 11.5],
            },
            "control": {
                "type": "stage-hysteresis-min-runtime-v1",
                "start_level_m": 9.9,
                "stop_level_m": 9.5,
                "minimum_run_seconds": 0.0,
                "minimum_stop_seconds": 0.0,
                "maximum_starts": 2,
            },
        }
    ]
    return payload


def test_gp1_v4_lite_7_gate_pump_result_is_self_auditing() -> None:
    """GP1 closes Gate transfer, Pump sink, stage roots, water, and energy."""

    result = HydraulicEngine().run(make_v4_lite_d1_payload())
    assert isinstance(result, MvpHydraulicResult)
    document = result.to_dict()

    assert document["provenance"]["validation_policy_version"] == "v4-lite-7"
    assert document["pumps"][0]["coupling_policy"] == (
        "qh-operating-point-external-sink-v1"
    )
    pump_evidence = document["pump_coupling_evidence"][0]
    rows = pump_evidence["stage_evaluations"]
    assert len(rows) == 2 * document["diagnostics"]["step_count"]
    assert pump_evidence["total_external_volume_m3"] == pytest.approx(
        document["water_balance"]["pump_outflow_volume"]
    )
    assert pump_evidence["total_input_energy_kwh"] > 0.0
    assert pump_evidence["maximum_absolute_head_residual_m"] <= 1.0e-10
    assert all(
        row["pump_head_m"] == pytest.approx(row["system_head_m"], abs=1.0e-10)
        for row in rows
    )
    assert any(
        first["total_flow_m3s"] != pytest.approx(second["total_flow_m3s"])
        for first, second in zip(rows[0::2], rows[1::2])
    )
    assert any(event["action"] == "start" for event in document["control_events"])
    assert any(event["structure_type"] == "gate" for event in document["control_events"])
    assert document["water_balance"]["relative_water_balance_error"] < 1.0e-12
    assert "controlled_gate_coupling_evidence" in document


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        ("missing_policy", "every Gate/Pump policy field explicitly"),
        ("legacy_pump", "requires a hydraulic Q-H Pump"),
        ("overlap", "placements must not overlap"),
        ("curve_order", "strictly increasing"),
        ("efficiency", "less than or equal to 1"),
        ("hysteresis", "greater than stop_level_m"),
        ("outlet_coverage", "does not cover"),
        ("nonpositive_inflow", "strictly positive upstream hydrograph"),
        ("raised_tailwater", "no higher than the final initial stage"),
        ("dry_source", "source cell must start fully wet"),
        ("loose_balance", "at most 1e-10"),
    ],
)
def test_d1_preflight_fails_closed(mutation: str, message: str) -> None:
    """D1 rejects incomplete policy, placement, curve, control, and outlet input."""

    payload = make_v4_lite_d1_payload()
    pump = payload["structures"]["pumps"][0]
    if mutation == "missing_policy":
        payload["solver"].pop("pump_curve_policy")
    elif mutation == "legacy_pump":
        payload["structures"]["pumps"] = [
            {
                "identity": {"namespace": "public.pump", "id": 61},
                "branch_id": 21,
                "section_id": 3,
                "outlet": "external",
                "status": "off",
                "design_flow_m3_s": 0.2,
                "control": {"type": "fixed"},
            }
        ]
    elif mutation == "overlap":
        pump["section_id"] = 2
    elif mutation == "curve_order":
        pump["head_curve"]["points"][1]["flow_m3s"] = 0.01
    elif mutation == "efficiency":
        pump["efficiency_curve"]["points"][1]["efficiency"] = 1.1
    elif mutation == "hysteresis":
        pump["control"]["start_level_m"] = pump["control"]["stop_level_m"]
    elif mutation == "outlet_coverage":
        pump["outlet_stage"]["time_seconds"][-1] = 0.5
    elif mutation == "nonpositive_inflow":
        payload["boundary"]["upstream"]["flow_m3_s"][-1] = 0.0
    elif mutation == "raised_tailwater":
        payload["boundary"]["downstream"]["water_level_m"][-1] = 10.1
    elif mutation == "dry_source":
        payload["initial_state"]["values"][0]["water_level_m"] = 9.0005
    elif mutation == "loose_balance":
        payload["solver"]["water_balance_tolerance"] = 0.01

    with pytest.raises(HydraulicInputError, match=message):
        parse_v4_lite_input(payload)


def test_gp2_runtime_no_root_fails_without_design_flow_fallback() -> None:
    """A valid curve with no system intersection stops before any result exists."""

    payload = make_v4_lite_d1_payload()
    pump = payload["structures"]["pumps"][0]
    pump["outlet_stage"]["water_level_m"] = [20.0, 20.0]

    with pytest.raises(ValueError, match="no bracketed root"):
        HydraulicEngine().run(payload)


def test_d1_result_rejects_forged_energy_or_stage_head() -> None:
    """Durable D1 evidence cannot falsify accepted energy or the system head."""

    document = HydraulicEngine().run(make_v4_lite_d1_payload()).to_dict()
    energy_forgery = copy.deepcopy(document)
    energy_forgery["pump_coupling_evidence"][0]["total_input_energy_kwh"] += 1.0
    with pytest.raises(ValueError, match="energy is inconsistent"):
        MvpHydraulicResult.model_validate(energy_forgery)

    head_forgery = copy.deepcopy(document)
    head_forgery["pump_coupling_evidence"][0]["stage_evaluations"][0][
        "system_head_m"
    ] += 0.1
    with pytest.raises(ValueError, match="head closure"):
        MvpHydraulicResult.model_validate(head_forgery)


def test_d1_rejected_trial_does_not_pollute_energy_or_control(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A synthetic post-RK rejection leaves only accepted Pump stages durable."""

    original_step = integrator_module.ssp_rk2_step
    attempts = 0
    rejected_energy = 0.0

    def reject_first_trial(**kwargs):
        nonlocal attempts, rejected_energy
        attempts += 1
        trial = original_step(**kwargs)
        if attempts == 1:
            rejected_energy = trial.budget.pump_input_energy_kwh
            raise StabilityError("synthetic rejection after D1 Pump RK2")
        return trial

    monkeypatch.setattr(integrator_module, "ssp_rk2_step", reject_first_trial)
    document = HydraulicEngine().run(make_v4_lite_d1_payload()).to_dict()
    evidence = document["pump_coupling_evidence"][0]
    rows = evidence["stage_evaluations"]
    independent_energy = sum(
        0.5
        * first["dt"]
        * (first["input_power_kw"] + second["input_power_kw"])
        / 3600.0
        for first, second in zip(rows[0::2], rows[1::2])
    )

    assert rejected_energy > 0.0
    assert attempts > document["diagnostics"]["step_count"]
    assert len(rows) == 2 * document["diagnostics"]["step_count"]
    assert evidence["total_input_energy_kwh"] == pytest.approx(independent_energy)
    assert sum(
        event["action"] == "start" for event in document["control_events"]
    ) == 1
    assert sum(
        event["structure_type"] == "gate"
        for event in document["control_events"]
    ) == 1


def test_gp2_pump_root_iteration_exhaustion_fails_closed() -> None:
    """D1 cannot return a nearest-point result after its root budget is exhausted."""

    payload = make_v4_lite_d1_payload()
    payload["solver"]["pump_head_residual_tolerance_m"] = 1.0e-15
    payload["solver"]["pump_maximum_iterations"] = 1

    with pytest.raises(ValueError, match="did not converge"):
        HydraulicEngine().run(payload)


def test_gp2_gate_event_refinement_exhaustion_fails_closed() -> None:
    """The Gate crossing cannot skip its configured conservative replay budget."""

    payload = make_v4_lite_d1_payload()
    payload["solver"]["maximum_event_refinements"] = 0

    with pytest.raises(NumericalStateError, match="maximum_event_refinements"):
        HydraulicEngine().run(payload)


def test_gp2_pump_positivity_retry_exhaustion_fails_closed() -> None:
    """An oversized Pump sink must not be clipped to preserve cell area."""

    payload = make_v4_lite_d1_payload()
    pump = payload["structures"]["pumps"][0]
    pump["head_curve"]["points"] = [
        {"flow_m3s": 1000.0, "head_m": 2.5},
        {"flow_m3s": 10000.0, "head_m": 1.0},
    ]
    pump["efficiency_curve"]["points"] = [
        {"flow_m3s": 1000.0, "efficiency": 0.7},
        {"flow_m3s": 10000.0, "efficiency": 0.7},
    ]
    pump["system_loss"]["quadratic_loss_coefficient_s2_m5"] = 0.0
    payload["solver"]["maximum_retries"] = 0

    with pytest.raises(StabilityError, match="exhausted retry budget"):
        HydraulicEngine().run(payload)


def test_gp2_water_balance_quality_gate_fails_closed() -> None:
    """A tolerance below floating conservation closure cannot be marked PASS."""

    payload = make_v4_lite_d1_payload()
    payload["solver"]["water_balance_tolerance"] = 1.0e-30

    with pytest.raises(NumericalStateError, match="water_balance_failed"):
        HydraulicEngine().run(payload)
