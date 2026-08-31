"""Public, solver-neutral API for Dayu production one-dimensional hydraulics."""

from model.hydraulic_1d.contracts import (
    HYDRAULIC_1D_INPUT_SCHEMA,
    HYDRAULIC_RESULT_SCHEMA,
    BoundaryCondition,
    CrossSectionPoint,
    Hydraulic1DModel,
    HydraulicBranch,
    HydraulicCrossSection,
    HydraulicResult,
    HydraulicResultRecord,
    HydraulicStructure,
    InitialCondition,
    RoughnessZone,
    SectionInitialState,
    SimulationSettings,
    TimeValue,
)
from model.hydraulic_1d.engine import Hydraulic1DEngine, Hydraulic1DExecutionContext
from model.hydraulic_1d.factory import create_hydraulic_1d_engine
from model.hydraulic_1d.registry import (
    DEFAULT_HYDRAULIC_1D_ENGINE_ID,
    DEFAULT_HYDRAULIC_1D_ENGINE_VERSION,
)
from model.hydraulic_1d.benchmark import (
    BenchmarkTimer,
    HydraulicBenchmarkMetrics,
    evaluate_hydraulic_benchmark,
    rectangular_manning_discharge,
    root_mean_square_error,
)
from model.hydraulic_1d.errors import (
    Hydraulic1DCancelled,
    Hydraulic1DError,
    Hydraulic1DExecutionError,
    Hydraulic1DResultError,
    Hydraulic1DRuntimeUnavailable,
    Hydraulic1DValidationError,
)

__all__ = [
    "HYDRAULIC_1D_INPUT_SCHEMA",
    "HYDRAULIC_RESULT_SCHEMA",
    "BoundaryCondition",
    "BenchmarkTimer",
    "CrossSectionPoint",
    "DEFAULT_HYDRAULIC_1D_ENGINE_ID",
    "DEFAULT_HYDRAULIC_1D_ENGINE_VERSION",
    "Hydraulic1DEngine",
    "Hydraulic1DCancelled",
    "Hydraulic1DError",
    "Hydraulic1DExecutionContext",
    "Hydraulic1DExecutionError",
    "Hydraulic1DModel",
    "Hydraulic1DResultError",
    "Hydraulic1DRuntimeUnavailable",
    "Hydraulic1DValidationError",
    "HydraulicBranch",
    "HydraulicBenchmarkMetrics",
    "HydraulicCrossSection",
    "HydraulicResult",
    "HydraulicResultRecord",
    "HydraulicStructure",
    "InitialCondition",
    "RoughnessZone",
    "SectionInitialState",
    "SimulationSettings",
    "TimeValue",
    "evaluate_hydraulic_benchmark",
    "rectangular_manning_discharge",
    "root_mean_square_error",
    "create_hydraulic_1d_engine",
]
