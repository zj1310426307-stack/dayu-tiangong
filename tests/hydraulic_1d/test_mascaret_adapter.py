"""Verify Dayu-to-MASCARET model generation and official-style file identities."""

from xml.etree.ElementTree import parse

import pytest

from model.hydraulic_1d import BoundaryCondition, TimeValue
from model.hydraulic_1d.mascaret.adapter import MascaretModelBuilder
from tests.hydraulic_1d.helpers import model_fixture


def test_adapter_builds_isolated_case_and_unique_lateral_law(tmp_path) -> None:
    """Generate complete source files with endpoint laws 1/2 and lateral law 3."""

    workspace = tmp_path / "job"
    workspace.mkdir()
    prepared = MascaretModelBuilder().build(model_fixture(lateral=True), workspace)

    assert prepared.case_file.parent == workspace
    assert prepared.geometry_file.read_text(encoding="ascii").count("PROFIL Bief_1") == 2
    assert len(prepared.boundary_files) == 3
    tree = parse(prepared.case_file)
    assert tree.findtext(".//extrLibres/numLoi") == "1 2"
    assert tree.findtext(".//debitsApports/numLoi") == "3"
    assert tree.findtext(".//resultats/fichResultat") == "results.opt"
    assert (workspace / "FichierCas.txt").read_text(encoding="ascii") == "'case.xcas'\n"


def test_adapter_converts_manning_n_to_longitudinal_strickler(tmp_path) -> None:
    """Write one longitudinal K=1/n value for each authoritative cross section."""

    workspace = tmp_path / "job"
    workspace.mkdir()
    prepared = MascaretModelBuilder().build(
        model_fixture(manning_downstream=0.04),
        workspace,
    )

    values = parse(prepared.case_file).findtext(".//frottement/coefLitMin")
    assert values is not None
    assert [float(item) for item in values.split()] == pytest.approx([1.0 / 0.03, 25.0])


def test_multiple_lateral_laws_share_one_chainage_order(tmp_path) -> None:
    """Bind every lateral hydrograph to the same sorted location used by XCAS."""

    source = model_fixture(lateral=True)
    earlier = BoundaryCondition(
        id="lateral-q-earlier",
        branch_id="branch-1",
        location="lateral",
        variable="discharge",
        chainage_m=100.0,
        series=(TimeValue(time_seconds=0.0, value=7.0),),
    )
    model = source.model_copy(update={"boundaries": (*source.boundaries, earlier)})
    workspace = tmp_path / "job"
    workspace.mkdir()

    prepared = MascaretModelBuilder().build(model, workspace)
    tree = parse(prepared.case_file)

    assert tree.findtext(".//debitsApports/abscisses") == "100 500"
    assert tree.findtext(".//debitsApports/numLoi") == "3 4"
    assert " 7" in prepared.boundary_files[2].read_text(encoding="ascii")
    assert " 0.5" in prepared.boundary_files[3].read_text(encoding="ascii")


def test_structure_free_case_emits_no_unverified_singularities(tmp_path) -> None:
    """Do not emit a guessed Gate/Pump contract into the production case."""

    workspace = tmp_path / "job"
    workspace.mkdir()
    prepared = MascaretModelBuilder().build(model_fixture(), workspace)
    tree = parse(prepared.case_file)

    assert tree.findtext(".//parametresSingularite/nbSeuils") == "0"
    assert [item.findtext("type") for item in tree.findall(".//structureParametresLoi")] == [
        "1",
        "2",
    ]
