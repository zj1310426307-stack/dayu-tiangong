"""Verify the strict Dayu-to-D-Flow FM base 1D adapter."""

from __future__ import annotations

from importlib.util import find_spec
from json import loads
from pathlib import Path

import pytest

from model.hydraulic_1d import (
    BoundaryCondition,
    CrossSectionPoint,
    Hydraulic1DModel,
    HydraulicBranch,
    HydraulicCrossSection,
    HydraulicNode,
    HydraulicStructure,
    InitialCondition,
    RoughnessZone,
    SimulationSettings,
    TimeValue,
)
from model.hydraulic_1d.dflow_fm.adapter import (
    DFlowFMModelBuilder,
    DFlowFMModelValidator,
)
from model.hydraulic_1d.errors import Hydraulic1DValidationError
from model.hydraulic_1d.dflow_fm.workspace import DFlowJobWorkspace
from model.hydraulic_1d.structures import (
    GateHydraulicSpec,
    SourcedHydraulicScalar,
    StructureFlowDirection,
)


pytestmark = pytest.mark.engineering_structure
HYDROLIB_AVAILABLE = find_spec("hydrolib") is not None
HYDROLIB_SKIP_REASON = "HYDROLIB-core 1.0.1 is not installed"


def dflow_model(*, discharge_m3s: float = 0.0, zoned: bool = False) -> Hydraulic1DModel:
    """Build one explicitly georeferenced 1D branch with nonzero Dayu chainage origin."""

    points = (
        CrossSectionPoint(station_m=0.0, elevation_m=4.0),
        CrossSectionPoint(station_m=4.0, elevation_m=0.0),
        CrossSectionPoint(station_m=16.0, elevation_m=0.0),
        CrossSectionPoint(station_m=20.0, elevation_m=4.0),
    )
    roughness = (
        (
            RoughnessZone(start_station_m=0.0, end_station_m=8.0, manning_n=0.04),
            RoughnessZone(start_station_m=8.0, end_station_m=20.0, manning_n=0.03),
        )
        if zoned
        else ()
    )
    sections = tuple(
        HydraulicCrossSection(
            id=section_id,
            branch_id="branch-1",
            code=section_id.upper(),
            chainage_m=chainage,
            vertical_datum="1985-national-height-datum",
            points=points,
            manning_n=0.03,
            roughness_zones=roughness,
        )
        for section_id, chainage in (
            ("section-up", 100.0),
            ("section-mid", 600.0),
            ("section-down", 1100.0),
        )
    )
    return Hydraulic1DModel(
        simulation_id="df01",
        scenario_id="base-flow",
        network_id="network-df01",
        nodes=(
            HydraulicNode(
                id="node-up",
                code="N-UP",
                node_type="boundary",
                location_geometry={"type": "Point", "coordinates": [120.0, 30.0]},
            ),
            HydraulicNode(
                id="node-down",
                code="N-DOWN",
                node_type="boundary",
                location_geometry={"type": "Point", "coordinates": [120.01, 30.0]},
            ),
        ),
        branches=(
            HydraulicBranch(
                id="branch-1",
                code="B1",
                upstream_node_id="node-up",
                downstream_node_id="node-down",
                start_chainage_m=100.0,
                end_chainage_m=1100.0,
            ),
        ),
        cross_sections=sections,
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
        initial_condition=InitialCondition(
            water_level_m=2.0,
            discharge_m3s=discharge_m3s,
        ),
        settings=SimulationSettings(
            duration_seconds=600.0,
            time_step_seconds=10.0,
            output_interval_seconds=60.0,
        ),
        metadata={
            "engineering_crs": "EPSG:4547",
            "horizontal_unit": "m",
            "vertical_unit": "m",
            "vertical_datum": "1985-national-height-datum",
            "dflow_fm": {
                "coordinate_reference_system": "EPSG:4547",
                "mesh_edge_length_m": 100.0,
                "node_coordinates": {
                    "node-up": [0.0, 0.0],
                    "node-down": [1000.0, 0.0],
                },
                "branch_geometries": {
                    "branch-1": {
                        "type": "LineString",
                        "coordinates": [[0.0, 0.0], [400.0, 0.0], [1000.0, 0.0]],
                    }
                },
            },
        },
    )


def _vertical_gate() -> GateHydraulicSpec:
    def synthetic(value: float) -> SourcedHydraulicScalar:
        return SourcedHydraulicScalar.synthetic(
            value,
            "synthetic adapter integration fixture",
        )

    return GateHydraulicSpec(
        structure_id="gate-1",
        name="Synthetic vertical gate",
        branch_id="branch-1",
        chainage_m=500.0,
        gate_subtype="vertical_underflow_gate",
        crest_level_m=synthetic(2.0),
        crest_width_m=synthetic(3.5),
        opening_m=synthetic(0.4),
        maximum_opening_m=synthetic(1.2),
        allowed_flow_direction=StructureFlowDirection.BOTH,
        use_velocity_height=False,
        correction_coefficient=synthetic(0.61),
        maximum_opening_axis="vertical",
    )


def test_nonzero_initial_discharge_fails_without_velocity_guess() -> None:
    """Do not convert Dayu Q into an unaudited D-Flow initial velocity field."""

    with pytest.raises(Hydraulic1DValidationError) as error:
        DFlowFMModelValidator().validate(
            dflow_model(discharge_m3s=10.0),
            gate_specs=(),
            pump_specs=(),
        )

    assert error.value.code == "DFLOW_INITIAL_DISCHARGE_UNSUPPORTED"


def test_missing_branch_linestring_fails_closed() -> None:
    """Require authoritative branch geometry instead of drawing endpoint chords."""

    source = dflow_model()
    metadata = dict(source.metadata)
    dflow_metadata = dict(metadata["dflow_fm"])
    dflow_metadata.pop("branch_geometries")
    metadata["dflow_fm"] = dflow_metadata

    with pytest.raises(Hydraulic1DValidationError) as error:
        DFlowFMModelValidator().validate(
            source.model_copy(update={"metadata": metadata}),
            gate_specs=(),
            pump_specs=(),
        )

    assert error.value.code == "DFLOW_BRANCH_GEOMETRY_REQUIRED"


def test_native_coordinates_must_match_the_declared_engineering_crs() -> None:
    """Never reinterpret display-CRS node geometry as projected solver coordinates."""

    source = dflow_model()
    metadata = dict(source.metadata)
    dflow_metadata = dict(metadata["dflow_fm"])
    dflow_metadata["coordinate_reference_system"] = "EPSG:4490"
    metadata["dflow_fm"] = dflow_metadata

    with pytest.raises(Hydraulic1DValidationError) as error:
        DFlowFMModelValidator().validate_base(
            source.model_copy(update={"metadata": metadata})
        )

    assert error.value.code == "DFLOW_COORDINATE_CRS_MISMATCH"


def test_base_validation_defers_dispatch_owned_structure_specs() -> None:
    """Allow ordinary engine validation before dispatch freezes hydraulic specs."""

    source = dflow_model()
    model = source.model_copy(
        update={
            "structures": (
                HydraulicStructure(
                    id="gate-1",
                    name="Synthetic gate",
                    branch_id="branch-1",
                    kind="gate",
                    chainage_m=500.0,
                ),
            )
        }
    )
    validator = DFlowFMModelValidator()

    validator.validate_base(model)
    with pytest.raises(Hydraulic1DValidationError) as error:
        validator.validate(model, gate_specs=(), pump_specs=())

    assert error.value.code == "DFLOW_STRUCTURE_SPEC_SET_INVALID"


@pytest.mark.skipif(not HYDROLIB_AVAILABLE, reason=HYDROLIB_SKIP_REASON)
def test_typed_hydrolib_case_and_dimr_roundtrip(tmp_path: Path) -> None:
    """Save/load the full DF01 input graph and top-level DIMR configuration."""

    job_workspace = DFlowJobWorkspace.create(
        tmp_path / "jobs",
        simulation_id="df01",
        job_id="base-flow",
    )
    workspace = job_workspace.path
    prepared = DFlowFMModelBuilder().build(dflow_model(zoned=True), job_workspace)

    assert prepared.workspace == workspace
    assert prepared.job_workspace == job_workspace
    assert prepared.dimr_config_file.parent == job_workspace.control_dir
    assert prepared.case_file.parent == job_workspace.input_dir
    assert prepared.dimr_config_file.is_file()
    assert prepared.case_file.is_file()
    assert prepared.network_file.is_file()
    assert prepared.cross_definition_file.is_file()
    assert prepared.cross_location_file.is_file()
    assert prepared.roughness_file.is_file()
    assert prepared.forcing_file.is_file()
    assert prepared.external_forcing_file.is_file()
    assert prepared.observation_file.is_file()
    assert prepared.observation_cross_section_file.is_file()
    assert prepared.structure_file is None
    assert prepared.result_file == workspace / "output" / "dayu_his.nc"
    assert prepared.manifest_file.parent == job_workspace.metadata_dir

    from hydrolib.core.dflowfm.bc.models import ForcingModel
    from hydrolib.core.dflowfm.crosssection.models import CrossDefModel, CrossLocModel
    from hydrolib.core.dflowfm.friction.models import FrictionModel
    from hydrolib.core.dflowfm.mdu.models import FMModel
    from hydrolib.core.dimr.models import DIMR, Start

    dimr = DIMR(prepared.dimr_config_file, recurse=False)
    assert len(dimr.component) == 1
    assert dimr.component[0].library == "dflowfm"
    assert dimr.component[0].workingDir == Path("input")
    assert dimr.component[0].inputFile == Path("dayu.mdu")
    assert isinstance(dimr.control[0], Start)
    assert dimr.control[0].name == "dflowfm"

    native = FMModel(prepared.case_file, recurse=False)
    assert native.time.tunit == "S"
    assert native.time.dtmax == pytest.approx(10.0)
    assert native.time.tstop == pytest.approx(600.0)
    assert native.geometry.waterlevini == pytest.approx(2.0)
    assert native.output.outputdir == Path("../output")
    assert native.output.hisinterval == pytest.approx([60.0, 0.0, 600.0])
    assert native.output.mapinterval == pytest.approx([0.0])

    network = prepared.native_network_model._mesh1d
    assert list(network.network1d_branch_id) == ["branch-1"]
    assert set(network.network1d_node_id) == {"node-up", "node-down"}
    assert any(
        value == pytest.approx(500.0) for value in network.mesh1d_node_branch_offset
    )
    assert (
        max(
            right - left
            for left, right in zip(
                network.mesh1d_node_branch_offset,
                network.mesh1d_node_branch_offset[1:],
            )
        )
        <= 100.0 + 1e-9
    )

    definitions = CrossDefModel(prepared.cross_definition_file).definition
    assert len(definitions) == 3
    assert definitions[0].type == "yz"
    assert definitions[0].frictiontypes is None
    assert len(definitions[0].frictionids) == 2
    assert definitions[0].frictionpositions == pytest.approx([0.0, 8.0, 20.0])
    roughness = FrictionModel(prepared.roughness_file).global_
    assert len(roughness) == 6
    assert {item.frictiontype for item in roughness} == {"Manning"}
    assert [item.frictionvalue for item in roughness[:2]] == pytest.approx([0.04, 0.03])
    locations = CrossLocModel(prepared.cross_location_file).crosssection
    assert [item.chainage for item in locations] == pytest.approx([0.0, 500.0, 1000.0])

    forcing = ForcingModel(prepared.forcing_file)
    assert {item.name for item in forcing.forcing} == {"node-up", "node-down"}
    assert all(len(item.datablock) == 2 for item in forcing.forcing)
    assert all(
        item.datablock[-1][0] == pytest.approx(600.0) for item in forcing.forcing
    )

    manifest = loads(prepared.manifest_file.read_text(encoding="ascii"))
    assert manifest["engine_version"] == "DIMRset_2026.02"
    assert manifest["native_engine_version"] == "1.2.184"
    assert manifest["top_level_runtime"] == {
        "component": "dflowfm",
        "component_working_directory": "input",
        "config": "control/dimr_config.xml",
        "direct_dflowfm_launch_allowed": False,
        "launcher": "dimr",
    }
    assert manifest["coordinate_reference_system"] == "EPSG:4547"
    assert manifest["branches"][0]["native_chainage_offset_m"] == -100.0
    assert manifest["cross_sections"][1]["native_chainage_m"] == 500.0
    assert all(len(item["sha256"]) == 64 for item in manifest["artifacts"])
    assert {item["path"] for item in manifest["artifacts"]} >= {
        "control/dimr_config.xml",
        "input/dayu.mdu",
        "input/roughness.ini",
    }


@pytest.mark.skipif(not HYDROLIB_AVAILABLE, reason=HYDROLIB_SKIP_REASON)
def test_typed_case_supports_unicode_engineering_workspace(tmp_path: Path) -> None:
    """Keep native NetCDF I/O inside a Chinese-named project directory."""

    job_workspace = DFlowJobWorkspace.create(
        tmp_path / "大禹天工" / "验证记录",
        simulation_id="df01",
        job_id="unicode-path",
    )

    prepared = DFlowFMModelBuilder().build(dflow_model(), job_workspace)

    assert prepared.network_file.is_file()
    assert prepared.network_file.stat().st_size > 0
    assert prepared.case_file.is_file()
    assert "netfile" in prepared.case_file.read_text(encoding="utf-8").lower()


@pytest.mark.skipif(not HYDROLIB_AVAILABLE, reason=HYDROLIB_SKIP_REASON)
def test_builder_delegates_gate_mapping_and_localizes_chainage(tmp_path: Path) -> None:
    """Include a typed mapped Gate at its branch-local D-Flow mesh anchor."""

    source = dflow_model()
    model = source.model_copy(
        update={
            "structures": (
                HydraulicStructure(
                    id="gate-1",
                    name="Synthetic vertical gate",
                    branch_id="branch-1",
                    kind="gate",
                    chainage_m=500.0,
                ),
            )
        }
    )
    workspace = DFlowJobWorkspace.create(
        tmp_path / "jobs",
        simulation_id="df01",
        job_id="gate",
    )

    prepared = DFlowFMModelBuilder().build(
        model,
        workspace,
        gate_specs=(_vertical_gate(),),
    )

    from hydrolib.core.dflowfm.structure.models import StructureModel

    assert prepared.structure_file is not None
    assert prepared.structure_file.parent == workspace.input_dir
    native = StructureModel(prepared.structure_file).structure
    assert len(native) == 1
    assert native[0].id == "gate-1"
    assert native[0].branchid == "branch-1"
    assert native[0].chainage == pytest.approx(400.0)
    mesh = prepared.native_network_model._mesh1d
    assert any(
        value == pytest.approx(400.0) for value in mesh.mesh1d_node_branch_offset
    )
