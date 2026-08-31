"""Benchmark 05: independent upstream Q(t) and downstream H(t)."""

from xml.etree.ElementTree import parse

from model.hydraulic_1d.mascaret.adapter import MascaretModelBuilder
from tests.benchmark.hydraulic_1d.cases import benchmark_05_boundary_series


def test_endpoint_boundary_types_and_files_remain_distinct(tmp_path) -> None:
    """Register upstream hydrograph as type 1 and downstream limnigraph as type 2."""

    workspace = tmp_path / "job"
    workspace.mkdir()
    prepared = MascaretModelBuilder().build(benchmark_05_boundary_series().model, workspace)
    laws = parse(prepared.case_file).findall(".//structureParametresLoi")
    assert [item.findtext("type") for item in laws] == ["1", "2"]
    assert prepared.boundary_files[0].read_text(encoding="ascii") != prepared.boundary_files[
        1
    ].read_text(encoding="ascii")
