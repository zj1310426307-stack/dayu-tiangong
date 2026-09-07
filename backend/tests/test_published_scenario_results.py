"""Contract tests for locally published, uncalibrated scenario results."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.model_engine import scenario_results


def _manifest() -> dict[str, object]:
    """Return the smallest valid two-Section result bundle."""

    sections = [
        {
            "cross_section_id": "DM1",
            "chainage_m": 0.0,
            "bed_min_m": 30.0,
            "final_water_level_m": 35.0,
            "final_depth_m": 5.0,
            "final_discharge_m3s": 100.0,
            "final_velocity_ms": 1.0,
            "flow_area_m2": 100.0,
        },
        {
            "cross_section_id": "DM2",
            "chainage_m": 100.0,
            "bed_min_m": 29.0,
            "final_water_level_m": 34.0,
            "final_depth_m": 5.0,
            "final_discharge_m3s": 100.0,
            "final_velocity_ms": 1.2,
            "flow_area_m2": 83.3,
        },
    ]
    return {
        "bundle_id": "test-result",
        "title": "测试方案成果",
        "river_name": "测试河",
        "schema_version": "dayu.test.v1",
        "generated_at": "2026-09-07T08:27:54Z",
        "classification": "UNCALIBRATED_SCENARIO_CALCULATION",
        "acceptance": "NUMERICAL_QA_PASSED",
        "not_claimed": ["calibration"],
        "input": {"source_crs": "EPSG:4547"},
        "physical_assumptions": {"manning_n": 0.029},
        "numerical_acceptance": {"solver": "MASCARET v9.1.1"},
        "runtime_provenance": {"engine_name": "mascaret", "engine_version": "v9.1.1"},
        "scenarios": [
            {
                "scenario_id": "q100",
                "label": "Q=100",
                "q_m3s": 100.0,
                "downstream_h_m": 34.0,
                "status": "COMPLETED_QUASI_STEADY",
                "mesh_spacing_m": 20.0,
                "time_step_seconds": 0.1,
                "duration_seconds": 3600.0,
                "upstream_water_level_m": 35.0,
                "maximum_water_level_m": 35.0,
                "minimum_depth_m": 5.0,
                "maximum_velocity_ms": 1.2,
                "final_discharge_span_m3s": 0.0,
                "mass_balance_residual": 0.00001,
                "quality_gate": {
                    "temporal_converged": True,
                    "mass_balance_residual": 0.00001,
                    "mass_balance_tolerance": 0.001,
                    "final_discharge_span_m3s": 0.0,
                    "final_discharge_span_tolerance_m3s": 0.5,
                    "passed": True,
                },
                "section_summary": sections,
            }
        ],
    }


def _write_bundle(root: Path, payload: dict[str, object]) -> None:
    """Write one test manifest under the required content-addressable layout."""

    directory = root / str(payload["bundle_id"])
    directory.mkdir(parents=True)
    (directory / "manifest.json").write_text(
        json.dumps(payload, ensure_ascii=False), encoding="utf-8"
    )


def test_lists_valid_result_bundle_with_digest(tmp_path: Path) -> None:
    """A valid private manifest is normalized and assigned a content digest."""

    _write_bundle(tmp_path, _manifest())
    bundles = scenario_results.list_published_scenario_results(tmp_path)

    assert len(bundles) == 1
    assert bundles[0].bundle_id == "test-result"
    assert len(bundles[0].source_digest) == 64
    assert [item.cross_section_id for item in bundles[0].scenarios[0].section_summary] == [
        "DM1",
        "DM2",
    ]


def test_rejects_non_increasing_downstream_axis(tmp_path: Path) -> None:
    """A result package cannot silently reverse its Section order."""

    payload = _manifest()
    payload["scenarios"][0]["section_summary"][1]["chainage_m"] = 0.0  # type: ignore[index]
    _write_bundle(tmp_path, payload)

    with pytest.raises(scenario_results.ScenarioResultBundleError, match="increase downstream"):
        scenario_results.list_published_scenario_results(tmp_path)


def test_api_exposes_published_results_without_database(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The visualization feed remains readable even when no Dataset Version is selected."""

    _write_bundle(tmp_path, _manifest())
    monkeypatch.setattr(scenario_results, "SCENARIO_RESULT_ROOT", tmp_path)

    response = TestClient(app).get("/api/v1/model/scenario-results")

    assert response.status_code == 200
    assert response.json()[0]["river_name"] == "测试河"
    assert response.json()[0]["classification"] == "UNCALIBRATED_SCENARIO_CALCULATION"
