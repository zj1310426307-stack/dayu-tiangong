"""闸门与泵站简化水力接口。"""

from model.structure.gate import GateModel, gate_discharge
from model.structure.pump import PumpModel, pump_discharge

__all__ = ["GateModel", "PumpModel", "gate_discharge", "pump_discharge"]
