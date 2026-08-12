"""从 Phase 2 参数和任务覆盖值构建纯引擎配置。"""

from collections.abc import Mapping
from typing import Any

from model.core.errors import HydraulicInputError
from model.core.types import SolverConfig


def _parameter_values(snapshot: Mapping[str, Any]) -> dict[str, float]:
    """把同版本模型参数压缩为按名称索引的数值映射。"""

    parameters = snapshot.get("parameters", [])
    if not isinstance(parameters, list):
        raise HydraulicInputError("parameters 必须是数组")
    return {
        str(item["parameter_name"]): float(item["value"])
        for item in parameters
        if "parameter_name" in item and "value" in item
    }


def build_solver_config(
    snapshot: Mapping[str, Any], overrides: Mapping[str, Any] | None = None
) -> SolverConfig:
    """按“任务覆盖值优先、版本参数其次、默认值最后”构建求解配置。"""

    parameters = _parameter_values(snapshot)
    explicit = dict(overrides or {})

    def number(name: str, default: float | None) -> float | None:
        """读取并转换一个可选数值参数。"""

        value = explicit.get(name)
        if value is None:
            value = parameters.get(name, default)
        return None if value is None else float(value)

    return SolverConfig(
        duration_seconds=float(number("duration_seconds", 3600.0)),
        requested_time_step=float(
            number("time_step_seconds", parameters.get("time_step", 60.0))
        ),
        output_interval=float(
            number("output_interval_seconds", parameters.get("output_interval", 300.0))
        ),
        cfl_number=float(number("cfl_number", parameters.get("cfl", 0.75))),
        initial_water_level=number(
            "initial_water_level", parameters.get("initial_water_level")
        ),
        initial_flow=float(number("initial_flow", parameters.get("initial_flow", 0.0))),
        minimum_depth=float(number("minimum_depth", parameters.get("minimum_depth", 0.05))),
    )
