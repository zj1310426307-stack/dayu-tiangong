"""Contract tests for strict D-Flow FM history NetCDF parsing."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest

from model.hydraulic_1d import (
    BoundaryCondition,
    CrossSectionPoint,
    Hydraulic1DModel,
    HydraulicBranch,
    HydraulicCrossSection,
    InitialCondition,
    SimulationSettings,
    TimeValue,
)
from model.hydraulic_1d.dflow_fm.parser import DFlowFMResultParser
from model.hydraulic_1d.errors import Hydraulic1DResultError


pytestmark = pytest.mark.engineering_structure
np = pytest.importorskip("numpy")
xr = pytest.importorskip("xarray")


def _model() -> Hydraulic1DModel:
    profile = (
        CrossSectionPoint(station_m=0.0, elevation_m=4.0),
        CrossSectionPoint(station_m=4.0, elevation_m=0.0),
        CrossSectionPoint(station_m=16.0, elevation_m=0.0),
        CrossSectionPoint(station_m=20.0, elevation_m=4.0),
    )
    return Hydraulic1DModel(
        simulation_id="parse-01",
        scenario_id="contract",
        network_id="network-01",
        branches=(
            HydraulicBranch(
                id="branch-1",
                code="B1",
                upstream_node_id="node-up",
                downstream_node_id="node-down",
                start_chainage_m=0.0,
                end_chainage_m=100.0,
            ),
        ),
        cross_sections=(
            HydraulicCrossSection(
                id="section-a",
                branch_id="branch-1",
                code="A",
                chainage_m=0.0,
                vertical_datum="1985-national-height-datum",
                points=profile,
                manning_n=0.03,
            ),
            HydraulicCrossSection(
                id="section-b",
                branch_id="branch-1",
                code="B",
                chainage_m=100.0,
                vertical_datum="1985-national-height-datum",
                points=profile,
                manning_n=0.03,
            ),
        ),
        boundaries=(
            BoundaryCondition(
                id="upstream-q",
                branch_id="branch-1",
                location="upstream",
                variable="discharge",
                series=(TimeValue(time_seconds=0.0, value=10.0),),
            ),
            BoundaryCondition(
                id="downstream-h",
                branch_id="branch-1",
                location="downstream",
                variable="water_level",
                series=(TimeValue(time_seconds=0.0, value=2.0),),
            ),
        ),
        initial_condition=InitialCondition(water_level_m=2.0, discharge_m3s=0.0),
        settings=SimulationSettings(
            duration_seconds=120.0,
            time_step_seconds=10.0,
            output_interval_seconds=60.0,
        ),
    )


def _dataset() -> xr.Dataset:
    times = np.asarray([0.0, 60.0, 120.0])
    water_level = np.asarray(
        [
            [2.2, 2.1],
            [2.3, 2.2],
            [2.4, 2.3],
        ]
    )
    discharge = np.asarray(
        [
            [10.0, 20.0],
            [12.0, 22.0],
            [14.0, 24.0],
        ]
    )
    area = np.asarray(
        [
            [20.0, 25.0],
            [24.0, 27.5],
            [28.0, 30.0],
        ]
    )
    velocity = discharge / area
    return xr.Dataset(
        data_vars={
            # Deliberately use different location orders to prove ID-based mapping.
            "station_name": (("station",), np.asarray(["section-b", "section-a"])),
            "cross_section_name": (
                ("cross_section",),
                np.asarray(["section-a", "section-b"]),
            ),
            "waterlevel": (
                ("time", "station"),
                water_level,
                {"units": "m"},
            ),
            "cross_section_discharge": (
                ("time", "cross_section"),
                discharge,
                {"units": "m3 s-1"},
            ),
            "cross_section_area": (
                ("time", "cross_section"),
                area,
                {"units": "m2"},
            ),
            "cross_section_velocity": (
                ("time", "cross_section"),
                velocity,
                {"units": "m s-1"},
            ),
        },
        coords={
            "time": (
                ("time",),
                times,
                {"units": "seconds since 2020-01-01 00:00:00 +00:00"},
            )
        },
        attrs={"source": "synthetic audited D-Flow contract"},
    )


def _prepared(result_file: Path) -> SimpleNamespace:
    return SimpleNamespace(
        result_file=result_file,
        manifest_file=result_file.parent / "dayu-dflow-fm-manifest.json",
    )


def _write_netcdf_fixture_unicode_safe(dataset: xr.Dataset, destination: Path) -> None:
    """Write a real fixture through the same ASCII-only native path constraint."""

    from netCDF4 import Dataset

    relative_directory = Path("outputs") / "dflow-native-io" / uuid4().hex
    absolute_directory = Path.cwd() / relative_directory
    absolute_directory.mkdir(parents=True, exist_ok=False)
    relative_file = relative_directory / "fixture.nc"
    absolute_file = Path.cwd() / relative_file
    try:
        with Dataset(relative_file, mode="w") as target:
            for name, size in dataset.sizes.items():
                target.createDimension(name, int(size))
            for name, source in dataset.variables.items():
                values = source.values
                datatype = str if values.dtype.kind in {"U", "O"} else values.dtype
                variable = target.createVariable(name, datatype, source.dims)
                variable[:] = values.astype(object) if datatype is str else values
                for key, value in source.attrs.items():
                    variable.setncattr(key, value)
            for key, value in dataset.attrs.items():
                target.setncattr(key, value)
        absolute_file.replace(destination)
    finally:
        if absolute_file.exists():
            absolute_file.unlink()
        if absolute_directory.exists():
            absolute_directory.rmdir()


def test_parse_dataset_maps_exact_ids_and_returns_unified_rows(tmp_path: Path) -> None:
    result = DFlowFMResultParser().parse_dataset(
        _model(),
        _prepared(tmp_path / "dayu_his.nc"),
        _dataset(),
        runtime_seconds=1.25,
    )

    assert result.engine == "d-flow-fm"
    assert result.engine_version == "DIMRset_2026.02"
    assert len(result.records) == 6
    assert result.artifacts == ()
    first = result.records[0]
    assert first.cross_section_id == "section-a"
    assert first.timestamp == pytest.approx(0.0)
    assert first.water_level_m == pytest.approx(2.1)
    assert first.discharge_m3s == pytest.approx(10.0)
    assert first.flow_area_m2 == pytest.approx(20.0)
    assert first.velocity_m_s == pytest.approx(0.5)
    assert first.depth_m == pytest.approx(2.1)
    assert result.diagnostics["native_source"] == "synthetic audited D-Flow contract"
    assert result.diagnostics["native_engine_version"] == "1.2.184"


def test_real_xarray_netcdf_open_contract(tmp_path: Path) -> None:
    result_file = tmp_path / "dayu_his.nc"
    _write_netcdf_fixture_unicode_safe(_dataset(), result_file)

    result = DFlowFMResultParser().parse(
        _model(),
        _prepared(result_file),
        runtime_seconds=2.5,
    )

    assert len(result.records) == 6
    assert result.diagnostics["runtime_seconds"] == pytest.approx(2.5)


@pytest.mark.parametrize(
    ("mutation", "expected_code"),
    (
        ("missing-variable", "DFLOW_RESULT_VARIABLE_MISSING"),
        ("wrong-unit", "DFLOW_RESULT_UNIT_INVALID"),
        ("wrong-time", "DFLOW_RESULT_TIME_AXIS_INVALID"),
        ("non-finite", "DFLOW_RESULT_CORRUPT"),
        ("duplicate-id", "DFLOW_RESULT_LOCATION_DUPLICATE"),
        ("unexpected-id", "DFLOW_RESULT_LOCATION_UNEXPECTED"),
        ("flow-identity", "DFLOW_RESULT_FLOW_IDENTITY_INVALID"),
    ),
)
def test_parse_dataset_fails_closed(
    tmp_path: Path,
    mutation: str,
    expected_code: str,
) -> None:
    dataset = _dataset()
    if mutation == "missing-variable":
        dataset = dataset.drop_vars("cross_section_area")
    elif mutation == "wrong-unit":
        dataset["waterlevel"].attrs["units"] = "cm"
    elif mutation == "wrong-time":
        dataset = dataset.assign_coords(
            time=(
                ("time",),
                np.asarray([0.0, 30.0, 120.0]),
                {"units": "seconds since 2020-01-01 00:00:00 +00:00"},
            )
        )
    elif mutation == "non-finite":
        dataset["cross_section_discharge"].values[0, 0] = np.nan
    elif mutation == "duplicate-id":
        dataset["station_name"].values[:] = ["section-a", "section-a"]
    elif mutation == "unexpected-id":
        water_level = dataset["waterlevel"].values
        dataset = dataset.drop_vars(("station_name", "waterlevel"))
        dataset["station_name"] = (
            ("station",),
            np.asarray(["section-b", "section-a", "not-a-dayu-section"]),
        )
        dataset["waterlevel"] = (
            ("time", "station"),
            np.column_stack((water_level, water_level[:, 0])),
            {"units": "m"},
        )
    elif mutation == "flow-identity":
        dataset["cross_section_velocity"].values[0, 0] = 99.0
    else:  # pragma: no cover - keeps additions to the table explicit.
        raise AssertionError(mutation)

    with pytest.raises(Hydraulic1DResultError) as error:
        DFlowFMResultParser().parse_dataset(
            _model(),
            _prepared(tmp_path / "dayu_his.nc"),
            dataset,
            runtime_seconds=1.0,
        )

    assert error.value.code == expected_code


def test_missing_and_corrupt_netcdf_fail_closed(tmp_path: Path) -> None:
    parser = DFlowFMResultParser()
    missing = tmp_path / "missing.nc"
    with pytest.raises(Hydraulic1DResultError) as missing_error:
        parser.parse(_model(), _prepared(missing), runtime_seconds=0.0)
    assert missing_error.value.code == "DFLOW_RESULT_MISSING"

    corrupt = tmp_path / "corrupt.nc"
    corrupt.write_bytes(b"not a NetCDF file")
    with pytest.raises(Hydraulic1DResultError) as corrupt_error:
        parser.parse(_model(), _prepared(corrupt), runtime_seconds=0.0)
    assert corrupt_error.value.code == "DFLOW_RESULT_CORRUPT"
