"""Verify runtime absence, supervision, and workspace ownership are explicit."""

from hashlib import sha256
from pathlib import Path
from shutil import copyfile

import pytest

from model.hydraulic_1d import Hydraulic1DExecutionContext
from model.hydraulic_1d.errors import (
    Hydraulic1DCancelled,
    Hydraulic1DExecutionError,
    Hydraulic1DRuntimeUnavailable,
    Hydraulic1DValidationError,
)
from model.hydraulic_1d.mascaret import (
    MASCARET_RUNTIME_SKIP_REASON,
    MascaretEngine,
    MascaretJobWorkspace,
    MascaretRuntimeConfig,
)
from model.hydraulic_1d.mascaret.runtime import (
    MascaretRuntime,
    MascaretRuntimeRequest,
    MascaretRuntimeResult,
    create_mascaret_runtime,
)
from tests.hydraulic_1d.helpers import model_fixture


FIXTURE = Path(__file__).parents[1] / "fixtures" / "mascaret" / "opthyca_minimal.opt"


class _FixtureRuntime(MascaretRuntime):
    """Stand in only for process supervision while using a real parser fixture."""

    def __init__(self, *, fail: bool = False) -> None:
        """Choose whether execution reaches the parser or fails first."""

        self.fail = fail

    def availability(self) -> tuple[bool, str]:
        """Expose this deterministic test seam as available."""

        return True, "fixture runtime"

    def execute(
        self,
        request: MascaretRuntimeRequest,
        *,
        cancel_check=None,
    ) -> MascaretRuntimeResult:
        """Exercise heartbeat polling and then copy official-shaped output."""

        if cancel_check is not None:
            assert cancel_check() is False
        if self.fail:
            raise Hydraulic1DExecutionError("fixture runtime failed")
        copyfile(FIXTURE, request.result_file)
        return MascaretRuntimeResult(
            command=("fixture",),
            return_code=0,
            elapsed_seconds=0.01,
            stdout="",
            stderr="",
            result_file=request.result_file,
        )


def test_each_job_gets_a_unique_workspace(tmp_path) -> None:
    """Use a random final component even when simulation and job identities repeat."""

    left = MascaretJobWorkspace.create(tmp_path, simulation_id="sim", job_id="job")
    right = MascaretJobWorkspace.create(tmp_path, simulation_id="sim", job_id="job")

    assert left.path != right.path
    assert left.path.parent == right.path.parent == tmp_path.resolve()


def test_disabled_runtime_never_reports_a_fake_success(tmp_path) -> None:
    """Expose the mandated skip token through the real production engine boundary."""

    config = MascaretRuntimeConfig.from_environment(
        {
            "MASCARET_ENABLED": "0",
            "MASCARET_RUNTIME": "cli",
            "HYDRAULIC_WORKSPACE_ROOT": str(tmp_path),
        }
    )

    with pytest.raises(Hydraulic1DRuntimeUnavailable, match=MASCARET_RUNTIME_SKIP_REASON):
        MascaretEngine(config).run(
            model_fixture(),
            Hydraulic1DExecutionContext(job_id="job"),
        )


def test_real_mascaret_runtime_when_available(tmp_path) -> None:
    """Run no substitute engine; explicitly skip when official MASCARET is absent."""

    config = MascaretRuntimeConfig.from_environment()
    engine = MascaretEngine(config)
    available, reason = engine.availability()
    if not available:
        pytest.skip(f"{MASCARET_RUNTIME_SKIP_REASON}: {reason}")
    engine.run(
        model_fixture(),
        Hydraulic1DExecutionContext(job_id="runtime-integration", workspace_root=tmp_path),
    )


def test_cli_runtime_terminates_a_cancelled_external_process(tmp_path) -> None:
    """Cancellation must stop the child process instead of only changing DB state."""

    launcher = tmp_path / "mascaret.py"
    launcher.write_text(
        "import time\ntime.sleep(30)\n",
        encoding="utf-8",
    )
    workspace = MascaretJobWorkspace.create(
        tmp_path / "workspaces",
        simulation_id="cancel-test",
        job_id="cancel-attempt",
    )
    case_file = workspace.path / "case.xcas"
    case_file.write_text("<fichierCas />\n", encoding="ascii")
    launcher_sha256 = sha256(launcher.read_bytes()).hexdigest()
    config = MascaretRuntimeConfig.from_environment(
        {
            "MASCARET_ENABLED": "1",
            "MASCARET_RUNTIME": "cli",
            "MASCARET_EXECUTABLE": str(launcher),
            "MASCARET_EXECUTABLE_SHA256": launcher_sha256,
            "MASCARET_TIMEOUT": "60",
            "HYDRAULIC_WORKSPACE_ROOT": str(tmp_path / "workspaces"),
        }
    )

    with pytest.raises(Hydraulic1DCancelled, match="cancelled"):
        create_mascaret_runtime(config).execute(
            MascaretRuntimeRequest(
                workspace=workspace.path,
                case_file=case_file,
                result_file=workspace.path / "results.opt",
            ),
            cancel_check=lambda: True,
        )
    workspace.cleanup()


@pytest.mark.parametrize("value", ["nan", "inf", "-inf"])
def test_runtime_timeout_rejects_non_finite_values(tmp_path, value) -> None:
    """NaN and infinities must not disable the external-process timeout."""

    with pytest.raises(Hydraulic1DValidationError, match="finite and positive"):
        MascaretRuntimeConfig.from_environment(
            {
                "MASCARET_ENABLED": "0",
                "MASCARET_TIMEOUT": value,
                "HYDRAULIC_WORKSPACE_ROOT": str(tmp_path),
            }
        )


def test_engine_cleans_workspace_after_success_and_emits_runtime_heartbeat(
    tmp_path,
    monkeypatch,
) -> None:
    """Persist no private engine files and refresh the lease during execution."""

    monkeypatch.setattr(
        "model.hydraulic_1d.mascaret.engine.RUNTIME_HEARTBEAT_INTERVAL_SECONDS",
        0.0,
    )
    progress: list[tuple[float, str]] = []
    config = MascaretRuntimeConfig.from_environment(
        {
            "MASCARET_ENABLED": "0",
            "HYDRAULIC_WORKSPACE_ROOT": str(tmp_path),
        }
    )
    result = MascaretEngine(config, runtime=_FixtureRuntime()).run(
        model_fixture(),
        Hydraulic1DExecutionContext(
            job_id="cleanup-success",
            progress_callback=lambda value, detail: progress.append(
                (value, str(detail["phase"]))
            ),
        ),
    )

    assert result.records
    assert result.artifacts == ()
    assert (50.0, "executing") in progress
    assert list(tmp_path.iterdir()) == []


def test_engine_cleans_workspace_after_runtime_failure(tmp_path) -> None:
    """A native-process failure must not leak its generated case workspace."""

    config = MascaretRuntimeConfig.from_environment(
        {
            "MASCARET_ENABLED": "0",
            "HYDRAULIC_WORKSPACE_ROOT": str(tmp_path),
        }
    )
    with pytest.raises(Hydraulic1DExecutionError, match="fixture runtime failed"):
        MascaretEngine(config, runtime=_FixtureRuntime(fail=True)).run(
            model_fixture(),
            Hydraulic1DExecutionContext(job_id="cleanup-failure"),
        )

    assert list(tmp_path.iterdir()) == []
