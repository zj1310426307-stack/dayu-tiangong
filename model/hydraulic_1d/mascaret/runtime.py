"""Bounded independent-process runtimes for an externally installed MASCARET."""

from __future__ import annotations

import os
import signal
import subprocess
from abc import ABC, abstractmethod
from collections.abc import Callable
from dataclasses import dataclass
from hashlib import sha256
from hmac import compare_digest
from pathlib import Path
from shutil import which
from subprocess import DEVNULL, Popen, TimeoutExpired
from sys import executable as python_executable
from time import monotonic, sleep

from model.hydraulic_1d.errors import (
    Hydraulic1DCancelled,
    Hydraulic1DExecutionError,
    Hydraulic1DRuntimeUnavailable,
)
from model.hydraulic_1d.mascaret.config import MascaretRuntimeConfig
from model.hydraulic_1d.mascaret.runtime_recovery import (
    CONTAINER_LABEL_KEY,
    PROCESS_IDENTITY_ENV,
    RuntimeProcessGuard,
    attach_runtime_process,
    container_attempt_label,
    mark_runtime_exited,
    mark_runtime_launching,
    mark_runtime_released,
    remove_owned_container,
)
from model.hydraulic_1d.mascaret.workspace import read_workspace_marker


@dataclass(frozen=True, slots=True)
class MascaretRuntimeRequest:
    """Identify the prepared case and expected result inside one job workspace."""

    workspace: Path
    case_file: Path
    result_file: Path


@dataclass(frozen=True, slots=True)
class MascaretRuntimeResult:
    """Capture a real process outcome without treating missing output as success."""

    command: tuple[str, ...]
    return_code: int
    elapsed_seconds: float
    stdout: str
    stderr: str
    result_file: Path


class MascaretRuntime(ABC):
    """Define the process/container seam used by the MASCARET engine adapter."""

    @abstractmethod
    def availability(self) -> tuple[bool, str]:
        """Return a factual availability decision and a human-readable reason."""

    @abstractmethod
    def execute(
        self,
        request: MascaretRuntimeRequest,
        *,
        cancel_check: Callable[[], bool] | None = None,
    ) -> MascaretRuntimeResult:
        """Run a prepared case without a shell and enforce timeout/cancellation."""


class _ProcessMascaretRuntime(MascaretRuntime):
    """Share secure process supervision between CLI and container variants."""

    runtime_kind: str

    def __init__(self, config: MascaretRuntimeConfig) -> None:
        """Freeze runtime configuration for the lifetime of one engine instance."""

        self.config = config

    @abstractmethod
    def _command(
        self,
        request: MascaretRuntimeRequest,
        *,
        container_label: str | None,
    ) -> tuple[str, ...]:
        """Build a shell-free command for the selected execution boundary."""

    def execute(
        self,
        request: MascaretRuntimeRequest,
        *,
        cancel_check: Callable[[], bool] | None = None,
    ) -> MascaretRuntimeResult:
        """Supervise one process and require a non-empty expected result file."""

        available, reason = self.availability()
        if not available:
            raise Hydraulic1DRuntimeUnavailable(reason)
        workspace = request.workspace.resolve()
        if not workspace.is_dir():
            raise Hydraulic1DExecutionError("job workspace does not exist")
        for label, path in (
            ("case file", request.case_file),
            ("result file", request.result_file),
        ):
            if path.resolve().parent != workspace:
                raise Hydraulic1DExecutionError(f"{label} is outside the job workspace")
        if not request.case_file.is_file():
            raise Hydraulic1DExecutionError("MASCARET case file does not exist")
        if request.result_file.exists():
            request.result_file.unlink()
        marker = read_workspace_marker(workspace)
        container_label = (
            container_attempt_label(str(marker["job_id"]))
            if self.runtime_kind == "container"
            else None
        )
        command = self._command(request, container_label=container_label)
        stdout_path = request.workspace / "mascaret.stdout.log"
        stderr_path = request.workspace / "mascaret.stderr.log"
        started = monotonic()
        with stdout_path.open("wb") as stdout_stream, stderr_path.open("wb") as stderr_stream:
            process_identity = mark_runtime_launching(
                workspace,
                runtime_kind=self.runtime_kind,
                command=command,
                container_label=container_label,
            )
            process_environment = dict(os.environ)
            process_environment[PROCESS_IDENTITY_ENV] = process_identity
            try:
                process = Popen(
                    command,
                    cwd=request.workspace,
                    env=process_environment,
                    stdin=DEVNULL,
                    stdout=stdout_stream,
                    stderr=stderr_stream,
                    shell=False,
                    start_new_session=os.name != "nt",
                    creationflags=(
                        subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0
                    ),
                )
            except OSError:
                # Popen reports exec/create failures only after it has reaped any
                # partially created direct child, so no external identity exists.
                mark_runtime_released(workspace)
                raise
            guard: RuntimeProcessGuard | None = None
            try:
                guard = attach_runtime_process(
                    workspace,
                    process,
                    runtime_kind=self.runtime_kind,
                    command=command,
                )
                while process.poll() is None:
                    if cancel_check is not None and cancel_check():
                        raise Hydraulic1DCancelled("MASCARET execution cancelled")
                    if monotonic() - started > self.config.timeout_seconds:
                        raise Hydraulic1DExecutionError(
                            "MASCARET execution exceeded "
                            f"{self.config.timeout_seconds:g} seconds"
                        )
                    sleep(0.1)
            finally:
                if guard is None:
                    self._stop_unattached_process(process)
                else:
                    self._release_runtime(
                        process,
                        guard,
                        request,
                        container_label=container_label,
                    )
        elapsed = monotonic() - started
        stdout = stdout_path.read_text(encoding="utf-8", errors="replace")[-16000:]
        stderr = stderr_path.read_text(encoding="utf-8", errors="replace")[-16000:]
        return_code = int(process.returncode or 0)
        if return_code != 0:
            raise Hydraulic1DExecutionError(
                f"MASCARET exited with code {return_code}: {stderr[-2000:]}"
            )
        if not request.result_file.is_file() or request.result_file.stat().st_size == 0:
            raise Hydraulic1DExecutionError(
                "MASCARET returned success without the expected non-empty .opt result"
            )
        return MascaretRuntimeResult(
            command=command,
            return_code=return_code,
            elapsed_seconds=elapsed,
            stdout=stdout,
            stderr=stderr,
            result_file=request.result_file,
        )

    def _stop_unattached_process(
        self,
        process: Popen[bytes],
    ) -> None:
        """Stop the exact live Popen after identity attachment failed.

        The workspace deliberately remains in ``launching`` state because this
        fallback cannot prove on Windows that no child escaped before assignment.
        """

        if process.poll() is not None:
            return
        if os.name == "nt":
            process.kill()
        else:
            try:
                os.killpg(process.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
        try:
            process.wait(timeout=5)
        except TimeoutExpired:
            if os.name == "nt":
                process.kill()
            else:
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
            try:
                process.wait(timeout=5)
            except TimeoutExpired as exc:
                raise Hydraulic1DExecutionError(
                    "MASCARET process group did not stop after forced termination"
                ) from exc

    def _release_runtime(
        self,
        process: Popen[bytes],
        guard: RuntimeProcessGuard,
        request: MascaretRuntimeRequest,
        *,
        container_label: str | None,
    ) -> None:
        """Prove the process boundary and detached runtime are gone before cleanup."""

        failures: list[Exception] = []
        try:
            guard.terminate()
        except Exception as exc:
            failures.append(exc)
        launcher_exited = process.poll() is not None
        if launcher_exited:
            try:
                mark_runtime_exited(request.workspace, return_code=process.returncode)
            except Exception as exc:
                failures.append(exc)
        if self.runtime_kind == "container":
            try:
                assert container_label is not None
                remove_owned_container(
                    request.workspace,
                    expected_label=container_label,
                    process_exited=launcher_exited,
                )
            except Exception as exc:
                failures.append(exc)
        if not failures and launcher_exited:
            try:
                mark_runtime_released(request.workspace)
            except Exception as exc:
                failures.append(exc)
        guard.close()
        if failures:
            raise Hydraulic1DExecutionError(
                "MASCARET runtime release could not be confirmed: " + str(failures[0])
            ) from failures[0]
        if not launcher_exited:
            raise Hydraulic1DExecutionError("MASCARET launcher remained alive after termination")


class CliMascaretRuntime(_ProcessMascaretRuntime):
    """Run the official TELEMAC MASCARET launcher already installed on the host."""

    runtime_kind = "cli"

    def availability(self) -> tuple[bool, str]:
        """Require explicit enablement and a resolvable executable."""

        if not self.config.enabled:
            return False, "MASCARET runtime is disabled by MASCARET_ENABLED"
        executable = self.config.executable
        resolved = which(executable)
        if resolved is None and not Path(executable).is_file():
            return False, f"MASCARET executable is unavailable: {executable}"
        executable_path = Path(resolved or executable).resolve()
        digest = sha256()
        try:
            with executable_path.open("rb") as stream:
                for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                    digest.update(chunk)
        except OSError as exc:
            return False, f"MASCARET executable cannot be fingerprinted: {exc}"
        observed = digest.hexdigest()
        expected = self.config.executable_sha256
        if expected is None or not compare_digest(observed, expected):
            return False, "MASCARET executable SHA-256 does not match the reviewed runtime"
        return True, f"MASCARET CLI verified sha256:{observed}"

    def _command(
        self,
        request: MascaretRuntimeRequest,
        *,
        container_label: str | None,
    ) -> tuple[str, ...]:
        """Invoke the official Python launcher with the case basename."""

        assert container_label is None
        executable = which(self.config.executable) or str(Path(self.config.executable).resolve())
        if Path(executable).suffix.lower() == ".py":
            return python_executable, executable, request.case_file.name
        return executable, request.case_file.name


class ContainerMascaretRuntime(_ProcessMascaretRuntime):
    """Run a user-reviewed MASCARET image with a single isolated writable mount."""

    runtime_kind = "container"

    def availability(self) -> tuple[bool, str]:
        """Require Docker, explicit enablement, and an explicitly configured image."""

        if not self.config.enabled:
            return False, "MASCARET runtime is disabled by MASCARET_ENABLED"
        if which("docker") is None:
            return False, "Docker executable is unavailable"
        if not self.config.container_image:
            return False, "MASCARET_CONTAINER_IMAGE is not configured"
        return True, f"MASCARET container verified {self.config.container_image}"

    def _command(
        self,
        request: MascaretRuntimeRequest,
        *,
        container_label: str | None,
    ) -> tuple[str, ...]:
        """Disable networking and mount only the current job at `/work`."""

        assert self.config.container_image is not None
        assert container_label is not None
        command = (
            "docker",
            "run",
            "--rm",
            "--network",
            "none",
            "--cidfile",
            str((request.workspace / ".mascaret-container.cid").resolve()),
            "--label",
            f"{CONTAINER_LABEL_KEY}={container_label}",
            "--volume",
            f"{request.workspace.resolve()}:/work",
            "--workdir",
            "/work",
            self.config.container_image,
        )
        launcher = (
            ("python3", self.config.executable)
            if Path(self.config.executable).suffix.lower() == ".py"
            else (self.config.executable,)
        )
        return (*command, *launcher, request.case_file.name)

def create_mascaret_runtime(config: MascaretRuntimeConfig) -> MascaretRuntime:
    """Select the configured runtime without leaking that decision into services."""

    if config.runtime == "cli":
        return CliMascaretRuntime(config)
    return ContainerMascaretRuntime(config)
