"""HYDRO-MODEL-01 gate-domain acceptance tests."""

import math

import pytest

from model.structure.gate import GateModel, constrain_gate_opening


def test_gate_model_uses_the_shared_free_orifice_equation() -> None:
    """The immutable façade must not diverge from the accepted gate equation."""

    gate = GateModel(width=4.0, crest_elevation=9.0, discharge_coefficient=0.62)

    result = gate.evaluate(
        requested_opening=1.0,
        upstream_level=12.0,
        downstream_level=9.5,
    )

    expected = 0.62 * 4.0 * math.sqrt(2.0 * 9.81 * 3.0)
    assert result.regime == "free_orifice"
    assert result.flow == pytest.approx(expected)
    assert math.isfinite(result.flow)


def test_gate_model_reports_actual_rate_limited_opening() -> None:
    """A finite actuator rate must constrain the opening used by hydraulics."""

    actual, flags = constrain_gate_opening(
        2.0,
        previous_opening=0.5,
        elapsed_seconds=10.0,
        minimum_opening=0.0,
        maximum_opening=2.0,
        opening_rate_limit=0.05,
        minimum_hold_seconds=0.0,
        time_since_change=600.0,
        availability="online",
    )
    result = GateModel(width=4.0, crest_elevation=9.0).evaluate(
        requested_opening=2.0,
        actual_opening=actual,
        upstream_level=12.0,
        downstream_level=9.5,
    )

    assert actual == pytest.approx(1.0)
    assert result.actual_opening == pytest.approx(1.0)
    assert "opening_rate_limited" in flags
