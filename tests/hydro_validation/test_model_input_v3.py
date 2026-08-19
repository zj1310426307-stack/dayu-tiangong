"""HYDRO-DATA-02 gates for deterministic model-input.v3 deliverables."""

import hashlib
import json

import pytest

from app.hydraulic.validation_artifacts import (
    ValidationArtifactError,
    build_model_input_v3_artifact_bundle,
)


def make_validation_snapshot() -> dict:
    """Return one compact frozen v3 snapshot containing factual audit references."""

    return {
        "schema_version": "dayu.model-input.v3",
        "dataset_version": {
            "id": 31,
            "version": "SYNTHETIC-V1",
            "name": "Production validation survey",
        },
        "simulation_case": {
            "id": 41,
            "case_code": "VALIDATION-Q100",
            "dataset_version_id": 31,
        },
        "coordinate_reference": {
            "display_crs": "EPSG:4490",
            "engineering_crs": "EPSG:4547",
            "horizontal_unit": "m",
            "vertical_datum": "1985 National Height Datum",
            "vertical_unit": "m",
        },
        "coordinate_system": "CGCS2000 (EPSG:4490)",
        "networks": [{"id": 1, "code": "NET-01", "name": "Validation network"}],
        "nodes": [
            {
                "id": 1,
                "node_code": "UP",
                "geometry": {"type": "Point", "coordinates": [113.0, 23.0]},
            },
            {
                "id": 2,
                "node_code": "DOWN",
                "geometry": {"type": "Point", "coordinates": [113.01, 23.01]},
            },
        ],
        "branches": [
            {
                "id": 10,
                "legacy_river_id": 110,
                "branch_code": "BR-01",
                "branch_name": "Main branch",
                "upstream_node_id": 1,
                "downstream_node_id": 2,
                "length_m": 200.0,
                "direction_status": "confirmed",
                "source_revision": "SURVEY-REV-A",
                "centerline": {
                    "type": "LineString",
                    "coordinates": [[113.0, 23.0], [113.01, 23.01]],
                },
            }
        ],
        "reaches": [
            {
                "id": 100,
                "branch_id": 10,
                "reach_code": "REACH-01",
                "start_chainage_m": 0.0,
                "end_chainage_m": 200.0,
            }
        ],
        "cross_sections": [
            {
                "id": 501,
                "branch_id": 10,
                "section_code": "CS-001",
                "chainage_m": 0.0,
                "chainage_source": "survey",
                "snap_distance_m": 0.1,
                "orientation_status": "confirmed",
                "active_profile_id": 901,
                "location": {"type": "Point", "coordinates": [113.0, 23.0]},
            }
        ],
        "cross_section_profiles": [
            {
                "id": 901,
                "cross_section_id": 501,
                "branch_id": 10,
                "section_code": "CS-001",
                "chainage_m": 0.0,
                "topography_id": "SYNTHETIC-TOPO-001",
                "survey_date": "2025-01-01",
                "survey_method": "total_station",
                "vertical_datum": "1985 National Height Datum",
                "profile_hash": "profile-sha-501",
                "points": [
                    {"sequence": 0, "offset_m": 0.0, "elevation_m": 12.0},
                    {"sequence": 1, "offset_m": 5.0, "elevation_m": 9.0},
                    {"sequence": 2, "offset_m": 10.0, "elevation_m": 12.0},
                ],
                "processing": {
                    "id": 701,
                    "processor_version": "hydraulic-table-v1",
                    "vertical_step_m": 0.05,
                },
            }
        ],
        "roughness_zones": [
            {
                "profile_id": 901,
                "zone_order": 0,
                "offset_start_m": 0.0,
                "offset_end_m": 10.0,
                "manning_n": 0.035,
            }
        ],
        "hydraulic_tables": [],
        "boundary_conditions": [
            {
                "id": 801,
                "boundary_type": "upstream_flow",
                "values": {"mode": "constant", "value": 100.0},
            }
        ],
        "parameters": [{"parameter_name": "duration_seconds", "value": 3600.0}],
        "gates": [],
        "pumps": [],
        "controls": {"section_geometry": "tabulated", "allow_fallback_boundary": False},
        "dispatch_plan": None,
        "units": {"length": "m", "time": "s", "flow": "m3/s"},
        "distance_basis": "PostGIS projected geometry in EPSG:4547",
        "engine_version": "dayu-hydraulic-5.0.0",
        "provenance": {
            "engine_commit": "abc123",
            "input_schema_version": "dayu.model-input.v3",
        },
    }


def test_bundle_is_atomic_deterministic_and_hashes_exact_file_bytes() -> None:
    """One detached snapshot must produce a complete reproducible seven-file set."""

    snapshot = make_validation_snapshot()
    original = json.loads(json.dumps(snapshot))
    bundle = build_model_input_v3_artifact_bundle(snapshot)
    reordered = dict(reversed(list(snapshot.items())))
    second = build_model_input_v3_artifact_bundle(reordered)

    expected_names = {
        "network.json",
        "branches.json",
        "cross_sections.json",
        "profiles.json",
        "boundary.json",
        "provenance.json",
        "manifest.json",
    }
    assert set(bundle["files"]) == expected_names
    assert bundle["files"] == second["files"]
    assert snapshot == original

    manifest = json.loads(bundle["files"]["manifest.json"])
    assert manifest == bundle["manifest"]
    assert manifest["source_schema_version"] == "dayu.model-input.v3"
    assert manifest["refs"]["dataset"]["id"] == 31
    assert manifest["refs"]["case"]["id"] == 41
    assert manifest["refs"]["profiles"] == [
        {
            "branch_id": 10,
            "cross_section_id": 501,
            "id": 901,
            "profile_hash": "profile-sha-501",
            "section_code": "CS-001",
            "topography_id": "SYNTHETIC-TOPO-001",
        }
    ]
    assert manifest["refs"]["source"]["branch_revisions"][0]["source_revision"] == "SURVEY-REV-A"
    assert manifest["refs"]["config"]["controls"]["sha256"]
    assert manifest["refs"]["validation"]["branches"][0]["direction_status"] == "confirmed"

    for row in manifest["files"]:
        content = bundle["files"][row["name"]]
        assert row["sha256"] == hashlib.sha256(content).hexdigest()
        assert row["bytes"] == len(content)
    assert bundle["manifest_sha256"] == hashlib.sha256(
        bundle["files"]["manifest.json"]
    ).hexdigest()

    network = json.loads(bundle["files"]["network.json"])
    branches = json.loads(bundle["files"]["branches.json"])
    profiles = json.loads(bundle["files"]["profiles.json"])
    assert network["networks"] == snapshot["networks"]
    assert branches["branches"] == snapshot["branches"]
    assert profiles["cross_section_profiles"] == snapshot["cross_section_profiles"]


def test_bundle_rejects_unverifiable_schema_and_profile_references() -> None:
    """The packager must fail before returning a partial or fabricated bundle."""

    wrong_schema = make_validation_snapshot()
    wrong_schema["schema_version"] = "dayu.model-input.v2"
    with pytest.raises(ValidationArtifactError, match="requires schema_version"):
        build_model_input_v3_artifact_bundle(wrong_schema)

    missing_hash = make_validation_snapshot()
    del missing_hash["cross_section_profiles"][0]["profile_hash"]
    with pytest.raises(ValidationArtifactError, match="profile_hash"):
        build_model_input_v3_artifact_bundle(missing_hash)

    mismatched_case = make_validation_snapshot()
    mismatched_case["simulation_case"]["dataset_version_id"] = 999
    with pytest.raises(ValidationArtifactError, match="does not match"):
        build_model_input_v3_artifact_bundle(mismatched_case)
