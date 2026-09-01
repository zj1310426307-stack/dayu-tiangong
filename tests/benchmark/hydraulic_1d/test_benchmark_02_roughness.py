"""Benchmark 02: longitudinal roughness sensitivity."""

from xml.etree.ElementTree import parse

import pytest

from model.hydraulic_1d.mascaret.adapter import MascaretModelBuilder
from tests.benchmark.hydraulic_1d.cases import benchmark_02_roughness_sensitivity


def test_roughness_triplet_preserves_distinct_strickler_values(tmp_path) -> None:
    """Preserve n1=0.025, n2=0.035, n3=0.045 for the real H/V comparison."""

    case = benchmark_02_roughness_sensitivity()
    assert len(case.comparison_models) == 2
    values_by_case = []
    for name, model in zip(
        ("low", "middle", "high"),
        (case.model, *case.comparison_models),
    ):
        workspace = tmp_path / name
        workspace.mkdir()
        prepared = MascaretModelBuilder().build(model, workspace)
        raw = parse(prepared.case_file).findtext(".//frottement/coefLitMin")
        assert raw is not None
        values_by_case.append([float(item) for item in raw.split()])
    low_values, middle_values, high_values = values_by_case
    assert low_values == pytest.approx([1.0 / 0.025] * 21)
    assert middle_values == pytest.approx([1.0 / 0.035] * 21)
    assert high_values == pytest.approx([1.0 / 0.045] * 21)
    assert min(low_values) > max(high_values)
