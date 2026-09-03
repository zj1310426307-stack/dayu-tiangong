"""Orchestration tests for the development-only D-Flow FM engine."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
import json

import pytest

from model.hydraulic_1d.contracts import HydraulicResult
from model.hydraulic_1d.dflow_fm.adapter import DFlowFMModelValidator
from model.hydraulic_1d.dflow_fm.config import DFlowRuntimeConfig
from model.hydraulic_1d.dflow_fm.engine import DFlowFMEngine
from model.hydraulic_1d.dflow_fm.runtime import DFlowRuntimeResult
from model.hydraulic_1d.engine import Hydraulic1DExecutionContext
from model.hydraulic_1d.errors import Hydraulic1DRuntimeUnavailable
from model.hydraulic_1d.registry import DFLOW_FM_ENGINE_ID, DFLOW_FM_ENGINE_VERSION
from tests.hydraulic_1d.dflow_fm.test_adapter import dflow_model
from tools.run_controlled_pump_engine_acceptance import build_run as build_pump_run
from tools.run_dflow_gate_acceptance import IMAGE


def _config(tmp_path: Path) -> DFlowRuntimeConfig:
    return DFlowRuntimeConfig(
        runtime="disabled",
        dimr_executable="dimr",
        dimr_executable_sha256=None,
        docker_executable="docker",
        container_image=None,
        provenance_file=None,
        timeout_seconds=30.0,
        workspace_root=tmp_path,
    )


class _AvailableRuntime:
    def __init__(self) -> None:
        self.request = None

    def availability(self) -> tuple[bool, str]:
        return True, "reviewed synthetic runtime fake"

    def execute(self, request, *, cancel_check=None) -> DFlowRuntimeResult:
        self.request = request
        assert cancel_check is not None and cancel_check() is False
        return DFlowRuntimeResult(
            command=("dimr", "dimr_config.xml"),
            return_code=0,
            elapsed_seconds=0.25,
            stdout="",
            stderr="",
            provenance={"schema_version": "test-only"},
        )


class _Builder:
    validator = DFlowFMModelValidator()

    def build(self, model, workspace):
        workspace.control_dir.joinpath("dimr_config.xml").write_text(
            "test-only",
            encoding="ascii",
        )
        manifest = workspace.metadata_dir / "dayu-dflow-fm-manifest.json"
        manifest.write_text("{}\n", encoding="ascii")
        return SimpleNamespace(
            job_workspace=workspace,
            dimr_config_file=workspace.control_dir / "dimr_config.xml",
            manifest_file=manifest,
        )


class _Parser:
    def parse(self, model, prepared, *, runtime_seconds):
        assert prepared.manifest_file.is_file()
        assert runtime_seconds == pytest.approx(0.25)
        return HydraulicResult(
            simulation_id=model.simulation_id,
            scenario_id=model.scenario_id,
            engine=DFLOW_FM_ENGINE_ID,
            engine_version=DFLOW_FM_ENGINE_VERSION,
            records=(),
        )


def test_default_disabled_engine_fails_before_workspace_creation(
    tmp_path: Path,
) -> None:
    engine = DFlowFMEngine(config=_config(tmp_path))

    assert engine.availability()[0] is False
    assert engine.runtime_provenance()["provenance_complete"] is False
    with pytest.raises(Hydraulic1DRuntimeUnavailable) as blocked:
        engine.run(
            dflow_model(),
            Hydraulic1DExecutionContext(job_id="df01-disabled"),
        )
    assert blocked.value.code == "DFLOW_RUNTIME_BLOCKED"
    assert list(tmp_path.iterdir()) == []


def test_engine_builds_runs_and_parses_one_isolated_dimr_job(tmp_path: Path) -> None:
    runtime = _AvailableRuntime()
    progress: list[tuple[float, str]] = []
    engine = DFlowFMEngine(
        config=_config(tmp_path),
        runtime=runtime,  # type: ignore[arg-type]
        builder=_Builder(),  # type: ignore[arg-type]
        parser=_Parser(),  # type: ignore[arg-type]
    )

    result = engine.run(
        dflow_model(),
        Hydraulic1DExecutionContext(
            job_id="df01-test",
            cancel_check=lambda: False,
            progress_callback=lambda value, detail: progress.append(
                (value, str(detail["phase"]))
            ),
        ),
    )

    assert result.engine == DFLOW_FM_ENGINE_ID
    assert result.engine_version == DFLOW_FM_ENGINE_VERSION
    assert result.diagnostics["evidence_class"] == "SYNTHETIC_NUMERICAL_ONLY"
    assert result.diagnostics["real_engineering_validation"] is False
    assert runtime.request.workspace.path == tmp_path / "df01" / "df01-test"
    assert runtime.request.dimr_config.parent.name == "control"
    assert progress == [
        (5.0, "validated"),
        (20.0, "prepared"),
        (90.0, "parsing"),
        (100.0, "complete"),
    ]


def test_engine_compiles_gate_rule_with_independent_pump_schedule(
    tmp_path: Path,
) -> None:
    repository = Path(__file__).resolve().parents[3]
    engine = DFlowFMEngine(
        config=DFlowRuntimeConfig(
            runtime="container",
            dimr_executable="dimr",
            dimr_executable_sha256=None,
            docker_executable="docker",
            container_image=IMAGE,
            provenance_file=repository
            / "model/hydraulic_1d/dflow_fm/acceptance/DIMRset_2026.02/runtime-provenance.json",
            timeout_seconds=300.0,
            workspace_root=tmp_path,
        )
    )

    compiled = engine.compile_control(
        build_pump_run(joint=True, gate_rule=True),
        tmp_path,
    )

    manifest_artifact = next(
        item for item in compiled.artifacts if item.artifact_type == "manifest"
    )
    manifest = json.loads(
        (tmp_path / manifest_artifact.relative_path).read_text(encoding="utf-8")
    )
    assert manifest["semantic_contract"]["kind"] == (
        "gate_threshold_with_manual_schedules"
    )
