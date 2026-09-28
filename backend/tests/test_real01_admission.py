"""Unit coverage for conservative REAL-01 admission primitives."""

from types import SimpleNamespace

from app.dataset.engineering_graph import _remap_case_configuration
from app.dataset.real01 import _domain, _has_source_reference, _known_datum
from app.hydraulic.snapshot import _row_snapshot
from app.main import app


def test_real01_datum_requires_an_explicit_non_placeholder_value() -> None:
    """Unknown and blank vertical datums cannot pass real-engineering admission."""

    assert _known_datum("1985 National Height Datum")
    assert not _known_datum("unknown")
    assert not _known_datum("  ")
    assert not _known_datum(None)


def test_real01_source_reference_never_treats_a_numeric_default_as_evidence() -> None:
    """A parameter value alone must not be promoted to a real source record."""

    assert not _has_source_reference({"value": 0.029})
    assert _has_source_reference({"value": 0.029, "source": "survey-log-2026"})


def test_real01_partial_domain_stays_visible_as_a_review_warning() -> None:
    """Partial evidence is not silently converted to an available domain."""

    domain, issue = _domain("GATE", "PARTIAL", "one gate is present")

    assert domain.status == "PARTIAL"
    assert issue is not None
    assert issue.severity == "WARNING"


def test_snapshot_excludes_raw_import_bytes_but_keeps_source_hash() -> None:
    """Raw engineering files remain out of canonical snapshots and Git artifacts."""

    columns = [
        SimpleNamespace(name="id", type=SimpleNamespace(geometry_type=None)),
        SimpleNamespace(name="dataset_version_id", type=SimpleNamespace(geometry_type=None)),
        SimpleNamespace(name="raw_content", type=SimpleNamespace(geometry_type=None)),
        SimpleNamespace(name="source_hash_sha256", type=SimpleNamespace(geometry_type=None)),
        SimpleNamespace(name="branch_id", type=SimpleNamespace(geometry_type=None)),
    ]
    row = SimpleNamespace(
        __table__=SimpleNamespace(columns=columns, schema="hydraulic", name="import_job"),
        id=7,
        dataset_version_id=9,
        raw_content=b"not-for-git",
        source_hash_sha256="a" * 64,
        branch_id=5,
    )

    snapshot = _row_snapshot(
        SimpleNamespace(), row, {"branch": {5: "network-a:branch-a"}}
    )

    assert snapshot["source_hash_sha256"] == "a" * 64
    assert "raw_content" not in snapshot
    assert "id" not in snapshot
    assert snapshot["branch_id"] == "network-a:branch-a"


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
