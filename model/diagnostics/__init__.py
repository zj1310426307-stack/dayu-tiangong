"""数值诊断公共入口。"""

from model.diagnostics.water_balance import WaterBalance, evaluate_water_balance

__all__ = ["WaterBalance", "evaluate_water_balance"]
