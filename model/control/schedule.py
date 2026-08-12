"""人工时序动作和事件时刻对齐策略。"""

from dataclasses import dataclass

from model.control.policy import ControlTarget, HydraulicObservation


@dataclass(frozen=True)
class ScheduledAction:
    """保存一个时序控制动作；目标值单位由 command_type 决定。"""

    id: int | None
    time_seconds: float
    structure_type: str
    structure_id: int
    command_type: str
    target_value: float
    interpolation: str = "step"
    priority: int = 0


@dataclass(frozen=True)
class ManualSchedulePolicy:
    """按阶梯或线性方式返回给定时刻的人工计划目标。"""

    actions: tuple[ScheduledAction, ...]

    @property
    def event_times(self) -> tuple[float, ...]:
        """返回求解器必须精确对齐的动作时刻。"""

        return tuple(sorted({item.time_seconds for item in self.actions}))

    def targets_at(
        self, time_seconds: float, state: HydraulicObservation
    ) -> list[ControlTarget]:
        """对每个设备/命令返回时刻前最后一个动作，线性动作按相邻值插值。"""

        del state
        grouped: dict[tuple[str, int, str], list[ScheduledAction]] = {}
        for action in self.actions:
            grouped.setdefault(
                (action.structure_type, action.structure_id, action.command_type), []
            ).append(action)
        targets: list[ControlTarget] = []
        for (structure_type, structure_id, command_type), actions in grouped.items():
            ordered = sorted(actions, key=lambda item: (item.time_seconds, item.id or 0))
            candidates = [item for item in ordered if item.time_seconds <= time_seconds]
            if not candidates:
                continue
            current = candidates[-1]
            value = current.target_value
            if current.interpolation == "linear":
                following = next(
                    (item for item in ordered if item.time_seconds > time_seconds), None
                )
                if following is not None:
                    ratio = (time_seconds - current.time_seconds) / (
                        following.time_seconds - current.time_seconds
                    )
                    value += ratio * (following.target_value - current.target_value)
            targets.append(
                ControlTarget(
                    structure_type,
                    structure_id,
                    command_type,
                    value,
                    current.priority,
                    "manual",
                    current.id,
                )
            )
        return targets
