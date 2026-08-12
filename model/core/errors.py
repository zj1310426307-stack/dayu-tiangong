"""水动力引擎对外暴露的可诊断异常。"""


class HydraulicInputError(ValueError):
    """表示快照、断面、参数或边界条件不满足计算前提。"""


class HydraulicStabilityError(RuntimeError):
    """表示计算过程中出现非有限值、步长耗尽或水深失稳。"""


class HydraulicCancelledError(RuntimeError):
    """Worker 请求协作式取消且求解器在安全检查点停止时抛出。"""
