"""Shell-free DIMR process/container boundary for D-Flow FM plus D-RTC."""

from __future__ import annotations

import json
import os
import platform
import signal
import subprocess
from abc import ABC, abstractmethod
from collections.abc import Callable
from dataclasses import dataclass
from hashlib import sha256
from hmac import compare_digest
from pathlib import Path
from re import fullmatch
from shutil import which
from subprocess import DEVNULL, PIPE, Popen, TimeoutExpired, run
from time import monotonic, sleep
from typing import Any

from model.hydraulic_1d.dflow_fm.config import (
    DFLOW_RUNTIME_BLOCKED,
    DFLOW_UPSTREAM_COMMIT,
    DFLOW_UPSTREAM_REPOSITORY,
    DFLOW_UPSTREAM_TAG,
    DFlowRuntimeConfig,
)
from model.hydraulic_1d.dflow_fm.provenance import (
    DFlowProvenanceUnavailable,
    DFlowRuntimeProvenance,
    load_dflow_provenance,
)
from model.hydraulic_1d.dflow_fm.workspace import DFlowJobWorkspace
from model.hydraulic_1d.errors import (
    Hydraulic1DCancelled,
    Hydraulic1DExecutionError,
    Hydraulic1DRuntimeUnavailable,
)


CONTAINER_OWNER_LABEL = "io.dayu-tiangong.dflow.owner"
CONTAINER_PROVENANCE_LABEL = "io.dayu-tiangong.dflow.provenance-sha256"
CONTAINER_CID_FILENAME = "dflow-container.cid"

# Deployment input and provenance manifests are diagnostic evidence, not trust
# roots. These source-controlled acceptance sets can only be changed by review;
# they cannot be populated through environment variables or a runtime manifest.
_ACCEPTED_CLI_BINDING_MANIFESTS: frozenset[str] = frozenset()
_ACCEPTED_CONTAINER_IMAGE_DIGESTS: frozenset[str] = frozenset(
    {
        # DIMRset_2026.02, built from Deltares/Delft3D@5a464983 and verified
        # against the official D-Flow FM and DIMR/FBC examples. Detailed source,
        # build, component and reproducibility evidence lives in acceptance/.
        "sha256:e53a7c22cdce6a63f39357006ba73f2254ace24979c1f374ba111ee52d5b12b9",
    }
)


def _blocked(detail: str) -> str:
    """Expose the task's deterministic unavailable state in readiness messages."""

    return f"{DFLOW_RUNTIME_BLOCKED}: {detail}"


def _sha256_file(path: Path) -> str:
    """Fingerprint a reviewed executable without loading it wholly into memory."""

    digest = sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _resolved_executable(configured: str) -> Path | None:
    """Resolve a literal executable name/path without invoking a shell."""

    discovered = which(configured)
    candidate = Path(discovered or configured).expanduser()
    if not candidate.is_file() or candidate.is_symlink():
        return None
    return candidate.resolve()


def _reviewed_artifact(configured: Path | None) -> Path | None:
    """Resolve one explicitly configured regular file without following symlinks."""

    if configured is None or not configured.is_absolute():
        return None
    if configured.is_symlink() or not configured.is_file():
        return None
    return configured.resolve()


def _normalized_architecture(value: str) -> str:
    """Normalize common OCI/host spellings solely for identity comparison."""

    normalized = value.strip().lower()
    return {
        "amd64": "x86_64",
        "x64": "x86_64",
        "aarch64": "arm64",
    }.get(normalized, normalized)


def _terminate_process_tree(process: Popen[bytes]) -> None:
    """Terminate the complete Windows process tree or POSIX session group.

    The launcher is created in a fresh process group. Windows uses ``taskkill /T``
    against the still-live owned PID; POSIX addresses the fresh group and escalates
    from TERM to KILL only when its leader remains alive.
    """

    if process.poll() is not None:
        return
    if os.name == "nt":
        completed = run(
            ("taskkill", "/PID", str(process.pid), "/T", "/F"),
            stdin=DEVNULL,
            stdout=PIPE,
            stderr=PIPE,
            check=False,
            shell=False,
            timeout=10,
        )
        if completed.returncode != 0 and process.poll() is None:
            detail = completed.stderr.decode("utf-8", errors="replace")[-1000:]
            raise Hydraulic1DExecutionError(
                f"owned D-Flow process tree could not be terminated: {detail}",
                code="DFLOW_RUNTIME_RELEASE_FAILED",
            )
        try:
            process.wait(timeout=5)
        except TimeoutExpired as exc:
            raise Hydraulic1DExecutionError(
                "owned D-Flow process tree remained alive after taskkill",
                code="DFLOW_RUNTIME_RELEASE_FAILED",
            ) from exc
        return

    try:
        os.killpg(process.pid, signal.SIGTERM)
    except ProcessLookupError:
        return
    try:
        process.wait(timeout=5)
        return
    except TimeoutExpired:
        pass
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except ProcessLookupError:
        return
    try:
        process.wait(timeout=5)
    except TimeoutExpired as exc:
        raise Hydraulic1DExecutionError(
            "owned D-Flow process group resisted forced termination",
            code="DFLOW_RUNTIME_RELEASE_FAILED",
        ) from exc


@dataclass(frozen=True, slots=True)
class DFlowRuntimeRequest:
    """Name one validated workspace and the single DIMR coupling configuration."""

    workspace: DFlowJobWorkspace | Path
    dimr_config: Path


@dataclass(frozen=True, slots=True)
class DFlowRuntimeResult:
    """Capture one real DIMR launcher outcome and its complete reviewed identity."""

    command: tuple[str, ...]
    return_code: int
    elapsed_seconds: float
    stdout: str
    stderr: str
    provenance: dict[str, Any]


class DFlowRuntime(ABC):
    """Define the external runtime seam without registering an engine prematurely."""

    def __init__(self, config: DFlowRuntimeConfig) -> None:
        """Freeze deployment configuration for this runtime instance."""

        self.config = config

    @abstractmethod
    def availability(self) -> tuple[bool, str]:
        """Return a factual fail-closed readiness decision."""

    def verified_provenance(
        self,
    ) -> tuple[bool, str, dict[str, Any] | None]:
        """Return provenance only when the same readiness decision verified it."""

        available, detail = self.availability()
        return available, detail, None

    @abstractmethod
    def execute(
        self,
        request: DFlowRuntimeRequest,
        *,
        cancel_check: Callable[[], bool] | None = None,
    ) -> DFlowRuntimeResult:
        """Run the whole coupled model through DIMR with bounded supervision."""


class DisabledDFlowRuntime(DFlowRuntime):
    """Represent the safe default when no reviewed official runtime is installed."""

    def availability(self) -> tuple[bool, str]:
        """Never advertise numerical capability while the boundary is disabled."""

        return False, _blocked("D-Flow runtime is disabled by DFLOW_RUNTIME")

    def execute(
        self,
        request: DFlowRuntimeRequest,
        *,
        cancel_check: Callable[[], bool] | None = None,
    ) -> DFlowRuntimeResult:
        """Fail explicitly rather than emitting a substitute or synthetic result."""

        del request, cancel_check
        raise Hydraulic1DRuntimeUnavailable(
            "D-Flow runtime is disabled; no official numerical run was performed",
            code=DFLOW_RUNTIME_BLOCKED,
        )


class _ProcessDFlowRuntime(DFlowRuntime):
    """Share request validation and process-tree supervision across CLI/container."""

    runtime_kind: str

    def _provenance(self) -> DFlowRuntimeProvenance:
        """Load provenance afresh so replacement cannot be hidden by object caching."""

        return load_dflow_provenance(self.config.provenance_file)

    @abstractmethod
    def _readiness(
        self,
    ) -> tuple[bool, str, DFlowRuntimeProvenance | None]:
        """Verify one provenance object together with its concrete runtime artifacts."""

    def availability(self) -> tuple[bool, str]:
        """Return readiness without discarding the verification result internally."""

        available, detail, _ = self._readiness()
        return available, detail

    def verified_provenance(
        self,
    ) -> tuple[bool, str, dict[str, Any] | None]:
        """Expose only the exact manifest object verified by this readiness call."""

        available, detail, provenance = self._readiness()
        return (
            available,
            detail,
            provenance.as_metadata() if provenance is not None else None,
        )

    def _validated_request(
        self, request: DFlowRuntimeRequest
    ) -> tuple[DFlowJobWorkspace, Path]:
        """Prove the DIMR config is a plain file directly in this job's control area."""

        workspace = (
            request.workspace.validate()
            if isinstance(request.workspace, DFlowJobWorkspace)
            else DFlowJobWorkspace.open(request.workspace)
        )
        dimr_config = request.dimr_config
        if dimr_config.is_symlink() or not dimr_config.is_file():
            raise Hydraulic1DExecutionError(
                "DIMR configuration is absent or is a symlink",
                code="DFLOW_MODEL_BUILD_FAILED",
            )
        resolved_config = dimr_config.resolve()
        if resolved_config.parent != workspace.control_dir.resolve():
            raise Hydraulic1DExecutionError(
                "DIMR configuration must be directly inside the job control directory",
                code="DFLOW_WORKSPACE_INVALID",
            )
        return workspace, resolved_config

    @abstractmethod
    def _command(
        self,
        workspace: DFlowJobWorkspace,
        dimr_config: Path,
    ) -> tuple[str, ...]:
        """Build the literal shell-free argv for this deployment mode."""

    def build_command(self, request: DFlowRuntimeRequest) -> tuple[str, ...]:
        """Expose the validated argv for contract tests and deployment diagnostics."""

        workspace, dimr_config = self._validated_request(request)
        return self._command(workspace, dimr_config)

    def _after_forced_stop(self, workspace: DFlowJobWorkspace) -> None:
        """Release mode-specific detached resources after the launcher tree stops."""

        del workspace

    def execute(
        self,
        request: DFlowRuntimeRequest,
        *,
        cancel_check: Callable[[], bool] | None = None,
    ) -> DFlowRuntimeResult:
        """Run DIMR in one isolated job, enforcing cancellation and timeout."""

        available, reason, provenance = self._readiness()
        if not available or provenance is None:
            detail = reason.removeprefix(f"{DFLOW_RUNTIME_BLOCKED}: ")
            raise Hydraulic1DRuntimeUnavailable(detail, code=DFLOW_RUNTIME_BLOCKED)
        workspace, dimr_config = self._validated_request(request)
        command = self._command(workspace, dimr_config)
        stdout_path = workspace.resolve_in("logs", "dimr.stdout.log")
        stderr_path = workspace.resolve_in("logs", "dimr.stderr.log")
        started = monotonic()
        with (
            stdout_path.open("xb") as stdout_stream,
            stderr_path.open("xb") as stderr_stream,
        ):
            try:
                process: Popen[bytes] = Popen(
                    command,
                    cwd=workspace.path,
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
                raise Hydraulic1DRuntimeUnavailable(
                    f"DIMR launcher could not be started: {exc}",
                    code=DFLOW_RUNTIME_BLOCKED,
                ) from exc
            try:
                while process.poll() is None:
                    if cancel_check is not None and cancel_check():
                        raise Hydraulic1DCancelled(
                            "D-Flow/D-RTC execution cancelled",
                            code="DFLOW_CANCELLED",
                        )
                    if monotonic() - started > self.config.timeout_seconds:
                        raise Hydraulic1DExecutionError(
                            "D-Flow/D-RTC execution exceeded "
                            f"{self.config.timeout_seconds:g} seconds",
                            code="DFLOW_TIMEOUT",
                        )
                    sleep(0.05)
            except BaseException:
                if process.poll() is None:
                    _terminate_process_tree(process)
                    self._after_forced_stop(workspace)
                raise

        elapsed = monotonic() - started
        return_code = int(process.returncode or 0)
        stdout = stdout_path.read_text(encoding="utf-8", errors="replace")[-16000:]
        stderr = stderr_path.read_text(encoding="utf-8", errors="replace")[-16000:]
        if return_code != 0:
            raise Hydraulic1DExecutionError(
                f"DIMR exited with code {return_code}: {stderr[-2000:]}",
                code="DFLOW_PROCESS_FAILED",
            )
        return DFlowRuntimeResult(
            command=command,
            return_code=return_code,
            elapsed_seconds=elapsed,
            stdout=stdout,
            stderr=stderr,
            provenance=provenance.as_metadata(),
        )


class CliDFlowRuntime(_ProcessDFlowRuntime):
    """Launch the complete official coupling through one reviewed host DIMR binary."""

    runtime_kind = "cli"

    def _dimr(self) -> Path | None:
        """Resolve the configured DIMR executable without accepting a command string."""

        return _resolved_executable(self.config.dimr_executable)

    def _readiness(
        self,
    ) -> tuple[bool, str, DFlowRuntimeProvenance | None]:
        """Bind all four declared components to byte-for-byte reviewed artifacts."""

        try:
            provenance = self._provenance()
        except DFlowProvenanceUnavailable as exc:
            return False, str(exc), None
        executable = self._dimr()
        if executable is None:
            return (
                False,
                _blocked(
                    f"DIMR executable is unavailable: {self.config.dimr_executable}"
                ),
                None,
            )
        component_paths = {
            "dimr": executable,
            "dflowfm": _reviewed_artifact(self.config.dflowfm_artifact),
            "fbc": _reviewed_artifact(self.config.fbc_artifact),
            "hydrolib_core": _reviewed_artifact(self.config.hydrolib_core_artifact),
        }
        missing = [name for name, path in component_paths.items() if path is None]
        if missing:
            return (
                False,
                _blocked(
                    "reviewed CLI component artifact paths are unavailable: "
                    + ", ".join(missing)
                ),
                None,
            )
        observed_hashes: dict[str, str] = {}
        for name, path in component_paths.items():
            assert path is not None
            try:
                observed_hashes[name] = _sha256_file(path)
            except OSError as exc:
                return (
                    False,
                    _blocked(f"{name} artifact cannot be fingerprinted: {exc}"),
                    None,
                )
            component = getattr(provenance, name)
            if not compare_digest(observed_hashes[name], component.binary_sha256):
                return (
                    False,
                    _blocked(f"{name} artifact SHA-256 differs from provenance"),
                    None,
                )
        configured = self.config.dimr_executable_sha256
        if configured is not None and not compare_digest(
            observed_hashes["dimr"], configured
        ):
            return (
                False,
                _blocked("DIMR binary SHA-256 differs from configuration"),
                None,
            )
        actual_platform = platform.system().lower()
        actual_architecture = _normalized_architecture(platform.machine())
        for name in component_paths:
            component = getattr(provenance, name)
            if (
                component.platform != actual_platform
                or _normalized_architecture(component.architecture)
                != actual_architecture
            ):
                return (
                    False,
                    _blocked(f"{name} provenance platform/architecture mismatch"),
                    None,
                )
        manifest_sha256 = provenance.canonical_sha256()
        if manifest_sha256 not in _ACCEPTED_CLI_BINDING_MANIFESTS:
            return (
                False,
                _blocked(
                    "source-controlled CLI binding acceptance allowlist is empty; "
                    "DIMR-to-D-Flow/FBC load paths and the active HYDROLIB import "
                    "have not been independently bound to the reviewed artifacts"
                ),
                None,
            )
        return (
            True,
            (
                f"DIMR suite {DFLOW_UPSTREAM_TAG} verified at {DFLOW_UPSTREAM_COMMIT} "
                f"manifest-sha256:{manifest_sha256}"
            ),
            provenance,
        )

    def _command(
        self,
        workspace: DFlowJobWorkspace,
        dimr_config: Path,
    ) -> tuple[str, ...]:
        """Invoke only DIMR; DIMR owns all D-Flow FM/FBC coupling steps."""

        executable = self._dimr()
        if executable is None:
            raise Hydraulic1DRuntimeUnavailable(
                "DIMR executable disappeared before launch",
                code=DFLOW_RUNTIME_BLOCKED,
            )
        relative_config = dimr_config.relative_to(workspace.path).as_posix()
        return str(executable), relative_config


class ContainerDFlowRuntime(_ProcessDFlowRuntime):
    """Launch a digest-pinned reviewed suite in a network-disabled container."""

    runtime_kind = "container"

    def _docker(self) -> Path | None:
        """Resolve the Docker client without searching for an alternate runtime."""

        return _resolved_executable(self.config.docker_executable)

    def _inspect_image(self) -> dict[str, Any] | None:
        """Inspect only the already-local digest reference; never pull an image."""

        docker = self._docker()
        image = self.config.container_image
        if docker is None or image is None:
            return None
        try:
            completed = run(
                (str(docker), "image", "inspect", image),
                stdin=DEVNULL,
                stdout=PIPE,
                stderr=PIPE,
                check=False,
                shell=False,
                timeout=15,
            )
        except (OSError, TimeoutExpired):
            return None
        if completed.returncode != 0:
            return None
        try:
            payload = json.loads(completed.stdout.decode("utf-8", errors="strict"))
        except (UnicodeError, ValueError):
            return None
        if (
            not isinstance(payload, list)
            or len(payload) != 1
            or not isinstance(payload[0], dict)
        ):
            return None
        return payload[0]

    def _readiness(
        self,
    ) -> tuple[bool, str, DFlowRuntimeProvenance | None]:
        """Require local digest identity, OCI source labels, and full provenance."""

        try:
            provenance = self._provenance()
        except DFlowProvenanceUnavailable as exc:
            return False, str(exc), None
        image = self.config.container_image
        if image is None:
            return False, _blocked("DFLOW_CONTAINER_IMAGE is not configured"), None
        inspected = self._inspect_image()
        if inspected is None:
            return (
                False,
                _blocked("reviewed container image or Docker daemon is unavailable"),
                None,
            )
        digest = image.rsplit("@", 1)[-1].lower()
        repo_digests = inspected.get("RepoDigests")
        observed_id = str(inspected.get("Id", "")).lower()
        if observed_id != digest and not (
            isinstance(repo_digests, list)
            and any(str(item).lower().endswith("@" + digest) for item in repo_digests)
        ):
            return (
                False,
                _blocked("local container digest differs from configuration"),
                None,
            )
        image_config = inspected.get("Config")
        labels = image_config.get("Labels") if isinstance(image_config, dict) else None
        if not isinstance(labels, dict):
            return False, _blocked("container lacks reviewed OCI labels"), None
        expected_labels = {
            "org.opencontainers.image.source": DFLOW_UPSTREAM_REPOSITORY,
            "org.opencontainers.image.version": DFLOW_UPSTREAM_TAG,
            "org.opencontainers.image.revision": DFLOW_UPSTREAM_COMMIT,
            CONTAINER_PROVENANCE_LABEL: provenance.canonical_sha256(),
        }
        for key, expected in expected_labels.items():
            if labels.get(key) != expected:
                return (
                    False,
                    _blocked(f"container label {key} does not match provenance"),
                    None,
                )
        image_platform = str(inspected.get("Os", "")).lower()
        image_architecture = _normalized_architecture(
            str(inspected.get("Architecture", ""))
        )
        if (
            provenance.dimr.platform != image_platform
            or _normalized_architecture(provenance.dimr.architecture)
            != image_architecture
        ):
            return (
                False,
                _blocked("container platform/architecture differs from provenance"),
                None,
            )
        if digest not in _ACCEPTED_CONTAINER_IMAGE_DIGESTS:
            return (
                False,
                _blocked(
                    "container image digest is absent from the source-controlled "
                    "reviewed acceptance allowlist"
                ),
                None,
            )
        return True, f"reviewed D-Flow image verified at {digest}", provenance

    def _command(
        self,
        workspace: DFlowJobWorkspace,
        dimr_config: Path,
    ) -> tuple[str, ...]:
        """Mount only this job, disable networking, label ownership, and run DIMR."""

        docker = self._docker()
        image = self.config.container_image
        if docker is None or image is None:
            raise Hydraulic1DRuntimeUnavailable(
                "reviewed container runtime disappeared before launch",
                code=DFLOW_RUNTIME_BLOCKED,
            )
        cidfile = workspace.resolve_in("metadata", CONTAINER_CID_FILENAME)
        relative_config = dimr_config.relative_to(workspace.path).as_posix()
        return (
            str(docker),
            "run",
            "--pull",
            "never",
            "--rm",
            "--network",
            "none",
            "--read-only",
            "--cidfile",
            str(cidfile),
            "--label",
            f"{CONTAINER_OWNER_LABEL}={workspace.owner_token}",
            "--volume",
            f"{workspace.path}:/work",
            "--workdir",
            "/work",
            image,
            self.config.dimr_executable,
            relative_config,
        )

    def _after_forced_stop(self, workspace: DFlowJobWorkspace) -> None:
        """Remove only the cidfile container whose ownership label matches this job."""

        docker = self._docker()
        if docker is None:
            raise Hydraulic1DExecutionError(
                "Docker disappeared before owned container cleanup",
                code="DFLOW_RUNTIME_RELEASE_FAILED",
            )
        cidfile = workspace.resolve_in("metadata", CONTAINER_CID_FILENAME)
        if cidfile.is_symlink() or not cidfile.is_file():
            raise Hydraulic1DExecutionError(
                "owned D-Flow container cidfile is missing",
                code="DFLOW_RUNTIME_RELEASE_FAILED",
            )
        container_id = cidfile.read_text(encoding="ascii", errors="strict").strip()
        if fullmatch(r"[0-9a-fA-F]{12,64}", container_id) is None:
            raise Hydraulic1DExecutionError(
                "owned D-Flow container cidfile is invalid",
                code="DFLOW_RUNTIME_RELEASE_FAILED",
            )
        label_format = '{{ index .Config.Labels "' + CONTAINER_OWNER_LABEL + '" }}'
        inspected = run(
            (str(docker), "inspect", "--format", label_format, container_id),
            stdin=DEVNULL,
            stdout=PIPE,
            stderr=PIPE,
            check=False,
            shell=False,
            timeout=15,
        )
        observed_label = inspected.stdout.decode("utf-8", errors="replace").strip()
        if inspected.returncode != 0 or observed_label != workspace.owner_token:
            raise Hydraulic1DExecutionError(
                "container ownership label mismatch; no container was removed",
                code="DFLOW_RUNTIME_RELEASE_FAILED",
            )
        removed = run(
            (str(docker), "rm", "--force", container_id),
            stdin=DEVNULL,
            stdout=PIPE,
            stderr=PIPE,
            check=False,
            shell=False,
            timeout=30,
        )
        if removed.returncode != 0:
            raise Hydraulic1DExecutionError(
                "owned D-Flow container could not be removed",
                code="DFLOW_RUNTIME_RELEASE_FAILED",
            )


def create_dflow_runtime(config: DFlowRuntimeConfig) -> DFlowRuntime:
    """Select an explicit deployment boundary; never auto-discover another solver."""

    if config.runtime == "disabled":
        return DisabledDFlowRuntime(config)
    if config.runtime == "cli":
        return CliDFlowRuntime(config)
    return ContainerDFlowRuntime(config)


__all__ = [
    "CONTAINER_CID_FILENAME",
    "CONTAINER_OWNER_LABEL",
    "CONTAINER_PROVENANCE_LABEL",
    "CliDFlowRuntime",
    "ContainerDFlowRuntime",
    "DFlowRuntime",
    "DFlowRuntimeRequest",
    "DFlowRuntimeResult",
    "DisabledDFlowRuntime",
    "create_dflow_runtime",
]
