"""验证水动力、优化与 AI 预留接口的输入输出契约。"""

import pytest

from ai import WaterAI
from model import HydraulicModel
from optimization import SchedulerOptimizer


def test_hydraulic_model_returns_standard_empty_result() -> None:
    """水动力适配器应返回三类标准结果序列。"""

    assert HydraulicModel().run({}) == {
        "water_level": [],
        "flow": [],
        "velocity": [],
    }


def test_scheduler_optimizer_returns_uncomputed_result() -> None:
    """优化器在未接算法时应明确返回空方案与未计算评分。"""

    assert SchedulerOptimizer().optimize({}) == {"scheme": [], "score": None}


def test_water_ai_returns_placeholder_contract() -> None:
    """AI 助手应返回任务书约定的占位文本。"""

    assert WaterAI().analyze({}) == {"answer": "AI助手接口"}


@pytest.mark.parametrize(
    ("callable_under_test", "invalid_input"),
    [
        (HydraulicModel().run, []),
        (SchedulerOptimizer().optimize, "invalid"),
        (WaterAI().analyze, None),
    ],
)
def test_placeholder_interfaces_reject_non_mapping_input(callable_under_test, invalid_input) -> None:
    """三个适配器统一拒绝非映射输入，避免未来契约悄然漂移。"""

    with pytest.raises(TypeError):
        callable_under_test(invalid_input)
