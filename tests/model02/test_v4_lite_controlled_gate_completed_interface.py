"""C2c combination gate for bracketed control and completed Gate physics."""

from __future__ import annotations

import copy

import pytest

import model.solver.finite_volume.integrator as integrator_module
from model import HydraulicEngine
from model.adapters import (
    build_v4_lite_mesh,
    v4_lite_mesh_hash,
    v4_lite_solver_policy_hash,
)
from model.api import parse_v4_lite_input
from model.core.errors import HydraulicInputError
from model.geometry.sections import RectangularSectionGeometry
from model.result import MvpHydraulicResult
from model.solver.finite_volume import (
    BoundaryPair,
    BoundarySeries,
    BracketedOneShotStageThreshold,
    DownstreamStageBoundary,
    FiniteVolumeCell,
    FiniteVolumeMesh,
    FixedGate,
    HydraulicState,
    SingleBranchConfig,
    StabilityError,
    UpstreamDischargeBoundary,
    solve_single_branch,
)
from tests.model02.test_v4_lite_contract import make_v4_lite_bracketed_payload
from tests.model02.test_v4_lite_gate_completed_interface import (
    make_v4_lite_completed_gate_payload,
)


def make_v4_lite_controlled_completed_gate_payload() -> dict:
    """Return one closed-to-open v6 Gate reference with no Pump."""

    payload = make_v4_lite_bracketed_payload()
    payload["provenance"]["validation_policy_version"] = "v4-lite-6"
    payload["solver"].update(
        {
            "gate_coupling_policy": "submerged-orifice-energy-momentum-v1",
            "gate_equation_tolerance_m": 1.0e-10,
            "gate_maximum_iterations": 80,
            "gate_spatial_support": "bound-internal-section-face-v1",
        }
    )
    for section in payload["sections"]:
        section["default_manning_n"] = 0.0
    payload["initial_state"] = {
        "type": "by-section",
        "values": [
            {
                "section_id": section_id,
                "water_level_m": 10.0,
                "discharge_m3_s": 0.0,
            }
            for section_id in (1, 2, 3)
        ],
    }
    payload["structures"]["pumps"] = []
    payload["structures"]["gates"][0].update(
        {
            "opening_m": 0.5,
            "sill_elevation_m": 9.0,
        }
    )
    return payload


def _direct_combined_run(
    *,
    area: tuple[float, float, float] = (10.0, 10.0, 10.0),
    discharge: tuple[float, float, float] = (0.0, 0.0, 0.0),
    upstream_values: tuple[float, float] = (1.0, 1.0),
):
    """Exercise the kernel's independent C2 combination preflight."""

    geometry = RectangularSectionGeometry(width=10.0, bed_elevation=0.0)
    mesh = FiniteVolumeMesh(
        tuple(
            FiniteVolumeCell(
                cell_id=f"cell-{index}",
                dx=100.0,
                section_id=index + 1,
                bed_elevation=0.0,
                geometry=geometry,
                manning_n=0.0,
            )
            for index in range(3)
        )
    )
    initial = HydraulicState.from_conserved(
        mesh=mesh,
        time=0.0,
        area=area,
        discharge=discharge,
        dry_depth=1.0e-3,
    )
    boundaries = BoundaryPair(
        upstream=UpstreamDischargeBoundary(
            BoundarySeries((0.0, 0.5), upstream_values, "discharge"),
            boundary_closure="subcritical-characteristic-v1",
        ),
        downstream=DownstreamStageBoundary(
            BoundarySeries((0.0, 0.5), (1.0, 1.0), "stage"),
            boundary_closure="subcritical-characteristic-v1",
        ),
    )
    gate = FixedGate(
        gate_id="gate-1",
        face_index=0,
        opening=0.5,
        width=2.0,
        height=1.0,
        control=BracketedOneShotStageThreshold(1.00001),
        coupling_policy="submerged-orifice-energy-momentum-v1",
        sill_elevation=0.0,
    )
    return solve_single_branch(
        mesh=mesh,
        initial_state=initial,
        boundaries=boundaries,
        config=SingleBranchConfig(
            end_time=0.5,
            maximum_dt=0.25,
            minimum_dt=1.0e-5,
            output_interval=0.25,
            structure_event_policy=(
                "bracketed-conservative-replay-right-end-v1"
            ),
            event_time_tolerance=0.01,
        ),
        gates=(gate,),
    )


def test_v4_lite_6_event_then_completed_interface_is_self_auditing() -> None:
    """The located event stays closed and only the next interval uses strong flux."""

    payload = make_v4_lite_controlled_completed_gate_payload()
    result = HydraulicEngine().run(payload)
    assert isinstance(result, MvpHydraulicResult)
    document = result.to_dict()

    assert document["provenance"] == {
        "input_schema_version": "dayu.model-input.v4-lite",
        "input_snapshot_hash": (
            "b49e8b6174aa8979f04f8a0e6e0ae6350854c22487dd8374c7065346e4dabe74"
        ),
        "mesh_hash": (
            "5be802aaa262a02deb2419c45b1e4b30d88ed1f9f12f7eb43ad3a8e29b9c1e33"
        ),
        "solver_type": "saint-venant",
        "scheme": "finite-volume-hll",
        "time_integrator": "ssp-rk2",
        "engine_version": "dayu-hydraulic-mvp",
        "engine_commit": "test-commit",
        "validation_policy_version": "v4-lite-6",
        "solver_policy_hash": (
            "dd0f87e60a87826d55cc2bb02de1ad56a1bf4e8ec8a1ffe9698cdfb7738aaac4"
        ),
    }
    assert len(document["control_events"]) == 1
    event = document["control_events"][0]
    assert event["time"] == pytest.approx(0.0078125)
    assert event["bracket_end_time"] == event["time"]
    assert event["previous_observed_water_level"] <= event["threshold_water_level"]
    assert event["observed_water_level"] > event["threshold_water_level"]

    coupling = document["controlled_gate_coupling_evidence"][0]
    rows = coupling["stage_evaluations"]
    assert coupling["event_time"] == event["time"]
    assert coupling["total_transfer_volume"] == pytest.approx(
        0.18963193173761772
    )
    assert coupling["maximum_absolute_energy_residual"] <= 1.0e-10
    assert len(rows) == 2 * document["diagnostics"]["step_count"] == 10
    assert rows[0]["regime"] == "closed_barrier_completed_interface"
    assert rows[1]["evaluation_time"] == event["time"]
    assert rows[1]["actual_opening"] == rows[1]["flow"] == 0.0
    assert rows[2]["evaluation_time"] == event["time"]
    assert rows[2]["regime"] == "submerged_orifice_completed_interface"
    assert rows[2]["actual_opening"] == 0.5
    assert rows[2]["flow"] > 0.0
    assert document["gates"][0]["opening"] == [0.0, 0.5, 0.5]
    assert document["water_balance"]["relative_water_balance_error"] < 1.0e-12
    flags = set(document["diagnostics"]["diagnostic_flags"])
    assert "gate_completed_interface_bracketed_control_v1" in flags
    assert "structure_event_bracketed_conservative_replay_right_end_v1" in flags
    assert "structure_momentum_closure_mass_only_mvp" not in flags


def test_core_combined_scope_repeats_api_preflight_and_runs() -> None:
    """Direct kernel callers receive the same restricted combination semantics."""

    result = _direct_combined_run()
    assert len(result.control_events) == 1
    event_time = result.control_events[0].time
    event_step = next(item for item in result.steps if item.state.time == event_time)
    assert all(
        flow.completed_interface is not None
        and flow.completed_interface.actual_opening == 0.0
        for flow in event_step.budget.gate_stage_flows
    )
    next_step = next(item for item in result.steps if item.state.time > event_time)
    assert all(
        flow.completed_interface is not None
        and flow.completed_interface.actual_opening == 0.5
        for flow in next_step.budget.gate_stage_flows
    )


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"area": (10.0, 9.0, 10.0)}, "initially level face"),
        ({"discharge": (0.1, 0.0, 0.0)}, "zero initial discharge"),
        ({"upstream_values": (1.0, 1.1)}, "positive constant inflow"),
    ],
)
def test_core_combined_scope_fails_closed(kwargs: dict, message: str) -> None:
    """The low-level solver cannot bypass the public v6 combination scope."""

    with pytest.raises(ValueError, match=message):
        _direct_combined_run(**kwargs)


def test_combined_policy_changes_input_and_solver_hash_but_not_mesh() -> None:
    """Control/physics policy stays separate from immutable Gate mesh identity."""

    payload = make_v4_lite_controlled_completed_gate_payload()
    parsed = parse_v4_lite_input(payload)
    mesh = build_v4_lite_mesh(parsed)
    changed = copy.deepcopy(payload)
    changed["solver"]["event_time_tolerance_seconds"] = 0.005
    changed_parsed = parse_v4_lite_input(changed)
    changed_mesh = build_v4_lite_mesh(changed_parsed)

    assert v4_lite_mesh_hash(parsed, mesh) == v4_lite_mesh_hash(
        changed_parsed,
        changed_mesh,
    )
    assert v4_lite_solver_policy_hash(parsed) != v4_lite_solver_policy_hash(
        changed_parsed
    )


def test_rejected_combination_probe_has_no_control_or_coupling_side_effect(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A discarded SSP trial cannot duplicate the event or transfer volume."""

    payload = make_v4_lite_controlled_completed_gate_payload()
    reference = HydraulicEngine().run(payload).to_dict()
    original_step = integrator_module.ssp_rk2_step
    attempts = 0

    def reject_first_completed_trial(**kwargs):
        nonlocal attempts
        attempts += 1
        trial = original_step(**kwargs)
        if attempts == 1:
            raise StabilityError("synthetic rejection after completed-interface RK2")
        return trial

    monkeypatch.setattr(
        integrator_module,
        "ssp_rk2_step",
        reject_first_completed_trial,
    )
    retried = HydraulicEngine().run(payload).to_dict()

    assert len(retried["control_events"]) == 1
    assert retried["control_events"][0]["time"] == pytest.approx(
        reference["control_events"][0]["time"]
    )
    assert retried["controlled_gate_coupling_evidence"][0][
        "total_transfer_volume"
    ] == pytest.approx(
        reference["controlled_gate_coupling_evidence"][0][
            "total_transfer_volume"
        ]
    )
    assert retried["diagnostics"]["retry_count"] == 0


def test_v4_lite_6_without_a_crossing_cannot_claim_combined_success() -> None:
    """A valid but never-triggered run is not a successful C2 combination gate."""

    payload = make_v4_lite_controlled_completed_gate_payload()
    payload["structures"]["gates"][0]["control"][
        "threshold_water_level_m"
    ] = 11.0
    with pytest.raises(HydraulicInputError, match="requires one bracketed Gate event"):
        HydraulicEngine().run(payload)


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        ("fixed", "requires every structure to use bracketed control"),
        ("pump", "requires exactly one Gate and no Pump"),
        ("initial_head", "initially level closed interface"),
        ("zero_inflow", "requires positive constant upstream inflow"),
        ("dynamic_inflow", "requires constant upstream boundary discharge"),
        ("friction", "requires zero Manning friction"),
        ("not_submerged", "target opening must remain submerged"),
        ("missing_event", "requires every event policy field explicitly"),
        ("missing_gate", "requires every Gate coupling field explicitly"),
    ],
)
def test_v4_lite_6_combined_scope_fails_closed(
    mutation: str,
    message: str,
) -> None:
    """Unsupported control/physics combinations fail before numerical routing."""

    payload = make_v4_lite_controlled_completed_gate_payload()
    if mutation == "fixed":
        payload["structures"]["gates"][0]["control"] = {"type": "fixed"}
    elif mutation == "pump":
        payload["structures"]["pumps"] = make_v4_lite_bracketed_payload()[
            "structures"
        ]["pumps"]
    elif mutation == "initial_head":
        payload["initial_state"]["values"][1]["water_level_m"] = 9.9
    elif mutation == "zero_inflow":
        payload["boundary"]["upstream"]["flow_m3_s"] = [0.0, 0.0]
    elif mutation == "dynamic_inflow":
        payload["boundary"]["upstream"]["flow_m3_s"] = [5.0, 5.1]
    elif mutation == "friction":
        payload["sections"][0]["default_manning_n"] = 0.03
    elif mutation == "not_submerged":
        payload["structures"]["gates"][0]["sill_elevation_m"] = 9.6
    elif mutation == "missing_event":
        payload["solver"].pop("event_time_tolerance_seconds")
    elif mutation == "missing_gate":
        payload["solver"].pop("gate_equation_tolerance_m")
    with pytest.raises(HydraulicInputError, match=message):
        parse_v4_lite_input(payload)


@pytest.mark.parametrize(
    "mutation",
    ["remove", "backfill", "forge_momentum", "shift_event"],
)
def test_v4_lite_6_result_rejects_missing_or_forged_combined_evidence(
    mutation: str,
) -> None:
    """A durable v6 result cannot falsify event/command/momentum causality."""

    document = HydraulicEngine().run(
        make_v4_lite_controlled_completed_gate_payload()
    ).to_dict()
    evidence = document["controlled_gate_coupling_evidence"][0]
    if mutation == "remove":
        document.pop("controlled_gate_coupling_evidence")
    elif mutation == "backfill":
        evidence["stage_evaluations"][1]["actual_opening"] = 0.5
    elif mutation == "forge_momentum":
        evidence["stage_evaluations"][2]["momentum_flux_left"] += 1.0
    elif mutation == "shift_event":
        evidence["event_time"] += 0.01
    with pytest.raises(ValueError):
        MvpHydraulicResult.model_validate(document)


def test_v4_lite_5_frozen_hashes_remain_unchanged() -> None:
    """The new combination route must not reinterpret the fixed v5 Gate."""

    result = HydraulicEngine().run(make_v4_lite_completed_gate_payload())
    document = result.to_dict()
    assert document["provenance"]["input_snapshot_hash"] == (
        "b3cdf80d199ea643fcc763254c8c4878a843b6fb725f475f21a298dca2b541af"
    )
    assert document["provenance"]["solver_policy_hash"] == (
        "cb36f8c8989313a69261ab139471d8f05058a88383486033e29ebf5c71c55625"
    )
    assert "controlled_gate_coupling_evidence" not in document
    assert "controlled_gate_coupling_evidence" not in result.model_dump(mode="json")
