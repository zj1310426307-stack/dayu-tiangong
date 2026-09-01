"""Bounded independent-process runtimes for an externally installed MASCARET."""

from __future__ import annotations

import os
import platform
import json
import signal
import subprocess
from abc import ABC, abstractmethod
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from hashlib import sha256
from hmac import compare_digest
from pathlib import Path
from shutil import copy2, which
from subprocess import DEVNULL, Popen, TimeoutExpired
from sys import executable as python_executable
from time import monotonic, sleep

from model.hydraulic_1d.errors import (
    Hydraulic1DCancelled,
    Hydraulic1DExecutionError,
    Hydraulic1DRuntimeUnavailable,
    Hydraulic1DTimeout,
)
from model.hydraulic_1d.mascaret.config import (
    MASCARET_ENGINE_ID,
    MASCARET_SOURCE_ARCHIVE_SHA256,
    MASCARET_SOURCE_TREE_SHA256,
    MASCARET_VERSION,
    MascaretRuntimeConfig,
)
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
class MascaretRuntimeIdentity:
    """Describe the exact official runtime that produced one hydraulic result."""

    engine_name: str
    engine_version: str
    upstream_tag: str
    upstream_commit: str
    source_archive_sha256: str
    source_tree_sha256: str
    runtime_mode: str
    executable: str | None
    executable_hash: str | None
    container_image: str | None
    container_digest: str | None
    build_timestamp: str | None
    platform: str
    architecture: str
    is_real: bool
    version_verified: bool
    resource_digest: str | None = None

    def as_metadata(self) -> dict[str, object]:
        """Return JSON-safe simulation metadata with stable field names."""

        return asdict(self)


@dataclass(frozen=True, slots=True)
class MascaretRuntimeResult:
    """Capture a real process outcome without treating missing output as success."""

    command: tuple[str, ...]
    return_code: int
    elapsed_seconds: float
    stdout: str
    stderr: str
    result_file: Path
    runtime_identity: dict[str, object] = field(default_factory=dict)


class MascaretRuntime(ABC):
    """Define the process/container seam used by the MASCARET engine adapter."""

    @abstractmethod
    def availability(self) -> tuple[bool, str]:
        """Return a factual availability decision and a human-readable reason."""

    def identity(self) -> MascaretRuntimeIdentity:
        """Return an explicitly unverified identity for non-production test seams."""

        return MascaretRuntimeIdentity(
            engine_name=MASCARET_ENGINE_ID,
            engine_version=MASCARET_VERSION,
            upstream_tag="unknown",
            upstream_commit="unknown",
            source_archive_sha256="unknown",
            source_tree_sha256="unknown",
            runtime_mode="test-seam",
            executable=None,
            executable_hash=None,
            container_image=None,
            container_digest=None,
            build_timestamp=None,
            platform=platform.system().lower(),
            architecture=platform.machine().lower(),
            is_real=False,
            version_verified=False,
        )

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

    def _prepare_workspace(self, request: MascaretRuntimeRequest) -> None:
        """Materialize runtime-owned support files before launching the solver."""

        del request

    def execute(
        self,
        request: MascaretRuntimeRequest,
        *,
        cancel_check: Callable[[], bool] | None = None,
    ) -> MascaretRuntimeResult:
        """Supervise one process and require a non-empty expected result file."""

        available, reason = self.availability()
        if not available:
            code = (
                "MASCARET_VERSION_MISMATCH"
                if "version" in reason.lower() or "revision" in reason.lower()
                else "MASCARET_RUNTIME_IDENTITY_UNKNOWN"
            )
            raise Hydraulic1DRuntimeUnavailable(reason, code=code)
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
            raise Hydraulic1DExecutionError(
                "MASCARET case file does not exist",
                code="MASCARET_MODEL_BUILD_FAILED",
            )
        self._prepare_workspace(request)
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
        with (
            stdout_path.open("wb") as stdout_stream,
            stderr_path.open("wb") as stderr_stream,
        ):
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
            except OSError as exc:
                # Popen reports exec/create failures only after it has reaped any
                # partially created direct child, so no external identity exists.
                mark_runtime_released(workspace)
                raise Hydraulic1DExecutionError(
                    f"MASCARET process could not be started: {exc}",
                    code="MASCARET_RUNTIME_NOT_FOUND",
                ) from exc
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
                        raise Hydraulic1DTimeout(
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
                "MASCARET returned success without the expected non-empty .opt result",
                code="MASCARET_RESULT_MISSING",
            )
        identity = self.identity()
        if not identity.is_real or not identity.version_verified:
            raise Hydraulic1DRuntimeUnavailable(
                "runtime identity was not verified after execution",
                code="MASCARET_RUNTIME_IDENTITY_UNKNOWN",
            )
        return MascaretRuntimeResult(
            command=command,
            return_code=return_code,
            elapsed_seconds=elapsed,
            stdout=stdout,
            stderr=stderr,
            result_file=request.result_file,
            runtime_identity=identity.as_metadata(),
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
            raise Hydraulic1DExecutionError(
                "MASCARET launcher remained alive after termination"
            )


class CliMascaretRuntime(_ProcessMascaretRuntime):
    """Run the official TELEMAC MASCARET launcher already installed on the host."""

    runtime_kind = "external"

    def _resolved_executable(self) -> Path | None:
        """Resolve the configured executable without accepting a shell command."""

        resolved = which(self.config.executable)
        candidate = Path(resolved or self.config.executable)
        return candidate.resolve() if candidate.is_file() else None

    def _executable_digest(self, executable_path: Path) -> str:
        """Fingerprint the complete reviewed launcher or native executable."""

        digest = sha256()
        with executable_path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()

    def _resource_digest(self) -> str | None:
        """Fingerprint official runtime data copied beside a native executable."""

        data_dir = self.config.data_directory
        if data_dir is None:
            return None
        digest = sha256()
        for name in (
            "Abaques.txt",
            "Controle.txt",
            "dico_Courlis.txt",
            "mascaret-1.0.dtd",
        ):
            path = data_dir / name
            if not path.is_file():
                return None
            digest.update(name.encode("ascii"))
            digest.update(path.read_bytes())
        return digest.hexdigest()

    def availability(self) -> tuple[bool, str]:
        """Require explicit enablement and a resolvable executable."""

        if not self.config.enabled:
            return False, "MASCARET runtime is disabled by MASCARET_ENABLED"
        executable_path = self._resolved_executable()
        if executable_path is None:
            return (
                False,
                f"MASCARET executable is unavailable: {self.config.executable}",
            )
        try:
            observed = self._executable_digest(executable_path)
        except OSError as exc:
            return False, f"MASCARET executable cannot be fingerprinted: {exc}"
        expected = self.config.executable_sha256
        if expected is None or not compare_digest(observed, expected):
            return (
                False,
                "MASCARET executable SHA-256 does not match the reviewed runtime",
            )
        if executable_path.suffix.lower() != ".py":
            data_dir = self.config.data_directory
            if data_dir is None or not data_dir.is_dir():
                return False, "MASCARET_DATA_DIR is required for the native executable"
            if self._resource_digest() is None:
                return False, "MASCARET official runtime data files are incomplete"
        if self.config.build_timestamp is None:
            return False, "MASCARET build timestamp provenance is unavailable"
        return True, (
            f"MASCARET external {self.config.upstream_tag} verified "
            f"commit:{self.config.upstream_commit} sha256:{observed}"
        )

    def identity(self) -> MascaretRuntimeIdentity:
        """Return the verified external binary and official-source provenance."""

        executable_path = self._resolved_executable()
        if executable_path is None:
            return super().identity()
        try:
            observed = self._executable_digest(executable_path)
        except OSError:
            return super().identity()
        verified = (
            self.config.executable_sha256 is not None
            and compare_digest(observed, self.config.executable_sha256)
            and self.config.build_timestamp is not None
        )
        return MascaretRuntimeIdentity(
            engine_name=MASCARET_ENGINE_ID,
            engine_version=MASCARET_VERSION,
            upstream_tag=self.config.upstream_tag,
            upstream_commit=self.config.upstream_commit,
            source_archive_sha256=MASCARET_SOURCE_ARCHIVE_SHA256,
            source_tree_sha256=MASCARET_SOURCE_TREE_SHA256,
            runtime_mode="external",
            # Public provenance identifies the reviewed binary by basename and
            # digest without leaking a worker host path through result APIs.
            executable=executable_path.name,
            executable_hash=observed,
            container_image=None,
            container_digest=None,
            build_timestamp=self.config.build_timestamp,
            platform=platform.system().lower(),
            architecture=platform.machine().lower(),
            is_real=True,
            version_verified=verified,
            resource_digest=self._resource_digest(),
        )

    def _prepare_workspace(self, request: MascaretRuntimeRequest) -> None:
        """Copy the official data files required by the native Fortran executable."""

        executable = self._resolved_executable()
        if executable is None or executable.suffix.lower() == ".py":
            return
        assert self.config.data_directory is not None
        for name in (
            "Abaques.txt",
            "Controle.txt",
            "dico_Courlis.txt",
            "mascaret-1.0.dtd",
        ):
            copy2(self.config.data_directory / name, request.workspace / name)

    def _command(
        self,
        request: MascaretRuntimeRequest,
        *,
        container_label: str | None,
    ) -> tuple[str, ...]:
        """Invoke the official Python launcher with the case basename."""

        assert container_label is None
        executable = which(self.config.executable) or str(
            Path(self.config.executable).resolve()
        )
        if Path(executable).suffix.lower() == ".py":
            return python_executable, executable, request.case_file.name
        # The native official binary reads FichierCas.txt from cwd; it does not
        # consume a steering-file positional argument.
        return (executable,)


class ContainerMascaretRuntime(_ProcessMascaretRuntime):
    """Run a user-reviewed MASCARET image with a single isolated writable mount."""

    runtime_kind = "container"

    def _inspect_image(self) -> dict[str, object] | None:
        """Read local immutable image metadata without contacting a registry."""

        image = self.config.container_image
        if image is None or which("docker") is None:
            return None
        try:
            completed = subprocess.run(
                ("docker", "image", "inspect", image),
                check=False,
                capture_output=True,
                text=True,
                timeout=15,
                shell=False,
            )
        except (OSError, TimeoutExpired):
            return None
        if completed.returncode != 0:
            return None
        try:
            payload = json.loads(completed.stdout)
        except ValueError:
            return None
        if (
            not isinstance(payload, list)
            or len(payload) != 1
            or not isinstance(payload[0], dict)
        ):
            return None
        return payload[0]

    def availability(self) -> tuple[bool, str]:
        """Require Docker, explicit enablement, and an explicitly configured image."""

        if not self.config.enabled:
            return False, "MASCARET runtime is disabled by MASCARET_ENABLED"
        if which("docker") is None:
            return False, "Docker executable is unavailable"
        if not self.config.container_image:
            return False, "MASCARET_CONTAINER_IMAGE is not configured"
        inspected = self._inspect_image()
        if inspected is None:
            return False, "MASCARET container image or Docker daemon is unavailable"
        configured_digest = self.config.container_image.rsplit("@", 1)[-1]
        observed_id = str(inspected.get("Id", "")).lower()
        repo_digests = inspected.get("RepoDigests", [])
        digest_verified = observed_id == configured_digest.lower() or (
            isinstance(repo_digests, list)
            and any(
                str(item).lower().endswith("@" + configured_digest.lower())
                for item in repo_digests
            )
        )
        if not digest_verified:
            return False, "MASCARET container digest does not match the local image"
        config = inspected.get("Config")
        labels = config.get("Labels", {}) if isinstance(config, dict) else {}
        if not isinstance(labels, dict):
            labels = {}
        if labels.get("org.opencontainers.image.version") != self.config.upstream_tag:
            return (
                False,
                "MASCARET container version label does not match the reviewed tag",
            )
        if (
            labels.get("org.opencontainers.image.revision")
            != self.config.upstream_commit
        ):
            return (
                False,
                "MASCARET container revision label does not match the reviewed commit",
            )
        if not labels.get("org.opencontainers.image.created"):
            return False, "MASCARET container build timestamp label is unavailable"
        return True, (
            f"MASCARET container {self.config.upstream_tag} verified "
            f"commit:{self.config.upstream_commit} digest:{configured_digest}"
        )

    def identity(self) -> MascaretRuntimeIdentity:
        """Return digest- and OCI-label-verified container provenance."""

        inspected = self._inspect_image()
        if inspected is None or self.config.container_image is None:
            return super().identity()
        config = inspected.get("Config")
        labels = config.get("Labels", {}) if isinstance(config, dict) else {}
        if not isinstance(labels, dict):
            labels = {}
        digest = self.config.container_image.rsplit("@", 1)[-1]
        return MascaretRuntimeIdentity(
            engine_name=MASCARET_ENGINE_ID,
            engine_version=MASCARET_VERSION,
            upstream_tag=self.config.upstream_tag,
            upstream_commit=self.config.upstream_commit,
            source_archive_sha256=MASCARET_SOURCE_ARCHIVE_SHA256,
            source_tree_sha256=MASCARET_SOURCE_TREE_SHA256,
            runtime_mode="container",
            # Do not expose image-internal paths through readiness/result APIs.
            executable=Path(self.config.executable).name,
            executable_hash=None,
            container_image=self.config.container_image,
            container_digest=digest,
            build_timestamp=str(labels.get("org.opencontainers.image.created") or "")
            or None,
            platform=str(inspected.get("Os", "linux")).lower(),
            architecture=str(inspected.get("Architecture", "unknown")).lower(),
            is_real=True,
            version_verified=(
                labels.get("org.opencontainers.image.version")
                == self.config.upstream_tag
                and labels.get("org.opencontainers.image.revision")
                == self.config.upstream_commit
            ),
        )

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

    if config.runtime == "external":
        return CliMascaretRuntime(config)
    return ContainerMascaretRuntime(config)
