"""Unit coverage for conservative REAL-01 admission primitives."""

import inspect
from types import SimpleNamespace

from app.dataset.engineering_graph import (
    _remap_case_configuration,
    _row_values,
    clone_unified_engineering_graph,
)
from app.dataset.real01 import (
    _boundary_ready,
    _coordinate_contract_ready,
    _domain,
    _gate_ready,
    _has_source_reference,
    _known_datum,
    _network_topology_ready,
    _profile_points_ready,
    _qa_matches_graph,
)
from app.gis.models import SimulationCase
from app.hydraulic.models import HydraulicBranch
from app.hydraulic.snapshot import _ENGINEERING_MODELS, _reference_maps, _row_snapshot
from app.main import app


def test_real01_datum_requires_an_explicit_non_placeholder_value() -> None:
    """Unknown and blank vertical datums cannot pass real-engineering admission."""

    assert _known_datum("1985 National Height Datum")
    assert not _known_datum("unknown")
    assert not _known_datum("  ")
    assert not _known_datum(None)


def test_real01_coordinate_contract_requires_crs_axis_and_vertical_evidence() -> None:
    """Neither a CRS code nor a datum string alone can authorize a real import."""

    network = SimpleNamespace(
        engineering_crs="EPSG:4547",
        horizontal_unit="m",
        vertical_unit="m",
        vertical_datum="1985-national-height-datum",
        metadata_json={
            "coordinate_reference": {
                "source_crs": "EPSG:4547",
                "engineering_crs": "EPSG:4547",
                "axis_mapping": "source-X=northing,source-Y=easting",
                "vertical_datum": "1985-national-height-datum",
            }
        },
    )

    assert _coordinate_contract_ready(network)
    network.engineering_crs = None
    assert not _coordinate_contract_ready(network)
    network.engineering_crs = "EPSG:4547"
    network.vertical_datum = "unknown"
    assert not _coordinate_contract_ready(network)


def test_real01_source_reference_never_treats_a_numeric_default_as_evidence() -> None:
    """A parameter value alone must not be promoted to a real source record."""

    assert not _has_source_reference({"value": 0.029})
    assert _has_source_reference({"value": 0.029, "source": "survey-log-2026"})


def test_real01_partial_required_domain_stays_a_freeze_blocker() -> None:
    """Partial required evidence is visible and cannot silently pass a freeze."""

    domain, issue = _domain("GATE", "PARTIAL", "one gate is present")

    assert domain.status == "PARTIAL"
    assert issue is not None
    assert issue.severity == "BLOCKER"


def test_snapshot_excludes_raw_import_bytes_but_keeps_source_hash() -> None:
    """Raw engineering files remain out of canonical snapshots and Git artifacts."""

    columns = [
        SimpleNamespace(name="id", type=SimpleNamespace(geometry_type=None)),
        SimpleNamespace(name="dataset_version_id", type=SimpleNamespace(geometry_type=None)),
        SimpleNamespace(name="raw_content", type=SimpleNamespace(geometry_type=None)),
        SimpleNamespace(name="job_code", type=SimpleNamespace(geometry_type=None)),
        SimpleNamespace(name="source_hash_sha256", type=SimpleNamespace(geometry_type=None)),
        SimpleNamespace(name="branch_id", type=SimpleNamespace(geometry_type=None)),
    ]
    row = SimpleNamespace(
        __table__=SimpleNamespace(columns=columns, schema="hydraulic", name="import_job"),
        id=7,
        dataset_version_id=9,
        raw_content=b"not-for-git",
        job_code="CLONE-9-7",
        source_hash_sha256="a" * 64,
        branch_id=5,
    )

    snapshot = _row_snapshot(
        SimpleNamespace(), row, {"branch": {5: "network-a:branch-a"}}
    )

    assert snapshot["source_hash_sha256"] == "a" * 64
    assert "raw_content" not in snapshot
    assert "job_code" not in snapshot
    assert "id" not in snapshot
    assert snapshot["branch_id"] == "network-a:branch-a"


def test_case_reference_keys_ignore_clone_display_names() -> None:
    """Case-boundary links retain the same hash key after clone renaming."""

    source = SimpleNamespace(id=11, name="REAL-01 base case")
    clone = SimpleNamespace(id=22, name="REAL-01 base case · CLONE")
    empty_rows = {model: [] for model in _ENGINEERING_MODELS}
    source_rows = empty_rows | {SimulationCase: [source]}
    clone_rows = empty_rows | {SimulationCase: [clone]}

    assert _reference_maps(source_rows)["simulation_case"] == {11: "case-000001"}
    assert _reference_maps(clone_rows)["simulation_case"] == {22: "case-000001"}


def test_clone_row_values_use_mapped_attribute_names() -> None:
    """Explicit SQL column names must not break ORM constructor-based cloning."""

    branch = HydraulicBranch(start_chainage=1.0, end_chainage=2.0)

    values = _row_values(branch)

    assert values["start_chainage"] == 1.0
    assert values["end_chainage"] == 2.0
    assert "chainage_start_m" not in values
    assert "chainage_end_m" not in values


def test_real01_readiness_and_freeze_routes_are_part_of_openapi() -> None:
    """The generated frontend client has two explicit contracts to synchronize."""

    paths = app.openapi()["paths"]

    assert "/api/v1/model-data/dataset-versions/{version_id}/real-01-readiness" in paths
    assert "/api/v1/model-data/dataset-versions/{version_id}/freeze-real-01" in paths


def test_graph_clone_remaps_case_structure_and_section_references() -> None:
    """A clone cannot retain source-version IDs in editable Case configuration."""

    source = {
        "structures": {"structure_ids": [31, 32]},
        "initial_condition": {
            "by_section": [
                {"cross_section_id": "41", "water_level_m": 10.0, "discharge_m3s": 8.0}
            ]
        },
    }

    cloned = _remap_case_configuration(
        source,
        structures={31: 131, 32: 132},
        sections={41: 141},
    )

    assert cloned is not None
    assert cloned["structures"]["structure_ids"] == [131, 132]
    assert cloned["initial_condition"]["by_section"][0]["cross_section_id"] == "141"
    assert source["structures"]["structure_ids"] == [31, 32]


def test_real01_topology_accepts_bifurcation_but_rejects_disconnected_graph() -> None:
    """A valid river network may branch, but it may not contain an accidental island."""

    def branch(identifier: int, upstream: int, downstream: int) -> SimpleNamespace:
        return SimpleNamespace(
            id=identifier,
            network_id=1,
            upstream_node_id=upstream,
            downstream_node_id=downstream,
            direction_status="confirmed",
            start_chainage=0.0,
            end_chainage=100.0,
        )

    assert _network_topology_ready(
        [branch(1, 1, 2), branch(2, 2, 3), branch(3, 2, 4)]
    )
    assert not _network_topology_ready(
        [branch(1, 1, 2), branch(2, 3, 4)]
    )


def test_real01_profile_points_require_left_to_right_station_order() -> None:
    """Station must remain strictly increasing from the downstream-looking left bank."""

    ordered = [
        SimpleNamespace(sequence=0, distance=0.0, elevation=5.0),
        SimpleNamespace(sequence=1, distance=12.0, elevation=2.0),
        SimpleNamespace(sequence=2, distance=20.0, elevation=5.5),
    ]
    assert _profile_points_ready(ordered)
    assert not _profile_points_ready(
        [ordered[0], SimpleNamespace(sequence=1, distance=0.0, elevation=2.0)]
    )


def test_real01_boundaries_require_traceable_time_semantics() -> None:
    """A peak value alone is not promoted to an upstream Q(t) boundary."""

    base = {
        "unit": "m3/s",
        "hydraulic_node_id": 9,
        "boundary_type": "upstream_discharge",
    }
    peak_only = SimpleNamespace(
        **base,
        values={"mode": "constant", "value": 405.43, "source": "design-table"},
    )
    series = SimpleNamespace(
        **base,
        values={
            "time_basis": "relative",
            "source": "approved-hydrograph",
            "series": [
                {"time_seconds": 0, "flow_m3_s": 10.0},
                {"time_seconds": 3600, "flow_m3_s": 20.0},
            ],
        },
    )
    assert not _boundary_ready(peak_only)
    assert _boundary_ready(series)


def test_real01_gate_requires_complete_parameters_and_source_evidence() -> None:
    """Gate sill, opening, losses, coefficient, and provenance are all admission inputs."""

    branch = SimpleNamespace(id=3, start_chainage=0.0, end_chainage=1000.0)
    gate = SimpleNamespace(
        branch_id=3,
        chainage_m=500.0,
        invert_elevation_m=1.0,
        width_m=4.0,
        hydraulic_parameters={
            "source": "approved-gate-drawing",
            "correction_coefficient": 0.63,
            "mike11_gate_configuration": {
                "number_of_gates": 2,
                "maximum_value_m": 3.0,
                "initial_value_m": 0.5,
                "maximum_speed_m_per_s": 0.001,
                "underflow_discharge_coefficient": 0.63,
                "head_loss_factors": {"positive_inflow": 0.5},
            },
        },
        operation_parameters={},
        metadata_json={},
    )
    assert _gate_ready(gate, {3: branch})
    gate.invert_elevation_m = None
    assert not _gate_ready(gate, {3: branch})


def test_graph_clone_excludes_external_results_and_historical_acceptance() -> None:
    """Editable clones must not inherit external Solver outputs or acceptance evidence."""

    source = inspect.getsource(clone_unified_engineering_graph)

    assert "HydraulicExternalResult" not in source
    assert "SimulationTask" not in source


def test_real01_rejects_stale_qa_after_engineering_graph_change() -> None:
    """A historical pass cannot authorize a graph with a different content hash."""

    run = SimpleNamespace(
        status="passed",
        summary={"engineering_content_hash": "a" * 64},
    )

    assert _qa_matches_graph(run, "a" * 64)
    assert not _qa_matches_graph(run, "b" * 64)


def test_snapshot_ignores_clone_only_case_display_name() -> None:
    """The version suffix needed by a global DB key does not alter engineering identity."""

    columns = [
        SimpleNamespace(name="id", type=SimpleNamespace(geometry_type=None)),
        SimpleNamespace(name="dataset_version_id", type=SimpleNamespace(geometry_type=None)),
        SimpleNamespace(name="name", type=SimpleNamespace(geometry_type=None)),
        SimpleNamespace(
            name="hydraulic_1d_configuration",
            type=SimpleNamespace(geometry_type=None),
        ),
    ]
    row = SimpleNamespace(
        __table__=SimpleNamespace(columns=columns, schema=None, name="simulation_case"),
        id=3,
        dataset_version_id=9,
        name="Scenario A [clone-v2]",
        hydraulic_1d_configuration={"source": "approved-scenario"},
    )

    snapshot = _row_snapshot(SimpleNamespace(), row)

    assert "name" not in snapshot
    assert snapshot["hydraulic_1d_configuration"] == {
        "source": "approved-scenario"
    }
