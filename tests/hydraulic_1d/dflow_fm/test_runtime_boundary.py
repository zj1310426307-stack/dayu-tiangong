"""Contract tests for the fail-closed DIMR CLI/container execution boundary."""

from __future__ import annotations

import json
import platform
from hashlib import sha256
from pathlib import Path

import pytest

from model.hydraulic_1d.dflow_fm import runtime as runtime_module
from model.hydraulic_1d.dflow_fm.config import (
    DFLOW_NATIVE_VERSION,
    DIMR_NATIVE_VERSION,
    DFLOW_RUNTIME_BLOCKED,
    DFLOW_UPSTREAM_COMMIT,
    DFLOW_UPSTREAM_TAG,
    FBC_NATIVE_VERSION,
    HYDROLIB_CORE_UPSTREAM_COMMIT,
    DFlowRuntimeConfig,
)
from model.hydraulic_1d.dflow_fm.provenance import (
    PROVENANCE_SCHEMA,
    load_dflow_provenance,
)
from model.hydraulic_1d.dflow_fm.runtime import (
    CONTAINER_OWNER_LABEL,
    CliDFlowRuntime,
    ContainerDFlowRuntime,
    DFlowRuntimeRequest,
    DisabledDFlowRuntime,
    create_dflow_runtime,
)
from model.hydraulic_1d.dflow_fm.workspace import DFlowJobWorkspace
from model.hydraulic_1d.errors import (
    Hydraulic1DRuntimeUnavailable,
    Hydraulic1DValidationError,
)


def _component(
    *,
    binary_sha256: str,
    version: str = "2026.02",
    tag: str = DFLOW_UPSTREAM_TAG,
    commit: str = DFLOW_UPSTREAM_COMMIT,
) -> dict[str, str]:
    """Build one complete deterministic provenance component for unit tests."""

    return {
        "version": version,
        "upstream_tag": tag,
        "upstream_commit": commit,
        "binary_sha256": binary_sha256,
        "source_manifest": "a" * 64,
        "platform": platform.system().lower(),
        "architecture": platform.machine().lower(),
        "build_timestamp": "2026-09-02T00:00:00Z",
    }


def _write_provenance(path: Path, *, dimr_sha256: str) -> Path:
    """Write a complete four-component manifest at the selected official revision."""

    component_paths = {
        "dflowfm": path.parent / "dflowfm.reviewed",
        "fbc": path.parent / "fbc.reviewed",
        "hydrolib_core": path.parent / "hydrolib-core-1.0.1.whl",
    }
    for name, component_path in component_paths.items():
        component_path.write_bytes(f"reviewed {name}".encode("ascii"))
    payload = {
        "schema_version": PROVENANCE_SCHEMA,
        "dflowfm": _component(
            binary_sha256=sha256(component_paths["dflowfm"].read_bytes()).hexdigest(),
            version=DFLOW_NATIVE_VERSION,
        ),
        "dimr": _component(binary_sha256=dimr_sha256, version=DIMR_NATIVE_VERSION),
        "fbc": _component(
            binary_sha256=sha256(component_paths["fbc"].read_bytes()).hexdigest(),
            version=FBC_NATIVE_VERSION,
        ),
        "hydrolib_core": _component(
            binary_sha256=sha256(
                component_paths["hydrolib_core"].read_bytes()
            ).hexdigest(),
            version="1.0.1",
            tag="1.0.1",
            commit=HYDROLIB_CORE_UPSTREAM_COMMIT,
        ),
    }
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def _workspace(tmp_path: Path) -> tuple[DFlowJobWorkspace, Path]:
    """Create one valid job and its top-level DIMR coupling configuration."""

    workspace = DFlowJobWorkspace.create(
        tmp_path / "runtime",
        simulation_id="simulation",
        job_id="job",
    )
    dimr_config = workspace.resolve_in("control", "dimr_config.xml")
    dimr_config.write_text("<dimrConfig />\n", encoding="utf-8")
    return workspace, dimr_config


def _cli_config(
    tmp_path: Path, executable: Path, provenance: Path
) -> DFlowRuntimeConfig:
    """Build an enabled CLI configuration with no process invocation."""

    return DFlowRuntimeConfig.from_environment(
        {
            "DFLOW_RUNTIME": "cli",
            "DFLOW_DIMR_EXECUTABLE": str(executable),
            "DFLOW_PROVENANCE_FILE": str(provenance),
            "DFLOW_WORKSPACE_ROOT": str(tmp_path / "runtime"),
            "DFLOW_DFLOWFM_ARTIFACT": str((tmp_path / "dflowfm.reviewed").resolve()),
            "DFLOW_FBC_ARTIFACT": str((tmp_path / "fbc.reviewed").resolve()),
            "DFLOW_HYDROLIB_CORE_ARTIFACT": str(
                (tmp_path / "hydrolib-core-1.0.1.whl").resolve()
            ),
        }
    )


def test_default_runtime_is_disabled_and_reports_blocked() -> None:
    """A fresh deployment cannot advertise or fake an official D-Flow result."""

    runtime = create_dflow_runtime(DFlowRuntimeConfig.from_environment({}))

    assert isinstance(runtime, DisabledDFlowRuntime)
    assert runtime.availability() == (
        False,
        f"{DFLOW_RUNTIME_BLOCKED}: D-Flow runtime is disabled by DFLOW_RUNTIME",
    )
    with pytest.raises(Hydraulic1DRuntimeUnavailable) as raised:
        runtime.execute(
            DFlowRuntimeRequest(
                workspace=Path("unused"), dimr_config=Path("unused.xml")
            )
        )
    assert raised.value.code == DFLOW_RUNTIME_BLOCKED


def test_configuration_pins_release_and_requires_digest_image(tmp_path: Path) -> None:
    """Reject latest/tag-only images and any drift from the audited suite revision."""

    with pytest.raises(Hydraulic1DValidationError, match="non-latest"):
        DFlowRuntimeConfig.from_environment(
            {
                "DFLOW_RUNTIME": "container",
                "DFLOW_CONTAINER_IMAGE": "deltares/dflow:latest",
            }
        )
    with pytest.raises(Hydraulic1DValidationError) as raised:
        DFlowRuntimeConfig.from_environment(
            {
                "DFLOW_RUNTIME": "disabled",
                "DFLOW_UPSTREAM_COMMIT": "0" * 40,
                "DFLOW_WORKSPACE_ROOT": str(tmp_path),
            }
        )
    assert raised.value.code == "DFLOW_VERSION_MISMATCH"


def test_missing_component_provenance_is_runtime_blocked(tmp_path: Path) -> None:
    """Presence of DIMR alone is insufficient when any required identity is missing."""

    dimr = tmp_path / "dimr"
    dimr.write_bytes(b"reviewed dimr")
    provenance = tmp_path / "provenance.json"
    provenance.write_text(
        json.dumps(
            {
                "schema_version": PROVENANCE_SCHEMA,
                "dflowfm": _component(binary_sha256="b" * 64),
                "dimr": _component(binary_sha256=sha256(dimr.read_bytes()).hexdigest()),
                "fbc": _component(binary_sha256="c" * 64),
            }
        ),
        encoding="utf-8",
    )

    available, reason = CliDFlowRuntime(
        _cli_config(tmp_path, dimr, provenance)
    ).availability()

    assert available is False
    assert reason.startswith(DFLOW_RUNTIME_BLOCKED)
    assert "hydrolib_core" in reason


def test_runtime_provenance_rejects_native_component_version_drift(
    tmp_path: Path,
) -> None:
    dimr = tmp_path / "dimr"
    dimr.write_bytes(b"reviewed dimr")
    provenance = _write_provenance(
        tmp_path / "provenance.json",
        dimr_sha256=sha256(dimr.read_bytes()).hexdigest(),
    )
    payload = json.loads(provenance.read_text(encoding="utf-8"))
    payload["fbc"]["version"] = "1.6.0"
    provenance.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError, match=r"fbc\.version must be 1\.6\.1"):
        load_dflow_provenance(provenance)


def test_cli_complete_self_declared_provenance_remains_blocked(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Matching files and manifests cannot self-authorize the CLI runtime."""

    dimr = tmp_path / "dimr"
    dimr.write_bytes(b"reviewed dimr")
    provenance_file = _write_provenance(
        tmp_path / "provenance.json",
        dimr_sha256=sha256(dimr.read_bytes()).hexdigest(),
    )
    workspace, dimr_config = _workspace(tmp_path)
    launches: list[tuple[object, ...]] = []

    def reject_popen(*args, **kwargs):
        """Prove the empty source acceptance gate precedes process creation."""

        launches.append((*args, kwargs))
        raise AssertionError("Popen must not be called while acceptance is empty")

    monkeypatch.setattr(runtime_module, "Popen", reject_popen)
    runtime = CliDFlowRuntime(_cli_config(tmp_path, dimr, provenance_file))

    command = runtime.build_command(
        DFlowRuntimeRequest(workspace=workspace, dimr_config=dimr_config)
    )
    available, detail = runtime.availability()
    verified, verified_detail, metadata = runtime.verified_provenance()
    with pytest.raises(Hydraulic1DRuntimeUnavailable) as raised:
        runtime.execute(
            DFlowRuntimeRequest(workspace=workspace, dimr_config=dimr_config)
        )

    assert command == (str(dimr.resolve()), "control/dimr_config.xml")
    assert not any(token in command for token in ("dflowfm", "fbc"))
    assert available is False
    assert "CLI binding acceptance allowlist is empty" in detail
    assert (verified, verified_detail, metadata) == (False, detail, None)
    assert raised.value.code == DFLOW_RUNTIME_BLOCKED
    assert launches == []


def test_cli_blocks_when_any_component_artifact_hash_drifts(tmp_path: Path) -> None:
    """A valid DIMR hash cannot vouch for different D-Flow/FBC/HYDROLIB bytes."""

    dimr = tmp_path / "dimr"
    dimr.write_bytes(b"reviewed dimr")
    provenance = _write_provenance(
        tmp_path / "provenance.json",
        dimr_sha256=sha256(dimr.read_bytes()).hexdigest(),
    )
    (tmp_path / "fbc.reviewed").write_bytes(b"replaced after review")

    available, detail = CliDFlowRuntime(
        _cli_config(tmp_path, dimr, provenance)
    ).availability()

    assert available is False
    assert detail.startswith(DFLOW_RUNTIME_BLOCKED)
    assert "fbc artifact SHA-256" in detail


def test_container_argv_is_digest_pinned_owned_and_network_disabled(
    tmp_path: Path,
) -> None:
    """The container command cannot use latest, the network, or a shared workspace."""

    docker = tmp_path / "docker"
    docker.write_bytes(b"docker client")
    provenance_file = _write_provenance(
        tmp_path / "provenance.json", dimr_sha256="f" * 64
    )
    image = f"registry.example/dayu/dflow@sha256:{'1' * 64}"
    config = DFlowRuntimeConfig.from_environment(
        {
            "DFLOW_RUNTIME": "container",
            "DFLOW_DOCKER_EXECUTABLE": str(docker),
            "DFLOW_CONTAINER_IMAGE": image,
            "DFLOW_PROVENANCE_FILE": str(provenance_file),
            "DFLOW_WORKSPACE_ROOT": str(tmp_path / "runtime"),
        }
    )
    workspace, dimr_config = _workspace(tmp_path)

    command = ContainerDFlowRuntime(config).build_command(
        DFlowRuntimeRequest(workspace=workspace, dimr_config=dimr_config)
    )

    assert command[0] == str(docker.resolve())
    assert command[1] == "run"
    assert command[command.index("--pull") + 1] == "never"
    assert command[command.index("--network") + 1] == "none"
    assert command[command.index("--label") + 1] == (
        f"{CONTAINER_OWNER_LABEL}={workspace.owner_token}"
    )
    assert image in command
    assert command[-2:] == ("dimr", "control/dimr_config.xml")
    assert "latest" not in command


def test_container_matching_self_declared_metadata_remains_blocked(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Digest and OCI labels remain diagnostic until a trust root is committed."""

    docker = tmp_path / "docker"
    docker.write_bytes(b"docker client")
    provenance_file = _write_provenance(
        tmp_path / "provenance.json", dimr_sha256="f" * 64
    )
    provenance = load_dflow_provenance(provenance_file)
    digest = f"sha256:{'2' * 64}"
    image = f"registry.example/dayu/dflow@{digest}"
    config = DFlowRuntimeConfig.from_environment(
        {
            "DFLOW_RUNTIME": "container",
            "DFLOW_DOCKER_EXECUTABLE": str(docker),
            "DFLOW_CONTAINER_IMAGE": image,
            "DFLOW_PROVENANCE_FILE": str(provenance_file),
            "DFLOW_WORKSPACE_ROOT": str(tmp_path / "runtime"),
        }
    )
    inspected = {
        "Id": digest,
        "RepoDigests": [image],
        "Os": provenance.dimr.platform,
        "Architecture": provenance.dimr.architecture,
        "Config": {
            "Labels": {
                "org.opencontainers.image.source": (
                    "https://github.com/Deltares/Delft3D"
                ),
                "org.opencontainers.image.version": DFLOW_UPSTREAM_TAG,
                "org.opencontainers.image.revision": DFLOW_UPSTREAM_COMMIT,
                runtime_module.CONTAINER_PROVENANCE_LABEL: (
                    provenance.canonical_sha256()
                ),
            }
        },
    }
    monkeypatch.setattr(
        ContainerDFlowRuntime,
        "_inspect_image",
        lambda _self: inspected,
    )
    monkeypatch.setattr(
        runtime_module,
        "Popen",
        lambda *_args, **_kwargs: pytest.fail("container must not launch"),
    )
    runtime = ContainerDFlowRuntime(config)
    workspace, dimr_config = _workspace(tmp_path)

    available, detail = runtime.availability()
    verified, verified_detail, metadata = runtime.verified_provenance()
    with pytest.raises(Hydraulic1DRuntimeUnavailable) as raised:
        runtime.execute(
            DFlowRuntimeRequest(workspace=workspace, dimr_config=dimr_config)
        )

    assert available is False
    assert "container image digest acceptance allowlist is empty" in detail
    assert (verified, verified_detail, metadata) == (False, detail, None)
    assert raised.value.code == DFLOW_RUNTIME_BLOCKED


def test_complete_provenance_loader_exposes_all_required_fields(tmp_path: Path) -> None:
    """Every component identity contains version, source, binary, platform, and build facts."""

    path = _write_provenance(tmp_path / "provenance.json", dimr_sha256="1" * 64)

    provenance = load_dflow_provenance(path)

    assert provenance.dflowfm.upstream_tag == DFLOW_UPSTREAM_TAG
    assert provenance.dimr.upstream_commit == DFLOW_UPSTREAM_COMMIT
    assert provenance.fbc.source_manifest_sha256 == "a" * 64
    assert provenance.hydrolib_core.version == "1.0.1"
