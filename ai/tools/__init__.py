"""描述 AI 只能调用的只读工具白名单。"""

from .registry import TOOL_DESCRIPTIONS, allowed_tool_names

__all__ = ["TOOL_DESCRIPTIONS", "allowed_tool_names"]
