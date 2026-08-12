"""Contract tests for hydraulic, optimisation and AI public adapters."""

import pytest

from ai import WaterAI
from model import HydraulicModel
from model.core.errors import HydraulicInputError
from optimization import SchedulerOptimizer


def test_hydraulic_model_requires_a_versioned_snapshot() -> None:
    """Hydraulic calculation must not silently accept an empty placeholder."""

    with pytest.raises(HydraulicInputError, match="dayu.model-input.v1"):
        HydraulicModel().run({})


def test_scheduler_optimizer_returns_uncomputed_result() -> None:
    """The optimisation placeholder keeps its stable public contract."""

    assert SchedulerOptimizer().optimize({}) == {"scheme": [], "score": None}


def test_water_ai_returns_placeholder_contract() -> None:
    """The AI placeholder keeps its stable public contract."""

    assert WaterAI().analyze({}) == {"answer": "AI助手接口"}


@pytest.mark.parametrize(
    ("callable_under_test", "invalid_input"),
    [
        (HydraulicModel().run, []),
        (SchedulerOptimizer().optimize, "invalid"),
        (WaterAI().analyze, None),
    ],
)
def test_public_interfaces_reject_non_mapping_input(callable_under_test, invalid_input) -> None:
    """All public adapters reject non-mapping input consistently."""

    with pytest.raises(TypeError):
        callable_under_test(invalid_input)
