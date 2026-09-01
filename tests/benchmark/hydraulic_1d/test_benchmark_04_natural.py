"""Benchmark 04: multiple natural cross sections."""

from json import loads

from model.hydraulic_1d.mascaret.adapter import MascaretModelBuilder
from tests.benchmark.hydraulic_1d.cases import benchmark_04_natural_sections


def test_natural_section_mapping_preserves_ids_and_chainage(tmp_path) -> None:
    """Keep all profile identities and ordered chainages in the private manifest."""

    workspace = tmp_path / "job"
    workspace.mkdir()
    prepared = MascaretModelBuilder().build(benchmark_04_natural_sections().model, workspace)
    manifest = loads(prepared.manifest_file.read_text(encoding="ascii"))
    assert [item["dayu_id"] for item in manifest["cross_sections"]] == [
        "section-1",
        "section-2",
        "section-3",
    ]
    assert [item["chainage_m"] for item in manifest["cross_sections"]] == [0.0, 500.0, 1000.0]
