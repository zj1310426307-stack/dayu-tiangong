"""Verify D-Flow native artifacts cannot escape or share a job workspace."""

from __future__ import annotations

from pathlib import Path

import pytest

from model.hydraulic_1d.dflow_fm.workspace import (
    WORKSPACE_AREAS,
    DFlowJobWorkspace,
)
from model.hydraulic_1d.errors import Hydraulic1DExecutionError


def test_workspace_has_exact_isolated_native_areas(tmp_path: Path) -> None:
    """Create the task-prescribed input/control/output/logs/metadata layout."""

    workspace = DFlowJobWorkspace.create(
        tmp_path / "runtime",
        simulation_id="simulation-17",
        job_id="job-3",
    )

    assert workspace.path == (tmp_path / "runtime/simulation-17/job-3").resolve()
    assert {child.name for child in workspace.path.iterdir()} == set(WORKSPACE_AREAS)
    assert DFlowJobWorkspace.open(workspace.path) == workspace


def test_workspace_rejects_identity_and_artifact_traversal(tmp_path: Path) -> None:
    """Neither path identities nor native filenames may traverse their owner root."""

    with pytest.raises(Hydraulic1DExecutionError, match="safe workspace identifier"):
        DFlowJobWorkspace.create(
            tmp_path,
            simulation_id="../another-simulation",
            job_id="job",
        )
    workspace = DFlowJobWorkspace.create(
        tmp_path,
        simulation_id="simulation",
        job_id="job",
    )

    with pytest.raises(Hydraulic1DExecutionError, match="non-traversing"):
        workspace.resolve_in("control", "../outside.xml")
    with pytest.raises(Hydraulic1DExecutionError, match="non-traversing"):
        workspace.resolve_in("input", tmp_path / "absolute.ini")


def test_same_job_workspace_cannot_be_reused(tmp_path: Path) -> None:
    """A duplicate execution identity must fail instead of sharing mutable native files."""

    DFlowJobWorkspace.create(tmp_path, simulation_id="simulation", job_id="job")

    with pytest.raises(Hydraulic1DExecutionError) as raised:
        DFlowJobWorkspace.create(tmp_path, simulation_id="simulation", job_id="job")

    assert raised.value.code == "DFLOW_WORKSPACE_CONFLICT"


def test_marker_tampering_is_detected_before_launch(tmp_path: Path) -> None:
    """The external boundary must not trust a job directory whose owner changed."""

    workspace = DFlowJobWorkspace.create(
        tmp_path,
        simulation_id="simulation",
        job_id="job",
    )
    workspace.marker_path.write_text("{}\n", encoding="ascii")

    with pytest.raises(Hydraulic1DExecutionError, match="safe workspace identifier"):
        workspace.validate()
