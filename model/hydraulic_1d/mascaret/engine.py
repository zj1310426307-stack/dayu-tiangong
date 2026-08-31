"""Production MASCARET implementation of the unified Hydraulic1DEngine."""

from __future__ import annotations

from time import monotonic

from model.hydraulic_1d.contracts import Hydraulic1DModel, HydraulicResult
from model.hydraulic_1d.engine import Hydraulic1DEngine, Hydraulic1DExecutionContext
from model.hydraulic_1d.errors import Hydraulic1DRuntimeUnavailable
from model.hydraulic_1d.mascaret.adapter import MascaretModelBuilder
from model.hydraulic_1d.mascaret.config import (
    MASCARET_ENGINE_ID,
    MASCARET_RUNTIME_SKIP_REASON,
    MASCARET_VERSION,
    MascaretRuntimeConfig,
)
from model.hydraulic_1d.mascaret.parser import MascaretResultParser
from model.hydraulic_1d.mascaret.runtime import (
    MascaretRuntime,
    MascaretRuntimeRequest,
    create_mascaret_runtime,
)
from model.hydraulic_1d.mascaret.workspace import MascaretJobWorkspace


RUNTIME_HEARTBEAT_INTERVAL_SECONDS = 15.0


class MascaretEngine(Hydraulic1DEngine):
    """Coordinate validation, model generation, external execution, and parsing."""

    def __init__(
        self,
        config: MascaretRuntimeConfig | None = None,
        *,
        runtime: MascaretRuntime | None = None,
        builder: MascaretModelBuilder | None = None,
        parser: MascaretResultParser | None = None,
    ) -> None:
        """Inject seams for deterministic tests while defaulting to real runtime config."""

        self.config = config or MascaretRuntimeConfig.from_environment()
        self.runtime = runtime or create_mascaret_runtime(self.config)
        self.builder = builder or MascaretModelBuilder()
        self.parser = parser or MascaretResultParser()

    @property
    def engine_id(self) -> str:
        """Return the stable external engine identifier."""

        return MASCARET_ENGINE_ID

    @property
    def engine_version(self) -> str:
        """Return the officially verified and adapter-locked release."""

        return MASCARET_VERSION

    def validate(self, model: Hydraulic1DModel) -> None:
        """Delegate all capability decisions to the shared model validator."""

        self.builder.validator.validate(model)

    def availability(self) -> tuple[bool, str]:
        """Expose runtime readiness without ever claiming a calculation occurred."""

        return self.runtime.availability()

    def run(
        self,
        model: Hydraulic1DModel,
        context: Hydraulic1DExecutionContext,
    ) -> HydraulicResult:
        """Execute one job in one unique workspace and return parsed Dayu records."""

        self.validate(model)
        available, reason = self.runtime.availability()
        if not available:
            raise Hydraulic1DRuntimeUnavailable(
                f"{MASCARET_RUNTIME_SKIP_REASON}: {reason}"
            )
        if context.progress_callback is not None:
            context.progress_callback(5.0, {"phase": "validated"})
        root = context.workspace_root or self.config.workspace_root
        workspace = MascaretJobWorkspace.create(
            root,
            simulation_id=model.simulation_id,
            job_id=context.job_id,
        )
        try:
            prepared = self.builder.build(model, workspace.path)
            if context.progress_callback is not None:
                context.progress_callback(20.0, {"phase": "prepared"})
            last_heartbeat = monotonic()

            def supervise() -> bool:
                """Poll cancellation and keep a long native run's lease alive."""

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
                MascaretRuntimeRequest(
                    workspace=prepared.workspace,
                    case_file=prepared.case_file,
                    result_file=prepared.result_file,
                ),
                cancel_check=supervise,
            )
            if context.progress_callback is not None:
                context.progress_callback(90.0, {"phase": "parsing"})
            result = self.parser.parse(
                model,
                prepared,
                runtime_seconds=execution.elapsed_seconds,
            )
            result = result.model_copy(
                update={
                    "diagnostics": {
                        **result.diagnostics,
                        "runtime_provenance": reason,
                    }
                }
            )
            if context.progress_callback is not None:
                context.progress_callback(100.0, {"phase": "complete"})
            return result
        finally:
            # Raw MASCARET files are an internal interchange format. The unified
            # records have already been parsed before a successful return.
            workspace.cleanup()
