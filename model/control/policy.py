"""统一的控制目标、观测和组合策略接口。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class HydraulicObservation:
    """保存规则可读取的白名单观测量，不包含任意表达式上下文。"""

    elapsed_time: float
    values: dict[tuple[str, int | None], float]

    def value(self, observation_type: str, object_id: int | None) -> float:
        """读取一个已由引擎明确提供的白名单观测。"""

        if observation_type == "elapsed_time":
            return self.elapsed_time
        key = (observation_type, object_id)
        if key not in self.values:
            raise KeyError(f"缺少观测 {observation_type}:{object_id}")
        return self.values[key]


@dataclass(frozen=True)
class ControlTarget:
    """描述一个设备控制请求及其来源和优先级。"""

    structure_type: str
    structure_id: int
    command_type: str
    target_value: float
    priority: int
    source_type: str
    source_id: int | None


class ControlPolicy(Protocol):
    """所有人工/规则调度策略必须实现的纯函数式接口。"""

    def targets_at(
        self, time_seconds: float, state: HydraulicObservation
    ) -> list[ControlTarget]: ...


@dataclass
class CompositeControlPolicy:
    """组合人工和规则目标，并按设备/命令保留最高优先级。"""

    policies: tuple[ControlPolicy, ...]
    conflict_count: int = 0

    def targets_at(
        self, time_seconds: float, state: HydraulicObservation
    ) -> list[ControlTarget]:
        """稳定解决同设备同命令冲突，优先级相同时后注册策略获胜。"""

        selected: dict[tuple[str, int, str], ControlTarget] = {}
        for policy in self.policies:
            for target in policy.targets_at(time_seconds, state):
                key = (target.structure_type, target.structure_id, target.command_type)
                existing = selected.get(key)
                if existing is not None:
                    self.conflict_count += 1
                if existing is None or target.priority >= existing.priority:
                    selected[key] = target
        return sorted(
            selected.values(),
            key=lambda item: (item.structure_type, item.structure_id, item.command_type),
        )
