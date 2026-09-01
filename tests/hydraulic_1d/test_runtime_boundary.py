"""Verify runtime absence, supervision, and workspace ownership are explicit."""

from concurrent.futures import ThreadPoolExecutor
from hashlib import sha256
from pathlib import Path
from shutil import copyfile

import pytest

from model.hydraulic_1d import Hydraulic1DExecutionContext
from model.hydraulic_1d.errors import (
    Hydraulic1DCancelled,
    Hydraulic1DExecutionError,
    Hydraulic1DRuntimeUnavailable,
    Hydraulic1DTimeout,
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
from model.hydraulic_1d.mascaret.workspace import read_workspace_marker
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

    with pytest.raises(
        Hydraulic1DRuntimeUnavailable, match=MASCARET_RUNTIME_SKIP_REASON
    ):
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
        Hydraulic1DExecutionContext(
            job_id="runtime-integration", workspace_root=tmp_path
        ),
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
            "MASCARET_BUILD_TIMESTAMP": "2026-08-31T00:00:00Z",
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


def test_engine_retains_bounded_diagnostics_after_runtime_failure(tmp_path) -> None:
    """A native-process failure keeps one marked workspace under the default policy."""

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

    retained = list(tmp_path.iterdir())
    assert len(retained) == 1
    marker = read_workspace_marker(retained[0])
    assert marker["state"] == "retained"
    assert marker["retention_class"] == "failed"
    assert marker["error_code"] == "MASCARET_PROCESS_FAILED"


def test_enabled_runtime_rejects_an_unreviewed_version(tmp_path) -> None:
    """Fail configuration before launch when upstream provenance drifts."""

    with pytest.raises(Hydraulic1DValidationError) as raised:
        MascaretRuntimeConfig.from_environment(
            {
                "MASCARET_ENABLED": "1",
                "MASCARET_EXECUTABLE_SHA256": "0" * 64,
                "MASCARET_BUILD_TIMESTAMP": "2026-09-01T00:00:00Z",
                "MASCARET_UPSTREAM_TAG": "v9.2.0",
                "HYDRAULIC_WORKSPACE_ROOT": str(tmp_path),
            }
        )

    assert raised.value.code == "MASCARET_VERSION_MISMATCH"


def test_external_runtime_reports_hash_mismatch(tmp_path) -> None:
    """Do not treat a present but unreviewed executable as available."""

    launcher = tmp_path / "mascaret.py"
    launcher.write_text("raise SystemExit(0)\n", encoding="utf-8")
    config = MascaretRuntimeConfig.from_environment(
        {
            "MASCARET_ENABLED": "1",
            "MASCARET_EXECUTABLE": str(launcher),
            "MASCARET_EXECUTABLE_SHA256": "0" * 64,
            "MASCARET_BUILD_TIMESTAMP": "2026-09-01T00:00:00Z",
            "HYDRAULIC_WORKSPACE_ROOT": str(tmp_path / "workspaces"),
        }
    )

    available, detail = create_mascaret_runtime(config).availability()

    assert available is False
    assert "SHA-256" in detail


def test_external_runtime_emits_timeout_and_missing_result_codes(tmp_path) -> None:
    """Keep timeout and successful-without-result failures machine actionable."""

    for name, source, timeout, expected_error, expected_code in (
        (
            "timeout",
            "import time\ntime.sleep(30)\n",
            "0.01",
            Hydraulic1DTimeout,
            "MASCARET_TIMEOUT",
        ),
        (
            "missing",
            "raise SystemExit(0)\n",
            "30",
            Hydraulic1DExecutionError,
            "MASCARET_RESULT_MISSING",
        ),
    ):
        root = tmp_path / name
        launcher = root / "mascaret.py"
        root.mkdir()
        launcher.write_text(source, encoding="utf-8")
        digest = sha256(launcher.read_bytes()).hexdigest()
        workspace = MascaretJobWorkspace.create(
            root / "workspaces",
            simulation_id=name,
            job_id=name,
        )
        case_file = workspace.path / "case.xcas"
        case_file.write_text("<fichierCas />\n", encoding="ascii")
        config = MascaretRuntimeConfig.from_environment(
            {
                "MASCARET_ENABLED": "1",
                "MASCARET_EXECUTABLE": str(launcher),
                "MASCARET_EXECUTABLE_SHA256": digest,
                "MASCARET_BUILD_TIMESTAMP": "2026-09-01T00:00:00Z",
                "MASCARET_TIMEOUT": timeout,
                "HYDRAULIC_WORKSPACE_ROOT": str(root / "workspaces"),
            }
        )
        with pytest.raises(expected_error) as raised:
            create_mascaret_runtime(config).execute(
                MascaretRuntimeRequest(
                    workspace=workspace.path,
                    case_file=case_file,
                    result_file=workspace.path / "results.opt",
                )
            )
        assert raised.value.code == expected_code


def test_failed_workspace_retention_is_bounded(tmp_path) -> None:
    """Prune only old verified diagnostic workspaces beyond the configured cap."""

    config = MascaretRuntimeConfig.from_environment(
        {
            "MASCARET_ENABLED": "0",
            "MASCARET_RETENTION_MAX_WORKSPACES": "2",
            "HYDRAULIC_WORKSPACE_ROOT": str(tmp_path),
        }
    )
    for index in range(3):
        with pytest.raises(Hydraulic1DExecutionError):
            MascaretEngine(config, runtime=_FixtureRuntime(fail=True)).run(
                model_fixture(),
                Hydraulic1DExecutionContext(job_id=f"failed-{index}"),
            )

    retained = list(tmp_path.iterdir())
    assert len(retained) == 2
    assert all(read_workspace_marker(path)["state"] == "retained" for path in retained)


@pytest.mark.mascaret_runtime
def test_two_real_jobs_use_independent_workspaces(tmp_path) -> None:
    """Execute two official-runtime jobs concurrently without native-file collision."""

    config = MascaretRuntimeConfig.from_environment()
    engine = MascaretEngine(config)
    available, reason = engine.availability()
    if not available:
        pytest.skip(f"{MASCARET_RUNTIME_SKIP_REASON}: {reason}")

    def execute(job_id: str):
        """Run one immutable model through an independently named attempt."""

        return engine.run(
            model_fixture(),
            Hydraulic1DExecutionContext(job_id=job_id, workspace_root=tmp_path),
        )

    with ThreadPoolExecutor(max_workers=2) as pool:
        left, right = tuple(pool.map(execute, ("concurrent-left", "concurrent-right")))

    assert left.records == right.records
    assert left.diagnostics["runtime_provenance"]["is_real"] is True
    assert right.diagnostics["runtime_provenance"]["version_verified"] is True
    assert len(list(tmp_path.iterdir())) == 2
