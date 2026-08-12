"""保持早期公共入口兼容的 Phase 3 水动力模型适配器。"""

from collections.abc import Mapping
from typing import Any

from model.engine import HydraulicEngine


class HydraulicModel:
    """通过历史 `run` 入口调用独立 Saint-Venant 计算引擎。"""

    def __init__(self) -> None:
        """初始化无 Web 与数据库依赖的数值引擎。"""

        self._engine = HydraulicEngine()

    def run(self, input_data: Mapping[str, Any]) -> dict[str, Any]:
        """接收 Phase 2 快照并返回可序列化的标准计算结果。

        Args:
            input_data: `dayu.model-input.v1` 模型输入快照。

        Returns:
            包含断面时序和稳定性诊断的结果映射。
        """

        if not isinstance(input_data, Mapping):
            raise TypeError("input_data 必须是映射类型")

        return self._engine.run(input_data).to_dict()
