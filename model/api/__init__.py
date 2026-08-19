"""模型引擎输入配置适配接口，不包含 FastAPI 路由。"""

from model.api.contracts import build_solver_config
from model.api.v4_lite import (
    MODEL_INPUT_V4_LITE,
    V4_LITE_SOLVER_TUPLE,
    V4LiteInput,
    parse_v4_lite_input,
)

__all__ = [
    "MODEL_INPUT_V4_LITE",
    "V4_LITE_SOLVER_TUPLE",
    "V4LiteInput",
    "build_solver_config",
    "parse_v4_lite_input",
]
