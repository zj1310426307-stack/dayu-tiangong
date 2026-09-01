"""Verify unsupported Dayu models fail closed before any external process starts."""

import pytest

from model.hydraulic_1d import (
    BoundaryCondition,
    Hydraulic1DModel,
    HydraulicStructure,
    RoughnessZone,
    SimulationSettings,
    TimeValue,
)
from model.hydraulic_1d.errors import Hydraulic1DValidationError
from model.hydraulic_1d.mascaret.adapter import MascaretModelValidator
from tests.benchmark.hydraulic_1d.network.cases import n01_confluence
from tests.hydraulic_1d.helpers import model_fixture


@pytest.mark.parametrize("kind", ["gate", "pump"])
def test_structure_without_verified_mapping_is_rejected(kind: str) -> None:
    """Prevent Gates or Pumps from entering an unverified MASCARET mapping."""

    model = model_fixture().model_copy(
        update={
            "structures": (
                HydraulicStructure(
                    id=f"{kind}-1",
                    branch_id="branch-1",
                    kind=kind,
                    chainage_m=500.0,
                ),
            )
        }
    )

    with pytest.raises(
        Hydraulic1DValidationError,
        match="MODEL_ENGINE_INCOMPATIBLE",
    ):
        MascaretModelValidator().validate(model)


def test_transverse_roughness_variation_is_rejected() -> None:
    """Do not flatten a materially different transverse roughness zone."""

    first = model_fixture().cross_sections[0]
    changed = first.model_copy(
        update={
            "roughness_zones": (
                RoughnessZone(start_station_m=0.0, end_station_m=20.0, manning_n=0.05),
            )
        }
    )
    source = model_fixture()
    model = source.model_copy(
        update={"cross_sections": (changed, source.cross_sections[1])}
    )

    with pytest.raises(
        Hydraulic1DValidationError,
        match="MASCARET_TRANSVERSE_ROUGHNESS_UNSUPPORTED",
    ):
        MascaretModelValidator().validate(model)


def test_malformed_cross_section_is_rejected_by_unified_contract() -> None:
    """A profile with fewer than three surveyed points never reaches the adapter."""

    payload = model_fixture().model_dump(mode="json")
    payload["cross_sections"][0]["points"] = payload["cross_sections"][0]["points"][:2]

    with pytest.raises(
        Hydraulic1DValidationError,
        match="DAYU_HYDRAULIC_1D_INPUT_INVALID",
    ):
        Hydraulic1DModel.parse_snapshot(payload)


def test_connected_multi_branch_network_is_accepted() -> None:
    """Accept a graph whose native topology is covered by engineering evidence."""

    MascaretModelValidator().validate(n01_confluence().model)


def test_wrong_downstream_boundary_variable_is_rejected() -> None:
    """A downstream discharge cannot be silently interpreted as a stage boundary."""

    source = model_fixture()
    wrong = BoundaryCondition(
        id="downstream-q",
        branch_id="branch-1",
        location="downstream",
        variable="discharge",
        series=(TimeValue(time_seconds=0.0, value=11.0),),
    )
    model = source.model_copy(update={"boundaries": (source.boundaries[0], wrong)})

    with pytest.raises(
        Hydraulic1DValidationError,
        match="MASCARET_DOWNSTREAM_BOUNDARY_INVALID",
    ):
        MascaretModelValidator().validate(model)


def test_one_sample_boundary_must_be_declared_at_zero() -> None:
    """Do not silently reinterpret a future sample as an all-duration constant."""

    source = model_fixture()
    shifted = source.boundaries[0].model_copy(
        update={"series": (TimeValue(time_seconds=30.0, value=11.0),)}
    )
    model = source.model_copy(update={"boundaries": (shifted, source.boundaries[1])})

    with pytest.raises(Hydraulic1DValidationError, match="one-sample constant"):
        MascaretModelValidator().validate(model)


def test_lateral_withdrawal_is_not_silently_mapped_as_inflow() -> None:
    """Reject negative lateral Q until withdrawal semantics are benchmarked."""

    source = model_fixture(lateral=True)
    lateral = source.boundaries[-1].model_copy(
        update={"series": (TimeValue(time_seconds=0.0, value=-0.5),)}
    )
    model = source.model_copy(update={"boundaries": (*source.boundaries[:-1], lateral)})

    with pytest.raises(
        Hydraulic1DValidationError, match="NEGATIVE_DISCHARGE_UNVERIFIED"
    ):
        MascaretModelValidator().validate(model)


def test_cross_section_vertical_datum_must_match_network() -> None:
    """Never combine elevations from different or unknown height datums."""

    source = model_fixture()
    changed = source.cross_sections[1].model_copy(
        update={"vertical_datum": "another-datum"}
    )
    model = source.model_copy(
        update={"cross_sections": (source.cross_sections[0], changed)}
    )

    with pytest.raises(Hydraulic1DValidationError, match="VERTICAL_DATUM_INVALID"):
        MascaretModelValidator().validate(model)


def test_duplicate_chainage_is_rejected_by_unified_contract() -> None:
    """A Branch cannot map two authoritative Sections to the same location."""

    payload = model_fixture().model_dump(mode="json")
    duplicate = dict(payload["cross_sections"][0])
    duplicate.update({"id": "section-duplicate", "code": "XS-DUP"})
    payload["cross_sections"].insert(1, duplicate)

    with pytest.raises(
        Hydraulic1DValidationError,
        match="chainages must be strictly increasing",
    ):
        Hydraulic1DModel.parse_snapshot(payload)


def test_derived_mesh_density_is_bounded() -> None:
    """One tiny local spacing cannot expand into an unbounded full-river mesh."""

    source = model_fixture()
    middle = source.cross_sections[0].model_copy(
        update={"id": "section-near", "code": "XS-NEAR", "chainage_m": 0.001}
    )
    model = source.model_copy(
        update={
            "cross_sections": (
                source.cross_sections[0],
                middle,
                source.cross_sections[1],
            )
        }
    )

    with pytest.raises(Hydraulic1DValidationError, match="MESH_DENSITY_UNSUPPORTED"):
        MascaretModelValidator().validate(model)


def test_output_interval_cannot_be_shorter_than_time_step() -> None:
    """Prevent output cadence rounding from silently changing the request."""

    with pytest.raises(ValueError, match="shorter than the time step"):
        SimulationSettings(
            duration_seconds=60.0,
            time_step_seconds=10.0,
            output_interval_seconds=1.0,
        )
