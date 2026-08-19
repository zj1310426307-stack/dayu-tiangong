"""Direct-engine integration tests for the explicit v4-lite FV route."""

from __future__ import annotations

import copy

import pytest

import model.adapters.v4_lite as v4_adapter_module
import model.engine as engine_module
from model import HydraulicEngine
from model.adapters import build_v4_lite_mesh, v4_lite_mesh_hash
from model.api import parse_v4_lite_input
from model.core.errors import HydraulicInputError
from model.provenance import snapshot_hash
from model.result import MvpHydraulicResult
from tests.model02.test_v4_lite_contract import make_v4_lite_payload
from tests.test_hydraulic_engine import make_snapshot
from tests.test_model_input_v3_adapter import _v3_snapshot
from tests.test_phase4_network import make_y_network


def make_short_v4_lite_payload() -> dict:
    """Reduce the strict contract fixture while retaining two dynamic boundary knots."""

    payload = make_v4_lite_payload()
    payload["solver"].update(
        {
            "duration_seconds": 120,
            "maximum_time_step_seconds": 10,
            "output_interval_seconds": 60,
        }
    )
    payload["boundary"]["upstream"].update(
        {
            "time_seconds": [0, 60, 120],
            "flow_m3_s": [5, 7, 5],
        }
    )
    payload["boundary"]["downstream"].update(
        {
            "time_seconds": [0, 120],
            "water_level_m": [10, 10.1],
        }
    )
    return payload


def test_v4_lite_exact_route_never_calls_the_legacy_v3_adapter(monkeypatch) -> None:
    """The v4-lite schema selects only its direct native solver route."""

    def forbidden_legacy_adapter(*args, **kwargs):
        """Fail immediately if v4-lite is accidentally projected through v3/v2."""

        del args, kwargs
        raise AssertionError("v4-lite must not call adapt_v3_to_v2")

    monkeypatch.setattr(engine_module, "adapt_v3_to_v2", forbidden_legacy_adapter)

    result = HydraulicEngine().run(make_short_v4_lite_payload())

    assert isinstance(result, MvpHydraulicResult)
    assert result.schema_version == "dayu.hydraulic-result.mvp"
    assert not hasattr(result, "node_series")


def test_v4_lite_builds_length_preserving_deterministic_mesh() -> None:
    """Endpoint half cells and internal midpoint cells cover the adopted domain once."""

    parsed = parse_v4_lite_input(make_short_v4_lite_payload())
    first = build_v4_lite_mesh(parsed)
    second = build_v4_lite_mesh(parsed)

    assert tuple(cell.dx for cell in first.cells) == pytest.approx((250.0, 500.0, 250.0))
    assert sum(cell.dx for cell in first.cells) == pytest.approx(1000.0)
    assert v4_lite_mesh_hash(parsed, first) == v4_lite_mesh_hash(parsed, second)

    changed = make_short_v4_lite_payload()
    for section in changed["sections"]:
        section["points"][-1]["offset_m"] = 22
    changed_parsed = parse_v4_lite_input(changed)
    changed_mesh = build_v4_lite_mesh(changed_parsed)
    assert v4_lite_mesh_hash(parsed, first) != v4_lite_mesh_hash(
        changed_parsed, changed_mesh
    )


def test_v4_lite_result_closes_time_water_structure_and_provenance_contracts() -> None:
    """Dynamic Q/H, output axes, devices, volume balance and hashes are durable evidence."""

    payload = make_short_v4_lite_payload()
    result = HydraulicEngine().run(payload)
    document = result.to_dict()

    assert [row["time"] for row in document["sections"]] == [
        [0.0, 60.0, 120.0],
        [0.0, 60.0, 120.0],
        [0.0, 60.0, 120.0],
    ]
    # Integral of the 5 -> 7 -> 5 m3/s piecewise-linear upstream hydrograph.
    assert document["water_balance"]["upstream_boundary_volume"] == pytest.approx(720.0)
    assert document["water_balance"]["pump_outflow_volume"] == pytest.approx(180.0)
    assert document["water_balance"]["relative_water_balance_error"] < 1.0e-12
    assert document["water_balance"]["status"] == "pass"
    assert document["gates"][0]["gate_id"] == 51
    assert document["gates"][0]["opening"] == [1.0, 1.0, 1.0]
    assert document["pumps"][0]["status"] == ["on", "on", "on"]
    assert document["pumps"][0]["flow"] == [1.5, 1.5, 1.5]
    assert (
        "structure_momentum_closure_mass_only_mvp"
        in document["diagnostics"]["diagnostic_flags"]
    )
    assert document["provenance"]["input_snapshot_hash"] == snapshot_hash(payload)
    assert len(document["provenance"]["mesh_hash"]) == 64

    constant_stage = copy.deepcopy(payload)
    constant_stage["boundary"]["downstream"]["water_level_m"] = [10, 10]
    reference = HydraulicEngine().run(constant_stage).to_dict()
    assert document["sections"][-1]["water_level"][-1] != pytest.approx(
        reference["sections"][-1]["water_level"][-1]
    )


def test_v4_lite_freezes_input_before_solver_execution(monkeypatch) -> None:
    """A caller mutation during solving cannot rewrite the executed-input digest."""

    payload = make_short_v4_lite_payload()
    before = snapshot_hash(copy.deepcopy(payload))
    original_solver = v4_adapter_module.solve_single_branch

    def mutate_caller_then_solve(*args, **kwargs):
        payload["provenance"]["engine_commit"] = "mutated-during-solve"
        return original_solver(*args, **kwargs)

    monkeypatch.setattr(
        v4_adapter_module,
        "solve_single_branch",
        mutate_caller_then_solve,
    )
    result = HydraulicEngine().run(payload)

    assert result.provenance.input_snapshot_hash == before
    assert result.provenance.engine_commit == "test-commit"
    assert snapshot_hash(payload) != before


def test_unknown_schema_and_v4_legacy_overrides_fail_closed() -> None:
    """Unknown versions and mutable legacy overrides cannot fall into v1."""

    with pytest.raises(HydraulicInputError, match="unsupported model input schema"):
        HydraulicEngine().run({"schema_version": "dayu.model-input.v5"})
    with pytest.raises(HydraulicInputError, match="does not accept legacy overrides"):
        HydraulicEngine().run(make_short_v4_lite_payload(), {"time_step": 60})
    with pytest.raises(HydraulicInputError, match="does not yet support cancellation"):
        HydraulicEngine().run(
            make_short_v4_lite_payload(),
            cancel_check=lambda: False,
        )


def test_v1_v2_v3_representative_routes_keep_their_result_semantics() -> None:
    """Adding the exact v4 route leaves all three historical routes selected explicitly."""

    v1 = HydraulicEngine().run(make_snapshot()).to_dict()
    v2 = HydraulicEngine().run(make_y_network()).to_dict()
    v3 = HydraulicEngine().run(_v3_snapshot()).to_dict()

    assert v1["schema_version"] == "dayu.hydraulic-result.v1"
    assert v1["diagnostics"]["solver"] == "saint-venant-rusanov-rectangular-v1"
    assert v2["schema_version"] == "dayu.hydraulic-result.v2"
    assert v2["provenance"]["input_schema_version"] == "dayu.model-input.v2"
    assert v3["schema_version"] == "dayu.hydraulic-result.v2"
    assert v3["provenance"]["input_schema_version"] == "dayu.model-input.v3"
