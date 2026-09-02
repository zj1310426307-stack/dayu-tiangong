"""Engine-neutral factory used by backend workers and command-line entry points."""

from __future__ import annotations

from importlib import import_module

from model.hydraulic_1d.engine import Hydraulic1DEngine
from model.hydraulic_1d.errors import (
    Hydraulic1DRuntimeUnavailable,
    Hydraulic1DValidationError,
)
from model.hydraulic_1d.mascaret.engine import MascaretEngine
from model.hydraulic_1d.registry import (
    DEFAULT_HYDRAULIC_1D_ENGINE_ID,
    DFLOW_FM_ENGINE_ID,
)


_DFLOW_FM_ENGINE_MODULE = "model.hydraulic_1d.dflow_fm.engine"


def create_hydraulic_1d_engine(
    engine_id: str = DEFAULT_HYDRAULIC_1D_ENGINE_ID,
) -> Hydraulic1DEngine:
    """Create one explicit engine while preserving MASCARET as the default route."""

    if engine_id == DEFAULT_HYDRAULIC_1D_ENGINE_ID:
        return MascaretEngine()
    if engine_id != DFLOW_FM_ENGINE_ID:
        raise Hydraulic1DValidationError(
            "HYDRAULIC_ENGINE_NOT_REGISTERED",
            f"hydraulic engine is not registered: {engine_id}",
            field_path="engine_id",
        )

    try:
        module = import_module(_DFLOW_FM_ENGINE_MODULE)
        engine_type = module.DFlowFMEngine
        engine = engine_type()
    except (AttributeError, ModuleNotFoundError) as exc:
        raise Hydraulic1DRuntimeUnavailable(
            "the registered D-Flow FM adapter is not installed in this build",
            code="DFLOW_FM_ADAPTER_UNAVAILABLE",
        ) from exc
    if not isinstance(engine, Hydraulic1DEngine):
        raise Hydraulic1DRuntimeUnavailable(
            "DFlowFMEngine does not implement Hydraulic1DEngine",
            code="DFLOW_FM_ADAPTER_INVALID",
        )
    return engine
