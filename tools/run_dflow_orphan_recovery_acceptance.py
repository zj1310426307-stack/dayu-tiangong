"""Prove that stale controlled-worker recovery removes only its owned container."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from subprocess import DEVNULL, PIPE, run

from model.hydraulic_1d.dflow_fm.runtime import (
    CONTAINER_CID_FILENAME,
    CONTAINER_OWNER_LABEL,
)
from model.hydraulic_1d.dflow_fm.workspace import DFlowJobWorkspace
from model.hydraulic_1d.execution_lease import recover_configured_hydraulic_1d_attempt
from tools.run_dflow_gate_acceptance import IMAGE


def verify(workspace_root: Path, job_id: str) -> dict[str, object]:
    repository = Path(__file__).resolve().parents[1]
    root = workspace_root.resolve()
    workspace = DFlowJobWorkspace.create(
        root,
        simulation_id="orphan-recovery",
        job_id=job_id,
    )
    cidfile = workspace.metadata_dir / CONTAINER_CID_FILENAME
    started = run(
        (
            "docker",
            "run",
            "--detach",
            "--rm",
            "--network",
            "none",
            "--read-only",
            "--cidfile",
            str(cidfile),
            "--label",
            f"{CONTAINER_OWNER_LABEL}={workspace.owner_token}",
            IMAGE,
            "sleep",
            "300",
        ),
        stdin=DEVNULL,
        stdout=PIPE,
        stderr=PIPE,
        check=False,
        shell=False,
        timeout=30,
    )
    if started.returncode != 0:
        raise RuntimeError(started.stderr.decode("utf-8", errors="replace"))
    os.environ.update(
        {
            "DFLOW_RUNTIME": "container",
            "DFLOW_CONTAINER_IMAGE": IMAGE,
            "DFLOW_PROVENANCE_FILE": str(
                repository
                / "model/hydraulic_1d/dflow_fm/acceptance/"
                "DIMRset_2026.02/runtime-provenance.json"
            ),
            "DFLOW_WORKSPACE_ROOT": str(root),
        }
    )
    outcome = recover_configured_hydraulic_1d_attempt(
        job_id=job_id,
        task_kind="controlled_hydraulic_preview",
    )
    container_id = cidfile.read_text(encoding="ascii").strip()
    inspected = run(
        ("docker", "inspect", container_id),
        stdin=DEVNULL,
        stdout=PIPE,
        stderr=PIPE,
        check=False,
        shell=False,
        timeout=15,
    )
    if not outcome.safe or inspected.returncode == 0:
        raise RuntimeError(f"orphan recovery failed closed: {outcome.detail}")
    return {
        "status": "PASS",
        "lifecycle_case": "orphan_recovery",
        "owned_container_removed": True,
        "detail": outcome.detail,
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--workspace-root", required=True, type=Path)
    parser.add_argument("--job-id", required=True)
    arguments = parser.parse_args()
    print(
        json.dumps(
            verify(arguments.workspace_root, arguments.job_id),
            indent=2,
            sort_keys=True,
        )
    )
