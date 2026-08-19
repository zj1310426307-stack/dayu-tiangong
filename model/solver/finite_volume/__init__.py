"""Public contracts for the opt-in Dayu Saint-Venant finite-volume MVP."""

from model.solver.finite_volume.boundary import (
    BoundaryPair,
    BoundarySeries,
    DownstreamStageBoundary,
    UpstreamDischargeBoundary,
)
from model.solver.finite_volume.diagnostics import (
    BoundaryCoverageError,
    FiniteVolumeError,
    NumericalStateError,
    QualityGateResult,
    StabilityError,
    inspect_state,
    require_quality,
)
from model.solver.finite_volume.flux import (
    GRAVITY,
    ConservedVector,
    NumericalFlux,
    hll_flux,
    maximum_signal_speed,
    physical_flux,
    rusanov_flux,
    wave_speed,
)
from model.solver.finite_volume.friction import (
    apply_manning_friction,
    semi_implicit_manning,
)
from model.solver.finite_volume.geometry import pressure_moment, pressure_moment_from_area
from model.solver.finite_volume.integrator import (
    CflEstimate,
    StepBudget,
    StepResult,
    advance_with_retries,
    cfl_number_for_step,
    estimate_cfl_time_step,
    forward_euler_stage,
    ssp_rk2_step,
)
from model.solver.finite_volume.mesh import (
    FiniteVolumeCell,
    FiniteVolumeFace,
    FiniteVolumeMesh,
    SectionGeometryLike,
)
from model.solver.finite_volume.protocols import (
    BranchNetworkSolver,
    ExternalComparison,
    NodeSolver,
    RoughnessZoneSolver,
    StructureSolver,
)
from model.solver.finite_volume.reconstruction import (
    HydrostaticReconstruction,
    InterfaceFlux,
    hydrostatic_interface_flux,
    hydrostatic_reconstruct,
)
from model.solver.finite_volume.solver import (
    SingleBranchConfig,
    SingleBranchDiagnostics,
    SingleBranchResult,
    solve_single_branch,
    storage,
)
from model.solver.finite_volume.state import HydraulicState, SolverDiagnostics
from model.solver.finite_volume.structures import (
    FixedGate,
    OnOffPump,
    StructureStageContext,
    StructureStageFlow,
)

__all__ = [
    "GRAVITY",
    "BoundaryCoverageError",
    "BoundaryPair",
    "BoundarySeries",
    "BranchNetworkSolver",
    "CflEstimate",
    "ConservedVector",
    "DownstreamStageBoundary",
    "ExternalComparison",
    "FiniteVolumeCell",
    "FiniteVolumeError",
    "FiniteVolumeFace",
    "FiniteVolumeMesh",
    "FixedGate",
    "HydraulicState",
    "HydrostaticReconstruction",
    "InterfaceFlux",
    "NodeSolver",
    "NumericalFlux",
    "NumericalStateError",
    "OnOffPump",
    "QualityGateResult",
    "RoughnessZoneSolver",
    "SectionGeometryLike",
    "SingleBranchConfig",
    "SingleBranchDiagnostics",
    "SingleBranchResult",
    "SolverDiagnostics",
    "StabilityError",
    "StepBudget",
    "StepResult",
    "StructureSolver",
    "StructureStageContext",
    "StructureStageFlow",
    "UpstreamDischargeBoundary",
    "advance_with_retries",
    "apply_manning_friction",
    "cfl_number_for_step",
    "estimate_cfl_time_step",
    "forward_euler_stage",
    "hll_flux",
    "hydrostatic_interface_flux",
    "hydrostatic_reconstruct",
    "inspect_state",
    "maximum_signal_speed",
    "physical_flux",
    "pressure_moment",
    "pressure_moment_from_area",
    "require_quality",
    "rusanov_flux",
    "semi_implicit_manning",
    "solve_single_branch",
    "ssp_rk2_step",
    "storage",
    "wave_speed",
]
