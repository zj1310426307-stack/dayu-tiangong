"""对库容和内外通量执行量纲一致的水量平衡诊断。"""

from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class WaterBalance:
    """保存一次计算的水量收支，所有体积单位均为 m³。"""

    storage_change: float
    external_inflow_volume: float
    external_outflow_volume: float
    lateral_source_volume: float
    lateral_sink_volume: float
    gate_transfer_volume: float
    pump_transfer_volume: float
    balance_residual: float
    relative_balance_residual: float
    status: str

    def to_dict(self) -> dict[str, float | str]:
        """返回稳定的 JSON 映射。"""

        return asdict(self)


def evaluate_water_balance(
    *,
    initial_storage: float,
    final_storage: float,
    external_inflow_volume: float = 0.0,
    external_outflow_volume: float = 0.0,
    lateral_source_volume: float = 0.0,
    lateral_sink_volume: float = 0.0,
    gate_transfer_volume: float = 0.0,
    pump_transfer_volume: float = 0.0,
    warning_threshold: float = 1.0e-3,
    failure_threshold: float = 5.0e-3,
) -> WaterBalance:
    """计算全域守恒残差；内部闸泵转输只披露而不计入外部净收支。"""

    storage_change = final_storage - initial_storage
    net_external = (
        external_inflow_volume
        + lateral_source_volume
        - external_outflow_volume
        - lateral_sink_volume
    )
    residual = storage_change - net_external
    scale = max(
        abs(initial_storage),
        abs(storage_change),
        abs(external_inflow_volume) + abs(external_outflow_volume),
        1.0,
    )
    relative = abs(residual) / scale
    status = "pass" if relative <= warning_threshold else "warning"
    if relative > failure_threshold:
        status = "fail"
    return WaterBalance(
        storage_change=storage_change,
        external_inflow_volume=external_inflow_volume,
        external_outflow_volume=external_outflow_volume,
        lateral_source_volume=lateral_source_volume,
        lateral_sink_volume=lateral_sink_volume,
        gate_transfer_volume=gate_transfer_volume,
        pump_transfer_volume=pump_transfer_volume,
        balance_residual=residual,
        relative_balance_residual=relative,
        status=status,
    )
