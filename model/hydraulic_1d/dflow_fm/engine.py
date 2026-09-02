"""Development-only D-Flow FM engine orchestration through the official DIMR boundary."""

from __future__ import annotations

from hashlib import sha256
from pathlib import Path
from time import monotonic

from model.hydraulic_1d.capabilities import (
    CapabilityExecutionPolicy,
    enforce_compatibility,
)
from model.hydraulic_1d.contracts import Hydraulic1DModel, HydraulicResult
from model.hydraulic_1d.controlled import (
    CompiledControl,
    ControlledHydraulic1DEngine,
    ControlledHydraulic1DRun,
    ControlledHydraulicResult,
)
from model.hydraulic_1d.dflow_fm.adapter import DFlowFMModelBuilder
from model.hydraulic_1d.dflow_fm.config import DFlowRuntimeConfig
from model.hydraulic_1d.dflow_fm.parser import DFlowFMResultParser
from model.hydraulic_1d.dflow_fm.runtime import (
    DFlowRuntime,
    DFlowRuntimeRequest,
    create_dflow_runtime,
)
from model.hydraulic_1d.dflow_fm.workspace import DFlowJobWorkspace
from model.hydraulic_1d.engine import Hydraulic1DExecutionContext
from model.hydraulic_1d.errors import (
    Hydraulic1DResultError,
    Hydraulic1DRuntimeUnavailable,
    Hydraulic1DValidationError,
)
from model.hydraulic_1d.registry import (
    DFLOW_FM_ADAPTER_ID,
    DFLOW_FM_ENGINE_ID,
    DFLOW_FM_ENGINE_VERSION,
)


RUNTIME_HEARTBEAT_INTERVAL_SECONDS = 15.0


class DFlowFMEngine(ControlledHydraulic1DEngine):
    """Build, execute, and parse the audited base-1D D-Flow subset.

    The ordinary ``run`` path closes the DF01-shaped base-hydraulics adapter.
    Controlled execution remains explicitly unavailable until an accepted
    D-RTC/FBC artifact compiler exists; no Python time-step coupler is used as
    a substitute.
    """

    def __init__(
        self,
        config: DFlowRuntimeConfig | None = None,
        *,
        runtime: DFlowRuntime | None = None,
        builder: DFlowFMModelBuilder | None = None,
        parser: DFlowFMResultParser | None = None,
    ) -> None:
        self.config = config or DFlowRuntimeConfig.from_environment()
        self.runtime = runtime or create_dflow_runtime(self.config)
        self.builder = builder or DFlowFMModelBuilder()
        self.parser = parser or DFlowFMResultParser()

    @property
    def engine_id(self) -> str:
        """Return the explicit secondary-engine registration."""

        return DFLOW_FM_ENGINE_ID

    @property
    def engine_version(self) -> str:
        """Return the pinned FM-suite release identity."""

        return DFLOW_FM_ENGINE_VERSION

    def availability(self) -> tuple[bool, str]:
        """Report the reviewed DIMR runtime state without creating a workspace."""

        return self.runtime.availability()

    def runtime_provenance(self) -> dict[str, object]:
        """Expose complete provenance only when its reviewed manifest is valid."""

        available, detail, provenance = self.runtime.verified_provenance()
        if not available:
            return {
                "engine": self.engine_id,
                "engine_version": self.engine_version,
                "adapter_id": DFLOW_FM_ADAPTER_ID,
                "runtime_mode": self.config.mode,
                "provenance_complete": False,
                "runtime_available": False,
                "detail": detail,
            }
        if provenance is None:  # pragma: no cover - guarded by runtime contract
            raise Hydraulic1DRuntimeUnavailable(
                "reviewed runtime returned no verified provenance",
                code="DFLOW_RUNTIME_BLOCKED",
            )
        return {
            **provenance,
            "engine": self.engine_id,
            "engine_version": self.engine_version,
            "adapter_id": DFLOW_FM_ADAPTER_ID,
            "runtime_mode": self.config.mode,
            "provenance_complete": True,
            "runtime_available": True,
        }

    def validate(self, model: Hydraulic1DModel) -> None:
        """Validate the base model; controlled structure specs live outside it."""

        self.builder.validator.validate_base(model)
        enforce_compatibility(
            model,
            engine=self.engine_id,
            engine_version=self.engine_version,
            execution_policy=CapabilityExecutionPolicy.SYNTHETIC_NUMERICAL_ONLY,
            development_mode=True,
            production_mode=False,
        )

    def run(
        self,
        model: Hydraulic1DModel,
        context: Hydraulic1DExecutionContext,
    ) -> HydraulicResult:
        """Run one isolated base-1D job through DIMR and return unified H/Q."""

        self.validate(model)
        active_structures = [
            item.id for item in model.structures if item.status == "active"
        ]
        if active_structures:
            raise Hydraulic1DValidationError(
                "DFLOW_STRUCTURE_SPECS_REQUIRED",
                (
                    "ordinary D-Flow execution cannot infer Gate/Pump specs; "
                    f"active structures={active_structures}"
                ),
                field_path="structures",
            )
        available, readiness_detail = self.runtime.availability()
        if not available:
            raise Hydraulic1DRuntimeUnavailable(
                readiness_detail,
                code="DFLOW_RUNTIME_BLOCKED",
            )
        if context.progress_callback is not None:
            context.progress_callback(5.0, {"phase": "validated"})
        workspace = DFlowJobWorkspace.create(
            context.workspace_root or self.config.workspace_root,
            simulation_id=model.simulation_id,
            job_id=context.job_id,
        )
        build_started = monotonic()
        prepared = self.builder.build(model, workspace)
        build_seconds = monotonic() - build_started
        if context.progress_callback is not None:
            context.progress_callback(20.0, {"phase": "prepared"})
        last_heartbeat = monotonic()

        def supervise() -> bool:
            nonlocal last_heartbeat
            if context.cancel_check is not None and context.cancel_check():
                return True
            now = monotonic()
            if (
                context.progress_callback is not None
                and now - last_heartbeat >= RUNTIME_HEARTBEAT_INTERVAL_SECONDS
            ):
                context.progress_callback(50.0, {"phase": "executing"})
                last_heartbeat = now
            return False

        execution = self.runtime.execute(
            DFlowRuntimeRequest(
                workspace=prepared.job_workspace,
                dimr_config=prepared.dimr_config_file,
            ),
            cancel_check=supervise,
        )
        if context.progress_callback is not None:
            context.progress_callback(90.0, {"phase": "parsing"})
        parse_started = monotonic()
        result = self.parser.parse(
            model,
            prepared,
            runtime_seconds=execution.elapsed_seconds,
        )
        parse_seconds = monotonic() - parse_started
        if (
            result.simulation_id != model.simulation_id
            or result.scenario_id != model.scenario_id
            or result.engine != self.engine_id
            or result.engine_version != self.engine_version
        ):
            raise Hydraulic1DResultError(
                "D-Flow parser returned a result with a mismatched model or engine identity",
                code="DFLOW_RESULT_IDENTITY_MISMATCH",
            )
        manifest_sha256 = sha256(prepared.manifest_file.read_bytes()).hexdigest()
        result = result.model_copy(
            update={
                "diagnostics": {
                    **result.diagnostics,
                    "model_build_seconds": build_seconds,
                    "parser_seconds": parse_seconds,
                    "runtime_provenance": execution.provenance,
                    "runtime_verification": readiness_detail,
                    "native_manifest_sha256": manifest_sha256,
                    "evidence_class": "SYNTHETIC_NUMERICAL_ONLY",
                    "real_engineering_validation": False,
                    "real_equipment_command": False,
                    "plc_scada_connected": False,
                }
            }
        )
        if context.progress_callback is not None:
            context.progress_callback(100.0, {"phase": "complete"})
        return result

    def validate_controlled_model(self, run: ControlledHydraulic1DRun) -> None:
        """Validate immutable identities, then reject the uncompiled control layer."""

        if (
            run.engine_selection.engine_id != self.engine_id
            or run.engine_selection.engine_version != self.engine_version
        ):
            raise Hydraulic1DValidationError(
                "CONTROLLED_ENGINE_SELECTION_MISMATCH",
                "controlled run is not bound to the selected D-Flow FM release",
                field_path="engine_selection",
            )
        self.builder.validator.validate_base(run.hydraulic_model)
        raise Hydraulic1DRuntimeUnavailable(
            "no accepted D-RTC/FBC artifact compiler is available",
            code="DRTC_COMPILER_BLOCKED",
        )

    def compile_control(
        self,
        run: ControlledHydraulic1DRun,
        workspace: Path,
    ) -> CompiledControl:
        """Never emit substitute RTC files while exact FBC semantics are unproven."""

        del workspace
        self.validate_controlled_model(run)
        raise AssertionError("validate_controlled_model must fail closed")

    def run_controlled(
        self,
        run: ControlledHydraulic1DRun,
        context: Hydraulic1DExecutionContext,
    ) -> ControlledHydraulicResult:
        """Keep coupled Gate/Pump execution closed until D-RTC acceptance exists."""

        del context
        self.validate_controlled_model(run)
        raise AssertionError("validate_controlled_model must fail closed")

    def parse_controlled_results(
        self,
        run: ControlledHydraulic1DRun,
        workspace: Path,
    ) -> ControlledHydraulicResult:
        """Reject results that cannot be tied to an accepted coupled execution."""

        del workspace
        self.validate_controlled_model(run)
        raise AssertionError("validate_controlled_model must fail closed")


__all__ = ["DFlowFMEngine", "RUNTIME_HEARTBEAT_INTERVAL_SECONDS"]
