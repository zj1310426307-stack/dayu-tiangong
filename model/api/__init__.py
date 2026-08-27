"""模型引擎输入配置适配接口，不包含 FastAPI 路由。"""

from model.api.contracts import build_solver_config
from model.api.v4 import ModelInputV4, parse_model_input_v4
from model.api.v4_lite import (
    MODEL_INPUT_V4_LITE,
    FixedStructureControlInput,
    HydraulicExternalPumpInput,
    OneShotStageAboveControlInput,
    PumpEfficiencyCurveInput,
    PumpHeadCurveInput,
    PumpOutletStageSeriesInput,
    PumpSystemLossInput,
    PumpUnitConfigurationInput,
    StageHysteresisMinimumRuntimeInput,
    StructureControlInput,
    V4_LITE_SOLVER_TUPLE,
    V4LiteInput,
    parse_v4_lite_input,
)

__all__ = [
    "MODEL_INPUT_V4_LITE",
    "ModelInputV4",
    "FixedStructureControlInput",
    "HydraulicExternalPumpInput",
    "OneShotStageAboveControlInput",
    "PumpEfficiencyCurveInput",
    "PumpHeadCurveInput",
    "PumpOutletStageSeriesInput",
    "PumpSystemLossInput",
    "PumpUnitConfigurationInput",
    "StageHysteresisMinimumRuntimeInput",
    "StructureControlInput",
    "V4_LITE_SOLVER_TUPLE",
    "V4LiteInput",
    "build_solver_config",
    "parse_v4_lite_input",
    "parse_model_input_v4",
]
