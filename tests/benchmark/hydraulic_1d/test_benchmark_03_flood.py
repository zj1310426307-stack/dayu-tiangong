"""Benchmark 03: non-steady flood hydrograph."""

from model.hydraulic_1d.mascaret.adapter import MascaretModelBuilder
from tests.benchmark.hydraulic_1d.cases import benchmark_03_flood_hydrograph


def test_flood_peak_and_time_are_preserved_in_boundary_law(tmp_path) -> None:
    """Keep the Q peak and argmax time intact for result peak/arrival metrics."""

    workspace = tmp_path / "job"
    workspace.mkdir()
    prepared = MascaretModelBuilder().build(benchmark_03_flood_hydrograph().model, workspace)
    samples = [
        tuple(map(float, line.split()))
        for line in prepared.boundary_files[0].read_text(encoding="ascii").splitlines()
        if line and not line.startswith("#") and line.strip() != "S"
    ]
    assert max(samples, key=lambda item: item[1]) == (1200.0, 35.0)
