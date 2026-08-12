"""纯模型层调度命令审计事件。"""

from dataclasses import asdict, dataclass
from typing import Any


@dataclass(frozen=True)
class ControlEvent:
    """记录命令来源、请求值、实际值、结果和原因。"""

    time_seconds: float
    source_type: str
    source_id: int | None
    structure_type: str
    structure_id: int
    requested_command: dict[str, Any]
    applied_command: dict[str, Any] | None
    outcome: str
    reason: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """返回可持久化 JSON 映射。"""

        return asdict(self)
