"""Native finite-volume progress and cooperative cancellation boundaries."""

from __future__ import annotations

import pytest

from model import HydraulicEngine
from model.core.errors import HydraulicCancelledError
from model.solver.finite_volume.pump_curve import (
    PumpSystemLoss,
    PumpUnitConfiguration,
    solve_pump_operating_point,
)
from tests.model02.test_pump_operating_point import _efficiency_curve, _head_curve
from tests.model02.test_gate_completed_interface import _completed_gate, _context
from tests.model02.test_v4_lite_engine import make_short_v4_lite_payload


def test_callback_reports_only_monotonic_accepted_steps_without_changing_result() -> None:
    """Observe accepted boundaries while retaining byte-equivalent result data."""

    payload = make_short_v4_lite_payload()
    observed: list[tuple[float, float, dict[str, object]]] = []

    callback_result = HydraulicEngine().run(
        payload,
        cancel_check=lambda: False,
        progress_callback=lambda time, cfl, details: observed.append(
            (time, cfl, details)
        ),
    )
    baseline = HydraulicEngine().run(payload)

    assert callback_result.to_dict() == baseline.to_dict()
    assert observed
    assert [item[0] for item in observed] == sorted(item[0] for item in observed)
    assert [item[2]["accepted_step_count"] for item in observed] == list(
        range(1, len(observed) + 1)
    )
    assert observed[-1][0] == 120.0


def test_cancel_before_trial_never_reports_an_unaccepted_step() -> None:
    """Stop at the first safe checkpoint and leave accepted progress empty."""

    observed: list[object] = []
    with pytest.raises(HydraulicCancelledError, match="accepted_step_start"):
        HydraulicEngine().run(
            make_short_v4_lite_payload(),
            cancel_check=lambda: True,
            progress_callback=lambda *args: observed.append(args),
        )
    assert observed == []


def test_pump_root_loop_honours_cooperative_cancellation() -> None:
    """Do not wait for a long bisection to return after cancellation."""

    with pytest.raises(HydraulicCancelledError, match="pump_root_iteration"):
        solve_pump_operating_point(
            evaluation_time=60.0,
            dt=10.0,
            pump_id="pump-1",
            source_stage_m=10.0,
            outlet_stage_m=14.0,
            head_curve=_head_curve(),
            efficiency_curve=_efficiency_curve(),
            units=PumpUnitConfiguration(
                total_units=1,
                running_units=1,
                minimum_running_units=1,
                maximum_running_units=1,
            ),
            system_loss=PumpSystemLoss(
                static_loss_m=0.5,
                quadratic_loss_coefficient_s2_m5=0.02,
            ),
            head_residual_tolerance_m=1.0e-10,
            maximum_iterations=100,
            cancel_check=lambda: True,
        )


def test_gate_root_loop_honours_cooperative_cancellation() -> None:
    """Completed-interface Gate bisection checks the same cancellation boundary."""

    with pytest.raises(HydraulicCancelledError, match="gate_root_iteration"):
        _completed_gate(face_index=0).evaluate_stage(
            _context(),
            cancel_check=lambda: True,
        )
