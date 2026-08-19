"""Synthetic 1,000-section performance gates with explicit coverage limits."""

from __future__ import annotations

import csv
from io import StringIO
import json
from time import perf_counter

from app.hydraulic.importers.tabular import parse_csv
from app.hydraulic.production_validation import SurveyBranch, locate_section_axes
from app.hydraulic.validation_artifacts import build_model_input_v3_artifact_bundle
from model.geometry import TabulatedSectionGeometry
from tests.hydro_validation.test_model_input_v3 import make_validation_snapshot


SECTION_COUNT = 1_000
LIMITS_SECONDS = {
    "import_parser": 60.0,
    "topology_preparation": 30.0,
    "hydraulic_table_numeric_core": 60.0,
    "model_input_artifact_bundle": 10.0,
}


def _synthetic_csv() -> bytes:
    output = StringIO()
    writer = csv.writer(output, lineterminator="\n")
    writer.writerow([
        "record_type", "network_code", "network_name", "branch_code",
        "branch_name", "river_name", "flow_direction", "chainage", "x", "y",
        "section_code", "topography_id", "sequence", "distance", "elevation",
        "default_manning_n", "location_x", "location_y",
    ])
    writer.writerow([
        "branch_point", "SYNTH-1000", "Synthetic 1000-section case", "BR-01",
        "Main", "Synthetic river", "forward", 0, 500000, 2500000,
        "", "", "", "", "", "", "", "",
    ])
    writer.writerow([
        "branch_point", "SYNTH-1000", "Synthetic 1000-section case", "BR-01",
        "Main", "Synthetic river", "forward", SECTION_COUNT, 501000, 2500000,
        "", "", "", "", "", "", "", "",
    ])
    for section_index in range(1, SECTION_COUNT + 1):
        section_code = f"SYN-CS-{section_index:04d}"
        for sequence, (distance, elevation) in enumerate(
            ((0.0, 12.0), (5.0, 9.0), (10.0, 12.0))
        ):
            writer.writerow([
                "section_point", "SYNTH-1000", "Synthetic 1000-section case",
                "BR-01", "Main", "Synthetic river", "forward", section_index,
                "", "", section_code, "SYNTHETIC", sequence, distance, elevation,
                0.035, 500000 + section_index, 2500000,
            ])
    return output.getvalue().encode()


def _axis_features() -> list[dict[str, object]]:
    return [
        {
            "type": "Feature",
            "properties": {"validation_source_ordinal": index},
            "geometry": {
                "type": "LineString",
                "coordinates": [
                    [500000.0 + index - 0.5, 2499990.0],
                    [500000.0 + index - 0.5, 2500010.0],
                ],
            },
        }
        for index in range(1, SECTION_COUNT + 1)
    ]


def _large_snapshot(geometries: list[TabulatedSectionGeometry]) -> dict:
    snapshot = make_validation_snapshot()
    snapshot["branches"][0]["length_m"] = float(SECTION_COUNT)
    snapshot["reaches"][0]["end_chainage_m"] = float(SECTION_COUNT)
    sections = []
    profiles = []
    roughness = []
    tables = []
    for index, geometry in enumerate(geometries, start=1):
        section_id = 10_000 + index
        profile_id = 20_000 + index
        processing_id = 30_000 + index
        chainage = float(index)
        sections.append({
            "id": section_id,
            "branch_id": 10,
            "section_code": f"SYN-CS-{index:04d}",
            "chainage_m": chainage,
            "chainage_source": "synthetic_scale_fixture",
            "snap_distance_m": 0.0,
            "orientation_status": "confirmed",
            "active_profile_id": profile_id,
            "location": {
                "type": "Point",
                "coordinates": [113.0 + index / 100_000.0, 23.0],
            },
        })
        profiles.append({
            "id": profile_id,
            "cross_section_id": section_id,
            "branch_id": 10,
            "section_code": f"SYN-CS-{index:04d}",
            "chainage_m": chainage,
            "topography_id": "SYNTHETIC",
            "survey_method": "generated performance fixture",
            "vertical_datum": "synthetic",
            "profile_hash": f"synthetic-profile-{index:04d}",
            "default_manning_n": 0.035,
            "points": [
                {"sequence": 0, "offset_m": 0.0, "elevation_m": 12.0},
                {"sequence": 1, "offset_m": 5.0, "elevation_m": 9.0},
                {"sequence": 2, "offset_m": 10.0, "elevation_m": 12.0},
            ],
            "processing": {
                "id": processing_id,
                "processor_version": "synthetic-tabulated-core",
                "vertical_step_m": 0.5,
            },
        })
        roughness.append({
            "profile_id": profile_id,
            "zone_order": 0,
            "offset_start_m": 0.0,
            "offset_end_m": 10.0,
            "manning_n": 0.035,
        })
        tables.extend({
            "profile_id": profile_id,
            "processing_id": processing_id,
            "profile_hash": f"synthetic-profile-{index:04d}",
            "stage_m": stage,
            "area_m2": geometry.areas[stage_index],
            "top_width_m": geometry.widths[stage_index],
            "wetted_perimeter_m": geometry.perimeters[stage_index],
        } for stage_index, stage in enumerate(geometry.stages))
    snapshot["cross_sections"] = sections
    snapshot["cross_section_profiles"] = profiles
    snapshot["roughness_zones"] = roughness
    snapshot["hydraulic_tables"] = tables
    snapshot["source_refs"] = {
        "case_type": "synthetic",
        "cross_section_count": SECTION_COUNT,
        "real_survey_data_used": False,
    }
    return snapshot


def test_synthetic_1000_section_stage_budgets() -> None:
    """Measure only executable in-memory stages; never label them as DB production timings."""

    csv_content = _synthetic_csv()
    started = perf_counter()
    payload = parse_csv("synthetic-1000.csv", csv_content, 4547)
    import_seconds = perf_counter() - started
    assert len(payload.sections) == SECTION_COUNT
    assert sum(len(section.points) for section in payload.sections) == 3 * SECTION_COUNT

    branch = SurveyBranch(
        code="BR-01",
        name="Main",
        river_name="Synthetic river",
        source_ordinal=1,
        coordinates=((500000.0, 2500000.0), (501000.0, 2500000.0)),
        chainage_start_m=0.0,
        chainage_end_m=float(SECTION_COUNT),
        annotation_count=0,
        annotation_rmse_m=0.0,
        source_order_reversed=False,
    )
    started = perf_counter()
    axes = locate_section_axes(_axis_features(), [branch])
    topology_seconds = perf_counter() - started
    assert len(axes) == SECTION_COUNT
    assert all(axis.quality == "passed" for axis in axes)

    started = perf_counter()
    geometries = [
        TabulatedSectionGeometry.from_points(
            [(0.0, 12.0), (5.0, 9.0), (10.0, 12.0)],
            vertical_step=0.5,
        )
        for _ in range(SECTION_COUNT)
    ]
    hydraulic_table_seconds = perf_counter() - started
    assert all(len(geometry.stages) == 7 for geometry in geometries)

    snapshot = _large_snapshot(geometries)
    started = perf_counter()
    bundle = build_model_input_v3_artifact_bundle(snapshot)
    model_input_seconds = perf_counter() - started
    assert len(bundle["manifest"]["refs"]["profiles"]) == SECTION_COUNT
    assert set(bundle["files"]) == {
        "network.json", "branches.json", "cross_sections.json", "profiles.json",
        "boundary.json", "provenance.json", "manifest.json",
    }

    timings = {
        "import_parser": import_seconds,
        "topology_preparation": topology_seconds,
        "hydraulic_table_numeric_core": hydraulic_table_seconds,
        "model_input_artifact_bundle": model_input_seconds,
    }
    for stage, seconds in timings.items():
        assert seconds < LIMITS_SECONDS[stage], (
            f"synthetic stage {stage} took {seconds:.6f}s; "
            f"limit is {LIMITS_SECONDS[stage]:.1f}s"
        )

    evidence = {
        "case_type": "synthetic",
        "real_survey_data_used": False,
        "cross_section_count": SECTION_COUNT,
        "profile_points_per_section": 3,
        "hydraulic_table_rows_per_section": 7,
        "timings_seconds": {
            key: round(value, 6) for key, value in timings.items()
        },
        "limits_seconds": LIMITS_SECONDS,
        "coverage": {
            "import_parser": "actual CSV decode and DTO normalisation; excludes HTTP and DB writes",
            "topology_preparation": (
                "actual surveyed-axis to branch location; excludes PostGIS node/reach build"
            ),
            "hydraulic_table_numeric_core": (
                "actual tabulated geometry computation; excludes DB persistence"
            ),
            "model_input_artifact_bundle": (
                "actual seven-file v3 byte bundle from a frozen snapshot; excludes DB queries"
            ),
        },
        "not_claimed": [
            "real-data performance",
            "PostGIS topology timing",
            "database import or hydraulic-table persistence timing",
            "build_model_input_v3 database query timing",
        ],
    }
    print("HYDRO_DATA_02_SYNTHETIC_PERFORMANCE=" + json.dumps(evidence, sort_keys=True))
