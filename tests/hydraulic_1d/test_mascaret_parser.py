"""Verify an official Opthyca-shaped fixture becomes a unified Dayu result."""

from pathlib import Path
from shutil import copyfile

import pytest

from model.hydraulic_1d.errors import Hydraulic1DResultError
from model.hydraulic_1d.mascaret.adapter import MascaretModelBuilder
from model.hydraulic_1d.mascaret.parser import MascaretResultParser
from tests.hydraulic_1d.helpers import model_fixture


FIXTURE = Path(__file__).parents[1] / "fixtures" / "mascaret" / "opthyca_minimal.opt"


def test_opthyca_fixture_maps_to_unified_result(tmp_path) -> None:
    """Map H/Q and geometry-derived V/A/R/top-width for every Dayu section."""

    workspace = tmp_path / "job"
    workspace.mkdir()
    model = model_fixture()
    prepared = MascaretModelBuilder().build(model, workspace)
    copyfile(FIXTURE, prepared.result_file)

    result = MascaretResultParser().parse(model, prepared, runtime_seconds=0.125)

    assert result.engine == "mascaret"
    assert result.engine_version == "v9.1.1"
    assert len(result.records) == 22
    first = result.records[0]
    assert first.cross_section_id == "section-up"
    assert first.water_level_m == 2.0
    assert first.discharge_m3s == 11.0
    assert first.flow_area_m2 == pytest.approx(22.0)
    assert first.velocity_m_s == pytest.approx(0.5)
    assert first.top_width_m == pytest.approx(12.0)


def test_parser_rejects_an_unexpected_reach_or_partial_time_axis(tmp_path) -> None:
    """Rows from another reach and incomplete Section output must fail closed."""

    model = model_fixture()
    for name, transform, message in (
        (
            "wrong-reach",
            lambda value: value.replace('0.0;"1";"1"', '0.0;"2";"1"', 1),
            "unexpected MASCARET reach",
        ),
        (
            "partial-axis",
            lambda value: "\n".join(
                line
                for line in value.splitlines()
                if line != '60.0;"1";"2";1000.0;0.0;3.0;3.0;17.25;0.12'
            )
            + "\n",
            "one time axis",
        ),
        (
            "truncated-axis",
            lambda value: value.replace(
                '600.0;"1";"1";0.0;0.0;3.0;3.0;17.25;0.12\n'
                '600.0;"1";"2";1000.0;0.0;3.0;3.0;17.25;0.12\n',
                "",
            ),
            "complete expected output time axis",
        ),
    ):
        workspace = tmp_path / name
        workspace.mkdir()
        prepared = MascaretModelBuilder().build(model, workspace)
        prepared.result_file.write_text(
            transform(FIXTURE.read_text(encoding="iso-8859-1")),
            encoding="iso-8859-1",
        )
        with pytest.raises(Hydraulic1DResultError, match=message):
            MascaretResultParser().parse(model, prepared, runtime_seconds=0.1)
