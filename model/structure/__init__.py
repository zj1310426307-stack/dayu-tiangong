"""闸门与泵站简化水力接口。"""

from model.structure.gate import gate_discharge
from model.structure.pump import pump_discharge

__all__ = ["gate_discharge", "pump_discharge"]
