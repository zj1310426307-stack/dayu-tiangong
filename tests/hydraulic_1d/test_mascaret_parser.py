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


def test_parser_accepts_the_official_native_first_step_time_axis(tmp_path) -> None:
    """Accept native output that begins at dt while retaining one complete axis."""

    workspace = tmp_path / "native-axis"
    workspace.mkdir()
    model = model_fixture()
    prepared = MascaretModelBuilder().build(model, workspace)
    lines = FIXTURE.read_text(encoding="iso-8859-1").splitlines()
    prepared.result_file.write_text(
        "\n".join(
            "10.0;" + line.removeprefix("0.0;") if line.startswith("0.0;") else line
            for line in lines
        )
        + "\n",
        encoding="iso-8859-1",
    )

    result = MascaretResultParser().parse(model, prepared, runtime_seconds=0.1)

    assert result.records[0].timestamp == 10.0
    assert result.diagnostics["time_axis_mode"] == "mascaret-native"


def test_parser_normalizes_signed_rezo_froude_magnitude(tmp_path) -> None:
    """Keep the unified Froude contract non-negative when REZO signs flow direction."""

    workspace = tmp_path / "signed-froude"
    workspace.mkdir()
    model = model_fixture()
    prepared = MascaretModelBuilder().build(model, workspace)
    prepared.result_file.write_text(
        FIXTURE.read_text(encoding="iso-8859-1").replace(";0.12", ";-0.12"),
        encoding="iso-8859-1",
    )

    result = MascaretResultParser().parse(model, prepared, runtime_seconds=0.1)

    assert 0.12 in {item.froude_number for item in result.records}
    assert all(
        item.froude_number is not None and item.froude_number >= 0.0
        for item in result.records
    )


def test_parser_reads_global_and_storage_aware_confluence_mass_reports(
    tmp_path,
) -> None:
    """Use official listing storage terms for node and network continuity evidence."""

    listing = tmp_path / "results.lis"
    listing.write_text(
        """
ERREUR RELATIVE : -2.5000E-03
ERREUR SUR LA MASSE D'EAU : -1.2500E+00
BILAN DE MASSE FINAL DANS LE CONFLUENT : 2
MASSE D'EAU INITIALE : 1.0000E+02
MASSE D'EAU ENTREE AUX FRONTIERES : 5.0000E+02
MASSE D'EAU SORTIE AUX FRONTIERES : 4.9000E+02
MASSE D'EAU FINALE : 1.0900E+02
ERREUR SUR LA MASSE D'EAU : 1.0000E+00
==============================
""".lstrip(),
        encoding="iso-8859-1",
    )

    diagnostics = MascaretResultParser._native_mass_balance(listing)

    assert diagnostics["network_mass_balance_residual"] == pytest.approx(0.0025)
    assert diagnostics["network_mass_balance_error_m3"] == pytest.approx(1.25)
    assert diagnostics["node_continuity_residual"] == pytest.approx(0.002)
    assert diagnostics["node_continuity"] == [
        {
            "mascaret_node_number": 2,
            "initial_volume_m3": 100.0,
            "inflow_volume_m3": 500.0,
            "outflow_volume_m3": 490.0,
            "final_volume_m3": 109.0,
            "mass_error_m3": 1.0,
            "continuity_residual": 0.002,
        }
    ]
