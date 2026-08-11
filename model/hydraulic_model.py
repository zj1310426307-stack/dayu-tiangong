"""Saint-Venant 一维水动力模型的 Phase 0 适配器契约。"""

from collections.abc import Mapping
from typing import Any


class HydraulicModel:
    """提供稳定的水动力运行入口，后续由真实求解器实现替换。"""

    def __init__(self) -> None:
        """初始化空适配器；Phase 0 不加载外部求解器或参数。"""

    def run(self, input_data: Mapping[str, Any]) -> dict[str, list[float]]:
        """接收模型输入并返回标准结果容器。

        Args:
            input_data: 未来承载河网、边界条件和模型参数的映射。

        Returns:
            包含水位、流量和流速序列的空结果容器。
        """

        if not isinstance(input_data, Mapping):
            raise TypeError("input_data 必须是映射类型")

        return {"water_level": [], "flow": [], "velocity": []}
