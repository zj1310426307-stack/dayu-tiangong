"""Contract gates for the authoritative hydraulic model-input.v3 adapter."""

import copy
import json
from pathlib import Path

import pytest

from model import HydraulicEngine
from model.adapters import adapt_v3_to_v2
from model.core.errors import HydraulicInputError
from tests.test_phase4_network import make_y_network


def _v3_snapshot() -> dict:
    """Lift the established Y-network fixture into the v3 hydraulic domain shape."""

    legacy = make_y_network()
    branch_lookup = {item["id"]: item for item in legacy["rivers"]}
    segments = {item["river_id"]: item for item in legacy["segments"]}
    profiles = []
    for section in legacy["cross_sections"]:
        source_points = section["points"]["points"]
        if len(source_points) == 2:
            source_points = [
                [0.0, 100.0], [1.0, 8.0], [1001.0, 8.0], [1002.0, 100.0]
            ]
        profiles.append({
            "cross_section_id": section["id"],
            "branch_id": section["river_id"],
            "section_code": section["section_code"],
            "chainage_m": section["station"],
            "topography_id": "SURVEY-2026",
            "profile_hash": f"HASH-{section['id']}",
            "default_manning_n": section["roughness"],
            "points": [
                {"offset_m": point[0], "elevation_m": point[1]}
                for point in source_points
            ],
        })
    return {
        **legacy,
        "schema_version": "dayu.model-input.v3",
        "coordinate_reference": {
            "display_crs": "EPSG:4490",
            "engineering_crs": "EPSG:4547",
            "horizontal_unit": "m",
            "vertical_datum": "1985 National Height Datum",
            "vertical_unit": "m",
        },
        "networks": [{"id": 1, "network_code": "TEST-Y"}],
        "nodes": [{
            **node,
            "node_type": "junction",
            "geometry": {"type": "Point", "coordinates": [113 + node["id"] * 0.001, 23]},
        } for node in legacy["nodes"]],
        "branches": [{
            "id": river_id,
            "legacy_river_id": river_id,
            "branch_code": branch_lookup[river_id]["code"],
            "branch_name": branch_lookup[river_id]["name"],
            "start_chainage_m": 0.0,
            "end_chainage_m": branch_lookup[river_id]["length"],
            "length_m": branch_lookup[river_id]["length"],
            "upstream_node_id": segments[river_id]["upstream_node_id"],
            "downstream_node_id": segments[river_id]["downstream_node_id"],
            "centerline": {
                "type": "LineString",
                "coordinates": [[113, 23], [113.01, 23.01]],
            },
        } for river_id in sorted(branch_lookup)],
        "reaches": [{
            "id": 100 + river_id,
            "branch_id": river_id,
            "reach_code": f"REACH-{river_id}",
            "reach_type": "channel",
            "start_chainage_m": 0.0,
            "end_chainage_m": branch_lookup[river_id]["length"],
            "upstream_node_id": segments[river_id]["upstream_node_id"],
            "downstream_node_id": segments[river_id]["downstream_node_id"],
            "length_m": branch_lookup[river_id]["length"],
            "geometry": {
                "type": "LineString",
                "coordinates": [[113, 23], [113.01, 23.01]],
            },
            "parameters": {"start_fraction": 0.0, "end_fraction": 1.0},
        } for river_id in sorted(branch_lookup)],
        "cross_section_profiles": profiles,
        "roughness_zones": [],
        "hydraulic_tables": [],
    }


def test_v3_adapter_preserves_topology_profiles_and_provenance() -> None:
    """The v3-to-v2 boundary must be deterministic and keep source provenance visible."""

    adapted = adapt_v3_to_v2(_v3_snapshot())
    assert adapted["schema_version"] == "dayu.model-input.v2"
    assert adapted["_source_schema_version"] == "dayu.model-input.v3"
    assert len(adapted["segments"]) == 3
    assert [segment["id"] for segment in adapted["segments"]] == [101, 102, 103]
    assert len(adapted["cross_sections"]) == 9
    assert adapted["cross_sections"][0]["topography_id"] == "SURVEY-2026"
    assert adapted["provenance"]["input_schema_version"] == "dayu.model-input.v3"
    assert adapted["provenance"]["reach_count"] == 3


def test_engine_accepts_v3_without_losing_result_input_provenance() -> None:
    """A ready v3 network must run through the established network solver boundary."""

    result = HydraulicEngine().run(_v3_snapshot()).to_dict()
    assert result["schema_version"] == "dayu.hydraulic-result.v2"
    assert result["provenance"]["input_schema_version"] == "dayu.model-input.v3"
    assert len(result["section_series"]) == 9


def test_v3_adapter_maps_branch_scoped_gate_to_its_only_reach() -> None:
    """A compatibility gate stays valid when its branch has one unambiguous Reach."""

    snapshot = _v3_snapshot()
    snapshot["gates"] = [{"id": 9, "river_segment_id": 1}]

    adapted = adapt_v3_to_v2(snapshot)

    assert adapted["gates"][0]["river_segment_id"] == 101


def test_v3_adapter_preserves_multiple_reaches_and_intermediate_node() -> None:
    """A split branch must reach the solver as two directed edges, not one shortcut."""

    snapshot = _v3_snapshot()
    snapshot["nodes"].append({
        "id": 5,
        "node_code": "N-5",
        "node_type": "junction",
        "geometry": {"type": "Point", "coordinates": [113.005, 23.005]},
    })
    first = next(reach for reach in snapshot["reaches"] if reach["branch_id"] == 1)
    snapshot["reaches"] = [
        reach for reach in snapshot["reaches"] if reach["branch_id"] != 1
    ] + [
        {
            **first,
            "id": 104,
            "reach_code": "REACH-1-A",
            "end_chainage_m": 400.0,
            "downstream_node_id": 5,
            "length_m": 400.0,
            "parameters": {"start_fraction": 0.0, "end_fraction": 0.4},
        },
        {
            **first,
            "id": 105,
            "reach_code": "REACH-1-B",
            "start_chainage_m": 400.0,
            "upstream_node_id": 5,
            "length_m": 600.0,
            "parameters": {"start_fraction": 0.4, "end_fraction": 1.0},
        },
    ]

    adapted = adapt_v3_to_v2(snapshot)
    river_one_segments = [
        segment for segment in adapted["segments"] if segment["river_id"] == 1
    ]
    assert [
        (item["id"], item["upstream_node_id"], item["downstream_node_id"])
        for item in river_one_segments
    ] == [(104, 1, 5), (105, 5, 3)]
    result = HydraulicEngine().run(snapshot).to_dict()
    assert any(row["node_id"] == 5 for row in result["node_series"])


def test_v3_adapter_fails_closed_when_reach_chain_is_discontinuous() -> None:
    """A chainage-contiguous but node-disconnected Reach pair must be rejected."""

    snapshot = _v3_snapshot()
    snapshot["nodes"].append({
        "id": 5,
        "node_code": "N-5",
        "node_type": "junction",
        "geometry": {"type": "Point", "coordinates": [113.005, 23.005]},
    })
    original = next(reach for reach in snapshot["reaches"] if reach["branch_id"] == 1)
    snapshot["reaches"] = [
        reach for reach in snapshot["reaches"] if reach["branch_id"] != 1
    ] + [
        {
            **original,
            "id": 104,
            "end_chainage_m": 500.0,
            "downstream_node_id": 5,
            "length_m": 500.0,
        },
        {
            **original,
            "id": 105,
            "start_chainage_m": 500.0,
            "upstream_node_id": 2,
            "length_m": 500.0,
        },
    ]

    with pytest.raises(HydraulicInputError, match="is not contiguous"):
        adapt_v3_to_v2(snapshot)


def test_v3_adapter_fails_closed_when_gate_reach_is_ambiguous() -> None:
    """A branch-scoped legacy gate cannot be guessed onto one of several Reaches."""

    snapshot = copy.deepcopy(_v3_snapshot())
    snapshot["nodes"].append({
        "id": 5,
        "node_code": "N-5",
        "node_type": "junction",
        "geometry": {"type": "Point", "coordinates": [113.005, 23.005]},
    })
    original = next(reach for reach in snapshot["reaches"] if reach["branch_id"] == 1)
    snapshot["reaches"] = [
        reach for reach in snapshot["reaches"] if reach["branch_id"] != 1
    ] + [
        {
            **original,
            "id": 104,
            "end_chainage_m": 500.0,
            "downstream_node_id": 5,
            "length_m": 500.0,
        },
        {
            **original,
            "id": 105,
            "start_chainage_m": 500.0,
            "upstream_node_id": 5,
            "length_m": 500.0,
        },
    ]
    snapshot["gates"] = [{"id": 9, "river_segment_id": 1}]

    with pytest.raises(HydraulicInputError, match="target reach is ambiguous"):
        adapt_v3_to_v2(snapshot)

    snapshot["gates"][0]["station"] = 250.0
    adapted = adapt_v3_to_v2(snapshot)
    assert adapted["gates"][0]["river_segment_id"] == 104
    assert adapted["gates"][0]["reach_id"] == 104

    snapshot["gates"][0]["station"] = 500.0
    with pytest.raises(HydraulicInputError, match="target reach is ambiguous"):
        adapt_v3_to_v2(snapshot)

    snapshot["gates"][0]["reach_id"] = 104
    adapted = adapt_v3_to_v2(snapshot)
    assert adapted["gates"][0]["river_segment_id"] == 104
    assert adapted["gates"][0]["reach_id"] == 104

    snapshot["gates"][0]["station"] = 750.0
    with pytest.raises(HydraulicInputError, match="lies outside explicit"):
        adapt_v3_to_v2(snapshot)


def _canonical_structures() -> dict:
    """Return a complete nested v3 structure envelope for adapter boundary tests."""

    dataset_provenance = {"id": 1, "version": "TEST"}
    return {
        "gates": [{
            "id": 9,
            "dataset_version_id": 1,
            "branch_id": 1,
            "river_segment_id": 1,
            "reach_id": 101,
            "station": 250.0,
            "chainage": 250.0,
            "geometry": {"type": "Point", "coordinates": [113.0025, 23.0]},
            "parameters": {"width": 4.0, "height": 2.0},
            "control_state": {
                "mode": "fixed",
                "status": "uninitialized",
                "availability": "online",
                "opening": None,
            },
            "provenance": {
                "dataset_version": dataset_provenance,
                "chainage_source": "public.gate.station",
                "reach_id": 101,
            },
        }],
        "pumps": [{
            "id": 10,
            "dataset_version_id": 1,
            "branch_id": 1,
            "chainage": None,
            "geometry": {"type": "Point", "coordinates": [113.008, 23.0]},
            "parameters": {"design_flow": 5.0, "pump_count": 1},
            "control_state": {
                "mode": "fixed",
                "status": "uninitialized",
                "availability": "online",
                "running_units": None,
            },
            "provenance": {
                "dataset_version": dataset_provenance,
                "chainage_source": "unavailable_not_inferred",
            },
        }],
    }


def test_v3_adapter_consumes_nested_only_structure_envelope() -> None:
    """The structured v3 envelope is primary; compatibility mirrors are optional input."""

    snapshot = _v3_snapshot()
    snapshot.pop("gates")
    snapshot.pop("pumps")
    snapshot["structures"] = _canonical_structures()
    snapshot["dispatch_plan"] = {"rules": []}
    snapshot["controls"] = {
        **snapshot["controls"],
        "rules": snapshot["dispatch_plan"]["rules"],
    }

    adapted = adapt_v3_to_v2(snapshot)

    assert adapted["gates"][0]["river_segment_id"] == 101
    assert adapted["gates"][0]["provenance"]["reach_resolution"] == (
        "explicit_reach_id"
    )
    assert adapted["pumps"][0]["chainage"] is None
    assert adapted["structures"]["gates"] == adapted["gates"]
    assert adapted["structures"]["pumps"] == adapted["pumps"]


def test_v3_adapter_rejects_divergent_top_level_structure_mirror() -> None:
    """A stale compatibility mirror may never override the authoritative envelope."""

    snapshot = _v3_snapshot()
    snapshot["structures"] = _canonical_structures()
    snapshot["dispatch_plan"] = {"rules": []}
    snapshot["controls"] = {**snapshot["controls"], "rules": []}

    with pytest.raises(HydraulicInputError, match="must match top-level"):
        adapt_v3_to_v2(snapshot)


def test_v3_adapter_accepts_sourced_pump_chainage_without_inference() -> None:
    """Generic v3 producers may locate a pump when they identify the chainage source."""

    snapshot = _v3_snapshot()
    snapshot.pop("gates")
    snapshot.pop("pumps")
    structures = _canonical_structures()
    structures["pumps"][0]["chainage"] = 800.0
    structures["pumps"][0]["provenance"]["chainage_source"] = (
        "synthetic_demo_contract"
    )
    snapshot["structures"] = structures
    snapshot["controls"] = {**snapshot["controls"], "rules": []}

    adapted = adapt_v3_to_v2(snapshot)

    assert adapted["pumps"][0]["chainage"] == 800.0


def test_v3_engine_projects_nested_canonical_structure_parameters() -> None:
    """Nested parameters/state must drive the solver even without flat mirrors."""

    demo_path = (
        Path(__file__).resolve().parents[1]
        / "examples/hydraulic/gate-pump-demo/input.json"
    )
    snapshot = json.loads(demo_path.read_text(encoding="utf-8"))
    snapshot.pop("gates")
    snapshot.pop("pumps")
    for field_name in (
        "width",
        "height",
        "max_flow",
        "status",
        "control_mode",
    ):
        snapshot["structures"]["gates"][0].pop(field_name, None)
    for field_name in (
        "design_flow",
        "head",
        "head_curve",
        "efficiency_curve",
        "unit_count",
        "status",
        "control_mode",
    ):
        snapshot["structures"]["pumps"][0].pop(field_name, None)

    result = HydraulicEngine().run(snapshot).to_dict()

    assert len(result["structure_series"]) == 50
    assert {row["structure_type"] for row in result["structure_series"]} == {
        "gate",
        "pump",
    }


@pytest.mark.parametrize(
    ("structure_type", "flat_field", "flat_value", "parameter_field"),
    [
        ("gates", "max_flow", 20.0, "max_flow"),
        ("pumps", "status", "online", None),
    ],
)
def test_v3_adapter_rejects_canonical_structure_conflicts(
    structure_type: str,
    flat_field: str,
    flat_value: object,
    parameter_field: str | None,
) -> None:
    """A stale flat mirror may not override parameters or availability."""

    snapshot = _v3_snapshot()
    snapshot.pop("gates")
    snapshot.pop("pumps")
    structures = _canonical_structures()
    row = structures[structure_type][0]
    row[flat_field] = flat_value
    if parameter_field is not None:
        row["parameters"][parameter_field] = 1.0
    else:
        row["control_state"]["availability"] = "offline"
    snapshot["structures"] = structures
    snapshot["dispatch_plan"] = {"rules": []}
    snapshot["controls"] = {**snapshot["controls"], "rules": []}

    with pytest.raises(HydraulicInputError, match="canonical .* conflicts"):
        adapt_v3_to_v2(snapshot)
