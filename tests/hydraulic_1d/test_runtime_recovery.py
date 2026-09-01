"""Verify stale MASCARET attempts are recovered only with exact OS identity."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from subprocess import DEVNULL, Popen
from types import SimpleNamespace

import pytest

from model.hydraulic_1d.errors import Hydraulic1DExecutionError
from model.hydraulic_1d.mascaret import runtime_recovery
from model.hydraulic_1d.mascaret.runtime_recovery import (
    PROCESS_IDENTITY_ENV,
    attach_runtime_process,
    mark_runtime_launching,
    recover_abandoned_attempt,
    remove_owned_container,
)
from model.hydraulic_1d.mascaret.workspace import (
    MascaretJobWorkspace,
    mascaret_attempt_job_id,
    read_workspace_marker,
)


def _job_id(token: str) -> str:
    """Build one test identity using the same task lease contract as workers."""

    return mascaret_attempt_job_id(
        task_id=17,
        execution_attempt_count=2,
        execution_token=token,
    )


def test_attempt_job_id_binds_the_execution_token() -> None:
    """A replacement database lease must never reuse the previous workspace ID."""

    assert _job_id("first-token") != _job_id("replacement-token")


def test_created_workspace_can_be_recovered_before_launch(tmp_path: Path) -> None:
    """A crash before Popen has no external resource and is safe to clean."""

    job_id = _job_id("created")
    workspace = MascaretJobWorkspace.create(
        tmp_path,
        simulation_id="simulation-created",
        job_id=job_id,
    )

    outcome = recover_abandoned_attempt(tmp_path, job_id=job_id)

    assert outcome.safe is True
    assert not workspace.path.exists()


def test_launch_window_fails_closed_without_a_runtime_handle(tmp_path: Path) -> None:
    """Never requeue when a crash occurred between Popen intent and OS attachment."""

    job_id = _job_id("launching")
    workspace = MascaretJobWorkspace.create(
        tmp_path,
        simulation_id="simulation-launching",
        job_id=job_id,
    )
    mark_runtime_launching(
        workspace.path,
        runtime_kind="cli",
        command=("mascaret", "case.xcas"),
        container_label=None,
    )

    outcome = recover_abandoned_attempt(tmp_path, job_id=job_id)

    assert outcome.safe is False
    assert "unidentifiable process launch window" in outcome.detail
    assert workspace.path.is_dir()


def test_recovery_never_deletes_another_execution_token(tmp_path: Path) -> None:
    """A stale scheduler lookup may affect only its exact execution-token marker."""

    owned = MascaretJobWorkspace.create(
        tmp_path,
        simulation_id="simulation-token",
        job_id=_job_id("owned"),
    )

    outcome = recover_abandoned_attempt(tmp_path, job_id=_job_id("other"))

    assert outcome.safe is False
    assert owned.path.is_dir()
    assert read_workspace_marker(owned.path)["job_id"] == _job_id("owned")
    owned.cleanup()


def test_live_owned_process_boundary_is_terminated_before_cleanup(tmp_path: Path) -> None:
    """Recover a real Linux session or Windows Job Object, then remove its marker."""

    job_id = _job_id("live-process")
    workspace = MascaretJobWorkspace.create(
        tmp_path,
        simulation_id="simulation-live",
        job_id=job_id,
    )
    command = (sys.executable, "-c", "import time; time.sleep(30)")
    process_identity = mark_runtime_launching(
        workspace.path,
        runtime_kind="cli",
        command=command,
        container_label=None,
    )
    environment = dict(os.environ)
    environment[PROCESS_IDENTITY_ENV] = process_identity
    process: Popen[bytes] = Popen(
        command,
        cwd=workspace.path,
        env=environment,
        stdin=DEVNULL,
        stdout=DEVNULL,
        stderr=DEVNULL,
        shell=False,
        start_new_session=os.name != "nt",
        creationflags=(
            subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0
        ),
    )
    guard = attach_runtime_process(
        workspace.path,
        process,
        runtime_kind="cli",
        command=command,
    )
    try:
        outcome = recover_abandoned_attempt(tmp_path, job_id=job_id)
    finally:
        if process.poll() is None:
            guard.terminate()
        guard.close()

    assert outcome.safe is True
    assert process.poll() is not None
    assert not workspace.path.exists()


def test_container_cleanup_requires_cidfile_label_and_confirmed_absence(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """A container is removed only when its immutable attempt label matches."""

    workspace = MascaretJobWorkspace.create(
        tmp_path,
        simulation_id="simulation-container",
        job_id=_job_id("container"),
    )
    (workspace.path / ".mascaret-container.cid").write_text(
        "a" * 64 + "\n",
        encoding="ascii",
    )
    responses = iter(
        (
            SimpleNamespace(returncode=0, stdout=b"expected-label\n", stderr=b""),
            SimpleNamespace(returncode=0, stdout=b"a" * 64, stderr=b""),
            SimpleNamespace(returncode=1, stdout=b"", stderr=b"No such object"),
        )
    )
    calls: list[tuple[str, ...]] = []

    def run(command, **_kwargs):
        """Return factual inspect/remove responses while recording exact argv."""

        calls.append(tuple(command))
        return next(responses)

    monkeypatch.setattr(runtime_recovery, "which", lambda _name: "docker")
    monkeypatch.setattr(runtime_recovery, "run", run)

    remove_owned_container(
        workspace.path,
        expected_label="expected-label",
        process_exited=False,
    )

    assert calls[0][1:3] == ("inspect", "--format")
    assert calls[1][:3] == ("docker", "rm", "--force")
    assert calls[2][:2] == ("docker", "inspect")


def test_container_label_mismatch_never_calls_remove(tmp_path: Path, monkeypatch) -> None:
    """A reused or forged cidfile must not cause deletion of another container."""

    workspace = MascaretJobWorkspace.create(
        tmp_path,
        simulation_id="simulation-container-mismatch",
        job_id=_job_id("container-mismatch"),
    )
    (workspace.path / ".mascaret-container.cid").write_text(
        "b" * 64 + "\n",
        encoding="ascii",
    )
    calls: list[tuple[str, ...]] = []

    def run(command, **_kwargs):
        """Expose a different immutable label for the recorded container ID."""

        calls.append(tuple(command))
        return SimpleNamespace(returncode=0, stdout=b"another-attempt\n", stderr=b"")

    monkeypatch.setattr(runtime_recovery, "which", lambda _name: "docker")
    monkeypatch.setattr(runtime_recovery, "run", run)

    with pytest.raises(Hydraulic1DExecutionError, match="identity label mismatch"):
        remove_owned_container(
            workspace.path,
            expected_label="expected-label",
            process_exited=False,
        )

    assert len(calls) == 1
    assert "rm" not in calls[0]
