"""大模型 API 与水利知识库的 Phase 0 统一入口。"""

from collections.abc import Mapping
from typing import Any


class WaterAI:
    """提供水利问题分析入口，当前阶段返回清晰的接口占位说明。"""

    def analyze(self, input_data: Mapping[str, Any]) -> dict[str, str]:
        """校验分析输入并返回 Phase 0 占位响应。

        Args:
            input_data: 未来承载问题、上下文和调度场景的映射。

        Returns:
            包含 AI 接口占位说明的结果。
        """

        if not isinstance(input_data, Mapping):
            raise TypeError("input_data 必须是映射类型")

        return {"answer": "AI助手接口"}
