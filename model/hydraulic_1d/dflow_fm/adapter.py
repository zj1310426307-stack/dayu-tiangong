"""Build a strict D-Flow FM 1D case from the solver-neutral Dayu model.

The adapter deliberately uses the typed HYDROLIB-core 1.0.1 models for every
native network, INI, boundary, and MDU artifact.  It does not make geometric or
hydraulic guesses: D-Flow branch geometry and mesh spacing are explicit adapter
metadata, and engine semantics without an audited equivalent fail closed.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from hashlib import sha256
from importlib import metadata
from json import dumps
from math import ceil, hypot, isclose, isfinite
from pathlib import Path
from re import fullmatch
from typing import Any, Iterable, Mapping, NoReturn, Sequence

from model.hydraulic_1d.contracts import (
    BoundaryCondition,
    Hydraulic1DModel,
    HydraulicBranch,
    HydraulicCrossSection,
    HydraulicNode,
)
from model.hydraulic_1d.dflow_fm.config import DFLOW_NATIVE_VERSION
from model.hydraulic_1d.dflow_fm.structures import (
    DFlowFMStructureMapper,
    HYDROLIB_CORE_REQUIRED_VERSION,
)
from model.hydraulic_1d.dflow_fm.workspace import DFlowJobWorkspace
from model.hydraulic_1d.errors import (
    Hydraulic1DExecutionError,
    Hydraulic1DRuntimeUnavailable,
    Hydraulic1DValidationError,
)
from model.hydraulic_1d.network import HydraulicNetworkGraph, HydraulicNetworkValidator
from model.hydraulic_1d.registry import DFLOW_FM_ENGINE_ID, DFLOW_FM_ENGINE_VERSION
from model.hydraulic_1d.structures import GateHydraulicSpec, PumpHydraulicSpec


DFLOW_ENGINE_ID = DFLOW_FM_ENGINE_ID
DFLOW_ENGINE_VERSION = DFLOW_FM_ENGINE_VERSION
CASE_FILENAME = "dayu.mdu"
NETWORK_FILENAME = "dayu_net.nc"
CROSS_DEF_FILENAME = "crossdef.ini"
CROSS_LOC_FILENAME = "crossloc.ini"
ROUGHNESS_FILENAME = "roughness.ini"
FORCING_FILENAME = "boundaries.bc"
EXTERNAL_FORCING_FILENAME = "boundaries.ext"
OBSERVATION_FILENAME = "dayu-observations.ini"
OBSERVATION_CROSS_SECTION_FILENAME = "dayu-observation-cross-sections.ini"
STRUCTURE_FILENAME = "structures.ini"
MANIFEST_FILENAME = "dayu-dflow-fm-manifest.json"
DIMR_FILENAME = "dimr_config.xml"
OUTPUT_DIRECTORY = "output"
RESULT_FILENAME = "dayu_his.nc"
DFLOW_REFERENCE_DATE = 20200101
DFLOW_TIME_UNIT = "seconds since 2020-01-01 00:00:00"
_NATIVE_NETWORK_ID_LIMIT = 40
_NATIVE_SAFE_ID = r"[A-Za-z0-9][A-Za-z0-9_.-]*"


def _new_file_model(model: Any, filepath: Path) -> Any:
    """Assign a target to a new HYDROLIB model without asking it to load first."""

    model.filepath = filepath
    return model


@dataclass(frozen=True, slots=True)
class DFlowFMPreparedCase:
    """Identify the typed source artifacts and expected D-Flow history result."""

    workspace: Path
    job_workspace: DFlowJobWorkspace
    dimr_config_file: Path
    case_file: Path
    network_file: Path
    cross_definition_file: Path
    cross_location_file: Path
    roughness_file: Path
    forcing_file: Path
    external_forcing_file: Path
    observation_file: Path
    observation_cross_section_file: Path
    structure_file: Path | None
    manifest_file: Path
    result_file: Path
    native_model: Any
    native_dimr_model: Any


@dataclass(frozen=True, slots=True)
class _HydrolibTypes:
    """Keep the pinned optional dependency behind one import boundary."""

    np: Any
    branch: type[Any]
    network: type[Any]
    network_model: type[Any]
    yz_cross_section: type[Any]
    cross_section: type[Any]
    cross_def_model: type[Any]
    cross_loc_model: type[Any]
    friction_global: type[Any]
    friction_model: type[Any]
    quantity_unit_pair: type[Any]
    time_series: type[Any]
    forcing_model: type[Any]
    boundary: type[Any]
    ext_model: type[Any]
    observation_point: type[Any]
    observation_point_model: type[Any]
    observation_cross_section: type[Any]
    observation_cross_section_model: type[Any]
    structure_model: type[Any]
    geometry: type[Any]
    time: type[Any]
    output: type[Any]
    external_forcing: type[Any]
    fm_model: type[Any]
    dimr: type[Any]
    dimr_documentation: type[Any]
    fm_component: type[Any]
    dimr_start: type[Any]


def _load_hydrolib_types() -> _HydrolibTypes:
    """Load exactly HYDROLIB-core 1.0.1 and reject absent or drifting installs."""

    try:
        installed_version = metadata.version("hydrolib-core")
    except metadata.PackageNotFoundError as exc:
        raise Hydraulic1DRuntimeUnavailable(
            "HYDROLIB-core 1.0.1 is required to build D-Flow FM cases",
            code="DFLOW_HYDROLIB_CORE_NOT_AVAILABLE",
        ) from exc
    if installed_version != HYDROLIB_CORE_REQUIRED_VERSION:
        raise Hydraulic1DRuntimeUnavailable(
            (
                "D-Flow FM adapter is locked to HYDROLIB-core "
                f"{HYDROLIB_CORE_REQUIRED_VERSION}, found {installed_version}"
            ),
            code="DFLOW_HYDROLIB_CORE_VERSION_MISMATCH",
        )
    try:
        import numpy as np
        from hydrolib.core.dflowfm.bc.models import (
            ForcingModel,
            QuantityUnitPair,
            TimeSeries,
        )
        from hydrolib.core.dflowfm.crosssection.models import (
            CrossDefModel,
            CrossLocModel,
            CrossSection,
            YZCrsDef,
        )
        from hydrolib.core.dflowfm.ext.models import Boundary, ExtModel
        from hydrolib.core.dflowfm.friction.models import FrictGlobal, FrictionModel
        from hydrolib.core.dflowfm.mdu.models import (
            ExternalForcing,
            FMModel,
            Geometry,
            Output,
            Time,
        )
        from hydrolib.core.dflowfm.net.models import (
            Branch,
            Network,
            NetworkModel,
        )
        from hydrolib.core.dflowfm.obs.models import (
            ObservationPoint,
            ObservationPointModel,
        )
        from hydrolib.core.dflowfm.obscrosssection.models import (
            ObservationCrossSection,
            ObservationCrossSectionModel,
        )
        from hydrolib.core.dflowfm.structure.models import StructureModel
        from hydrolib.core.dimr.models import (
            DIMR,
            Documentation,
            FMComponent,
            Start,
        )
    except ImportError as exc:
        raise Hydraulic1DRuntimeUnavailable(
            "HYDROLIB-core 1.0.1 dependencies could not be imported",
            code="DFLOW_HYDROLIB_CORE_NOT_AVAILABLE",
        ) from exc
    return _HydrolibTypes(
        np=np,
        branch=Branch,
        network=Network,
        network_model=NetworkModel,
        yz_cross_section=YZCrsDef,
        cross_section=CrossSection,
        cross_def_model=CrossDefModel,
        cross_loc_model=CrossLocModel,
        friction_global=FrictGlobal,
        friction_model=FrictionModel,
        quantity_unit_pair=QuantityUnitPair,
        time_series=TimeSeries,
        forcing_model=ForcingModel,
        boundary=Boundary,
        ext_model=ExtModel,
        observation_point=ObservationPoint,
        observation_point_model=ObservationPointModel,
        observation_cross_section=ObservationCrossSection,
        observation_cross_section_model=ObservationCrossSectionModel,
        structure_model=StructureModel,
        geometry=Geometry,
        time=Time,
        output=Output,
        external_forcing=ExternalForcing,
        fm_model=FMModel,
        dimr=DIMR,
        dimr_documentation=Documentation,
        fm_component=FMComponent,
        dimr_start=Start,
    )


class DFlowFMModelValidator:
    """Validate only the audited base-1D subset before native model creation."""

    def validate_base(self, model: Hydraulic1DModel) -> HydraulicNetworkGraph:
        """Validate solver-neutral 1D inputs without requiring dispatch-owned specs."""

        graph = HydraulicNetworkValidator().validate(model)
        if not model.nodes:
            self._reject(
                "DFLOW_NODE_GEOMETRY_REQUIRED",
                "D-Flow mapping requires explicit Dayu network nodes",
                "nodes",
            )
        referenced_nodes = {
            value
            for branch in model.branches
            for value in (branch.upstream_node_id, branch.downstream_node_id)
        }
        explicit_nodes = {node.id for node in model.nodes}
        if referenced_nodes != explicit_nodes:
            self._reject(
                "DFLOW_NODE_SET_INVALID",
                "explicit Dayu nodes must exactly cover every referenced branch endpoint",
                "nodes",
            )
        self._validate_coordinate_reference_system(model)
        coordinates = self._node_coordinates(model)
        for index, node in enumerate(model.nodes):
            self.node_xy(
                model,
                node,
                field_path=f"metadata.dflow_fm.node_coordinates.{node.id}",
            )
            self._validate_native_network_id(node.id, f"nodes[{index}].id")
        if set(coordinates) != explicit_nodes:
            self._reject(
                "DFLOW_NODE_COORDINATE_SET_INVALID",
                "dflow_fm.node_coordinates must exactly cover every Dayu node id",
                "metadata.dflow_fm.node_coordinates",
            )
        for index, branch in enumerate(model.branches):
            self._validate_native_network_id(branch.id, f"branches[{index}].id")
            self.branch_coordinates(model, branch, field_path=f"branches[{index}]")
        branch_geometries = self._metadata(model).get("branch_geometries")
        if not isinstance(branch_geometries, Mapping):
            self._reject(
                "DFLOW_BRANCH_GEOMETRY_REQUIRED",
                "dflow_fm.branch_geometries must be an object",
                "metadata.dflow_fm.branch_geometries",
            )
        if set(branch_geometries) != {item.id for item in model.branches}:
            self._reject(
                "DFLOW_BRANCH_GEOMETRY_SET_INVALID",
                "dflow_fm.branch_geometries must exactly cover every Dayu branch id",
                "metadata.dflow_fm.branch_geometries",
            )
        self.mesh_edge_length(model)
        self._validate_sections(model)
        self._validate_boundaries(model)
        self._validate_initial_condition(model)
        self._validate_time(model)
        return graph

    def validate(
        self,
        model: Hydraulic1DModel,
        *,
        gate_specs: Sequence[GateHydraulicSpec],
        pump_specs: Sequence[PumpHydraulicSpec],
    ) -> HydraulicNetworkGraph:
        """Reject topology, coordinates, boundaries, and initial-state drift."""

        graph = self.validate_base(model)
        self._validate_structures(model, gate_specs=gate_specs, pump_specs=pump_specs)
        return graph

    @staticmethod
    def _metadata(model: Hydraulic1DModel) -> Mapping[str, Any]:
        value = model.metadata.get("dflow_fm")
        if not isinstance(value, Mapping):
            raise Hydraulic1DValidationError(
                "DFLOW_ADAPTER_METADATA_REQUIRED",
                "model.metadata.dflow_fm must be an object",
                field_path="metadata.dflow_fm",
            )
        return value

    def mesh_edge_length(self, model: Hydraulic1DModel) -> float:
        """Return the explicit maximum 1D mesh edge length in metres."""

        value = self._metadata(model).get("mesh_edge_length_m")
        if (
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not isfinite(float(value))
        ):
            self._reject(
                "DFLOW_MESH_SPACING_REQUIRED",
                "dflow_fm.mesh_edge_length_m must be a finite positive number",
                "metadata.dflow_fm.mesh_edge_length_m",
            )
        result = float(value)
        if result <= 0.0:
            self._reject(
                "DFLOW_MESH_SPACING_REQUIRED",
                "dflow_fm.mesh_edge_length_m must be greater than zero",
                "metadata.dflow_fm.mesh_edge_length_m",
            )
        return result

    def _validate_coordinate_reference_system(self, model: Hydraulic1DModel) -> None:
        """Bind every native coordinate to the declared engineering CRS."""

        engineering_crs = model.metadata.get("engineering_crs")
        native_crs = self._metadata(model).get("coordinate_reference_system")
        if not isinstance(engineering_crs, str) or not engineering_crs.strip():
            self._reject(
                "DFLOW_ENGINEERING_CRS_REQUIRED",
                "metadata.engineering_crs must identify the projected engineering CRS",
                "metadata.engineering_crs",
            )
        if native_crs != engineering_crs:
            self._reject(
                "DFLOW_COORDINATE_CRS_MISMATCH",
                (
                    "dflow_fm.coordinate_reference_system must exactly match "
                    "metadata.engineering_crs"
                ),
                "metadata.dflow_fm.coordinate_reference_system",
            )

    def _node_coordinates(self, model: Hydraulic1DModel) -> Mapping[str, Any]:
        coordinates = self._metadata(model).get("node_coordinates")
        if not isinstance(coordinates, Mapping):
            self._reject(
                "DFLOW_NODE_COORDINATES_REQUIRED",
                (
                    "dflow_fm.node_coordinates must map every node id to projected "
                    "engineering-CRS coordinates"
                ),
                "metadata.dflow_fm.node_coordinates",
            )
        return coordinates

    def node_xy(
        self,
        model: Hydraulic1DModel,
        node: HydraulicNode,
        *,
        field_path: str,
    ) -> tuple[float, float]:
        """Read explicit projected coordinates without using display geometry."""

        coordinates = self._node_coordinates(model).get(node.id)
        if (
            not isinstance(coordinates, (list, tuple))
            or len(coordinates) != 2
            or any(
                isinstance(item, bool) or not isinstance(item, (int, float))
                for item in coordinates
            )
        ):
            raise Hydraulic1DValidationError(
                "DFLOW_NODE_GEOMETRY_INVALID",
                f"node {node.id} requires exactly two projected numeric coordinates",
                field_path=field_path,
            )
        x, y = float(coordinates[0]), float(coordinates[1])
        if not isfinite(x) or not isfinite(y):
            raise Hydraulic1DValidationError(
                "DFLOW_NODE_GEOMETRY_INVALID",
                f"node {node.id} coordinates must be finite",
                field_path=field_path,
            )
        return x, y

    def branch_coordinates(
        self,
        model: Hydraulic1DModel,
        branch: HydraulicBranch,
        *,
        field_path: str,
    ) -> tuple[tuple[float, float], ...]:
        """Resolve one explicit LineString and prove its direction and chainage length."""

        geometries = self._metadata(model).get("branch_geometries")
        if not isinstance(geometries, Mapping):
            self._reject(
                "DFLOW_BRANCH_GEOMETRY_REQUIRED",
                "dflow_fm.branch_geometries must map every branch id to a LineString",
                "metadata.dflow_fm.branch_geometries",
            )
        geometry = geometries.get(branch.id)
        if not isinstance(geometry, Mapping) or geometry.get("type") != "LineString":
            self._reject(
                "DFLOW_BRANCH_GEOMETRY_REQUIRED",
                f"branch {branch.id} requires an explicit GeoJSON LineString",
                f"{field_path}.geometry",
            )
        raw_coordinates = geometry.get("coordinates")
        if not isinstance(raw_coordinates, (list, tuple)) or len(raw_coordinates) < 2:
            self._reject(
                "DFLOW_BRANCH_GEOMETRY_INVALID",
                f"branch {branch.id} LineString requires at least two points",
                f"{field_path}.geometry.coordinates",
            )
        coordinates: list[tuple[float, float]] = []
        for point in raw_coordinates:
            if (
                not isinstance(point, (list, tuple))
                or len(point) != 2
                or any(
                    isinstance(item, bool) or not isinstance(item, (int, float))
                    for item in point
                )
            ):
                self._reject(
                    "DFLOW_BRANCH_GEOMETRY_INVALID",
                    f"branch {branch.id} has a non-XY coordinate",
                    f"{field_path}.geometry.coordinates",
                )
            coordinate = float(point[0]), float(point[1])
            if not all(isfinite(value) for value in coordinate):
                self._reject(
                    "DFLOW_BRANCH_GEOMETRY_INVALID",
                    f"branch {branch.id} has non-finite coordinates",
                    f"{field_path}.geometry.coordinates",
                )
            coordinates.append(coordinate)
        node_map = {node.id: node for node in model.nodes}
        upstream_xy = self.node_xy(
            model,
            node_map[branch.upstream_node_id],
            field_path=(
                f"metadata.dflow_fm.node_coordinates.{branch.upstream_node_id}"
            ),
        )
        downstream_xy = self.node_xy(
            model,
            node_map[branch.downstream_node_id],
            field_path=(
                f"metadata.dflow_fm.node_coordinates.{branch.downstream_node_id}"
            ),
        )
        if coordinates[0] != upstream_xy or coordinates[-1] != downstream_xy:
            self._reject(
                "DFLOW_BRANCH_DIRECTION_MISMATCH",
                (
                    f"branch {branch.id} LineString must start at its upstream node "
                    "and end at its downstream node"
                ),
                f"{field_path}.geometry",
            )
        geometric_length = sum(
            hypot(right[0] - left[0], right[1] - left[1])
            for left, right in zip(coordinates, coordinates[1:])
        )
        chainage_length = float(branch.end_chainage_m - branch.start_chainage_m)
        tolerance = max(1e-6, chainage_length * 1e-9)
        if not isclose(
            geometric_length,
            chainage_length,
            rel_tol=0.0,
            abs_tol=tolerance,
        ):
            self._reject(
                "DFLOW_BRANCH_CHAINAGE_GEOMETRY_MISMATCH",
                (
                    f"branch {branch.id} geometry length {geometric_length:g} m does "
                    f"not equal its chainage span {chainage_length:g} m"
                ),
                f"{field_path}.geometry",
            )
        return tuple(coordinates)

    def _validate_sections(self, model: Hydraulic1DModel) -> None:
        vertical_datum = str(model.metadata.get("vertical_datum", "")).strip()
        if not vertical_datum or vertical_datum.lower() == "unknown":
            self._reject(
                "DFLOW_VERTICAL_DATUM_INVALID",
                "a confirmed Network vertical datum is required",
                "metadata.vertical_datum",
            )
        if (
            model.metadata.get("horizontal_unit") != "m"
            or model.metadata.get("vertical_unit") != "m"
        ):
            self._reject(
                "DFLOW_NON_SI_UNITS_UNSUPPORTED",
                "horizontal and vertical units must both be metres",
                "metadata",
            )
        for index, section in enumerate(model.cross_sections):
            self._validate_native_network_id(
                section.id,
                f"cross_sections[{index}].id",
            )
            if section.vertical_datum != vertical_datum:
                self._reject(
                    "DFLOW_VERTICAL_DATUM_INVALID",
                    f"cross section {section.id} has a different vertical datum",
                    f"cross_sections[{index}].vertical_datum",
                )
            self.roughness_values(section, field_path=f"cross_sections[{index}]")

    def roughness_values(
        self,
        section: HydraulicCrossSection,
        *,
        field_path: str,
    ) -> tuple[tuple[float, ...] | None, tuple[float, ...]]:
        """Return exact transverse Manning zones or one uniform Manning value."""

        if not section.roughness_zones:
            return None, (float(section.manning_n),)
        zones = sorted(section.roughness_zones, key=lambda item: item.start_station_m)
        profile_end = float(section.points[-1].station_m)
        tolerance = max(1e-9, profile_end * 1e-10)
        if not isclose(float(zones[0].start_station_m), 0.0, abs_tol=tolerance):
            self._reject(
                "DFLOW_ROUGHNESS_COVERAGE_INVALID",
                "transverse roughness zones must start at station zero",
                f"{field_path}.roughness_zones",
            )
        if not isclose(float(zones[-1].end_station_m), profile_end, abs_tol=tolerance):
            self._reject(
                "DFLOW_ROUGHNESS_COVERAGE_INVALID",
                "transverse roughness zones must cover the complete profile width",
                f"{field_path}.roughness_zones",
            )
        for left, right in zip(zones, zones[1:]):
            if not isclose(
                float(left.end_station_m),
                float(right.start_station_m),
                rel_tol=0.0,
                abs_tol=tolerance,
            ):
                self._reject(
                    "DFLOW_ROUGHNESS_COVERAGE_INVALID",
                    "transverse roughness zones must be contiguous and non-overlapping",
                    f"{field_path}.roughness_zones",
                )
        positions = [float(zones[0].start_station_m)]
        positions.extend(float(item.end_station_m) for item in zones)
        return tuple(positions), tuple(float(item.manning_n) for item in zones)

    def _validate_boundaries(self, model: Hydraulic1DModel) -> None:
        for index, boundary in enumerate(model.boundaries):
            if boundary.location == "lateral":
                self._reject(
                    "DFLOW_LATERAL_BOUNDARY_UNSUPPORTED",
                    "the audited base adapter supports endpoint Q(t)/H(t) only",
                    f"boundaries[{index}]",
                )
            expected_variable = (
                "discharge" if boundary.location == "upstream" else "water_level"
            )
            if boundary.variable != expected_variable:
                self._reject(
                    "DFLOW_ENDPOINT_BOUNDARY_INVALID",
                    (
                        "upstream boundaries require discharge Q(t) and downstream "
                        "boundaries require water level H(t)"
                    ),
                    f"boundaries[{index}].variable",
                )
            times = [float(item.time_seconds) for item in boundary.series]
            if times[0] != 0.0:
                self._reject(
                    "DFLOW_BOUNDARY_COVERAGE_INVALID",
                    "boundary series must begin at t=0",
                    f"boundaries[{index}].series",
                )
            if len(times) > 1 and not isclose(
                times[-1],
                float(model.settings.duration_seconds),
                rel_tol=0.0,
                abs_tol=1e-9,
            ):
                self._reject(
                    "DFLOW_BOUNDARY_COVERAGE_INVALID",
                    "time-varying boundary must end exactly at the simulation duration",
                    f"boundaries[{index}].series",
                )

    def _validate_initial_condition(self, model: Hydraulic1DModel) -> None:
        condition = model.initial_condition
        if condition.by_section:
            self._reject(
                "DFLOW_SECTION_INITIAL_STATE_UNVERIFIED",
                "section-varying initial state has no audited native mapping",
                "initial_condition.by_section",
            )
        if condition.water_level_m is None or condition.discharge_m3s is None:
            self._reject(
                "DFLOW_INITIAL_STATE_INVALID",
                "a uniform water level and discharge are both required",
                "initial_condition",
            )
        if not isclose(float(condition.discharge_m3s), 0.0, abs_tol=1e-12):
            self._reject(
                "DFLOW_INITIAL_DISCHARGE_UNSUPPORTED",
                (
                    "D-Flow accepts initial velocity fields, not Dayu cross-section "
                    "discharge; nonzero initial discharge is not converted to velocity"
                ),
                "initial_condition.discharge_m3s",
            )
        for index, section in enumerate(model.cross_sections):
            if float(condition.water_level_m) <= min(
                float(point.elevation_m) for point in section.points
            ):
                self._reject(
                    "DFLOW_INITIAL_STATE_DRY",
                    "initial water level must exceed every local minimum bed elevation",
                    f"cross_sections[{index}]",
                )

    def _validate_time(self, model: Hydraulic1DModel) -> None:
        settings = model.settings
        for value, name in (
            (
                float(settings.duration_seconds) / float(settings.time_step_seconds),
                "duration_seconds",
            ),
            (
                float(settings.output_interval_seconds)
                / float(settings.time_step_seconds),
                "output_interval_seconds",
            ),
        ):
            if not isclose(value, round(value), rel_tol=0.0, abs_tol=1e-9):
                self._reject(
                    "DFLOW_TIME_INTERVAL_INVALID",
                    f"{name} must be an integer multiple of time_step_seconds",
                    f"settings.{name}",
                )

    def _validate_structures(
        self,
        model: Hydraulic1DModel,
        *,
        gate_specs: Sequence[GateHydraulicSpec],
        pump_specs: Sequence[PumpHydraulicSpec],
    ) -> None:
        specs: dict[str, GateHydraulicSpec | PumpHydraulicSpec] = {}
        for spec in (*gate_specs, *pump_specs):
            if spec.structure_id in specs:
                self._reject(
                    "DFLOW_STRUCTURE_SPEC_DUPLICATE",
                    f"structure {spec.structure_id} has more than one hydraulic spec",
                    "structure_specs",
                )
            specs[spec.structure_id] = spec
        active = {item.id: item for item in model.structures if item.status == "active"}
        if set(specs) != set(active):
            self._reject(
                "DFLOW_STRUCTURE_SPEC_SET_INVALID",
                (
                    "Gate/Pump specs must exactly cover active structures; "
                    f"missing={sorted(set(active).difference(specs))}, "
                    f"extra={sorted(set(specs).difference(active))}"
                ),
                "structure_specs",
            )
        for structure_id, structure in active.items():
            spec = specs[structure_id]
            expected_kind = "gate" if isinstance(spec, GateHydraulicSpec) else "pump"
            if structure.kind not in (
                {"gate", "sluice"} if expected_kind == "gate" else {"pump"}
            ):
                self._reject(
                    "DFLOW_STRUCTURE_KIND_MISMATCH",
                    f"structure {structure_id} does not match its {expected_kind} spec",
                    "structures",
                )
            if spec.branch_id != structure.branch_id or not isclose(
                float(spec.chainage_m),
                float(structure.chainage_m),
                rel_tol=0.0,
                abs_tol=1e-9,
            ):
                self._reject(
                    "DFLOW_STRUCTURE_LOCATION_MISMATCH",
                    f"structure {structure_id} spec has a different branch or chainage",
                    "structure_specs",
                )

    @staticmethod
    def _validate_native_network_id(value: str, field_path: str) -> None:
        if (
            len(value.encode("ascii", errors="ignore")) != len(value)
            or len(value) > _NATIVE_NETWORK_ID_LIMIT
        ):
            raise Hydraulic1DValidationError(
                "DFLOW_NATIVE_ID_UNSAFE",
                f"native network id must be ASCII and at most {_NATIVE_NETWORK_ID_LIMIT} characters",
                field_path=field_path,
            )
        if fullmatch(_NATIVE_SAFE_ID, value) is None:
            raise Hydraulic1DValidationError(
                "DFLOW_NATIVE_ID_UNSAFE",
                "native network id may contain letters, digits, dot, underscore, and hyphen only",
                field_path=field_path,
            )

    @staticmethod
    def _reject(code: str, message: str, field_path: str) -> NoReturn:
        raise Hydraulic1DValidationError(code, message, field_path=field_path)


class DFlowFMModelBuilder:
    """Materialize one complete typed D-Flow FM base-1D case."""

    def __init__(
        self,
        validator: DFlowFMModelValidator | None = None,
        structure_mapper: DFlowFMStructureMapper | None = None,
    ) -> None:
        self.validator = validator or DFlowFMModelValidator()
        self.structure_mapper = structure_mapper or DFlowFMStructureMapper()

    def build(
        self,
        model: Hydraulic1DModel,
        workspace: DFlowJobWorkspace | Path,
        *,
        gate_specs: Sequence[GateHydraulicSpec] = (),
        pump_specs: Sequence[PumpHydraulicSpec] = (),
    ) -> DFlowFMPreparedCase:
        """Validate, map, recursively save, reload, and inventory one native case."""

        self.validator.validate(model, gate_specs=gate_specs, pump_specs=pump_specs)
        try:
            job_workspace = (
                workspace.validate()
                if isinstance(workspace, DFlowJobWorkspace)
                else DFlowJobWorkspace.open(workspace)
            )
        except Hydraulic1DExecutionError as exc:
            raise Hydraulic1DValidationError(
                "DFLOW_WORKSPACE_INVALID",
                f"job workspace is not an owned D-Flow workspace: {exc}",
                field_path="workspace",
            ) from exc
        occupied_areas = [
            area
            for area, path in (
                ("input", job_workspace.input_dir),
                ("control", job_workspace.control_dir),
                ("output", job_workspace.output_dir),
                ("logs", job_workspace.logs_dir),
            )
            if any(path.iterdir())
        ]
        metadata_entries = {item.name for item in job_workspace.metadata_dir.iterdir()}
        if metadata_entries != {job_workspace.marker_path.name}:
            occupied_areas.append("metadata")
        if occupied_areas:
            raise Hydraulic1DValidationError(
                "DFLOW_WORKSPACE_NOT_EMPTY",
                (
                    "D-Flow case generation requires pristine workspace areas; "
                    f"occupied={sorted(set(occupied_areas))}"
                ),
                field_path="workspace",
            )
        resolved = job_workspace.path
        types = _load_hydrolib_types()
        paths = self._paths(job_workspace)
        branches = sorted(model.branches, key=lambda item: (item.code, item.id))
        branch_map = {item.id: item for item in branches}
        native_network = self._network(model, branches, types)
        network_model = _new_file_model(
            types.network_model(network=native_network),
            paths["network"],
        )
        cross_def, cross_loc, roughness = self._cross_sections(
            model,
            branch_map,
            paths,
            types,
        )
        forcing, external_forcing = self._boundaries(
            model,
            branch_map,
            paths,
            types,
        )
        observations, observation_cross_sections = self._observations(
            model,
            branch_map,
            paths,
            types,
        )
        structures = self._structures(
            branch_map,
            gate_specs=gate_specs,
            pump_specs=pump_specs,
            path=paths["structures"],
            types=types,
        )
        if model.initial_condition.water_level_m is None:
            raise Hydraulic1DValidationError(
                "DFLOW_INITIAL_STATE_INVALID",
                "uniform initial water level was not validated",
                field_path="initial_condition.water_level_m",
            )
        geometry_values: dict[str, Any] = {
            "netFile": network_model,
            "crossDefFile": cross_def,
            "crossLocFile": cross_loc,
            "frictFile": [roughness],
            "waterLevIni": float(model.initial_condition.water_level_m),
            "useCaching": False,
            "changeStructureDimensions": False,
        }
        if structures is not None:
            geometry_values["structureFile"] = [structures]
        settings = model.settings
        native_model = _new_file_model(
            types.fm_model(
                geometry=types.geometry(**geometry_values),
                time=types.time(
                    refDate=DFLOW_REFERENCE_DATE,
                    tZone=0.0,
                    tUnit="S",
                    dtUser=float(settings.time_step_seconds),
                    dtMax=float(settings.time_step_seconds),
                    dtInit=float(settings.time_step_seconds),
                    autoTimestep=0,
                    tStart=0.0,
                    tStop=float(settings.duration_seconds),
                ),
                external_forcing=types.external_forcing(
                    extForceFileNew=external_forcing
                ),
                output=types.output(
                    outputDir=Path("../output"),
                    obsFile=[observations],
                    crsFile=[observation_cross_sections],
                    hisInterval=[
                        float(settings.output_interval_seconds),
                        0.0,
                        float(settings.duration_seconds),
                    ],
                    mapInterval=[0.0],
                    rstInterval=[0.0],
                    ncFormat=4,
                    wrihis_waterlevel_s1=True,
                    wrihis_waterdepth=True,
                    wrihis_velocity=True,
                    wrihis_discharge=True,
                    wrihis_balance=True,
                ),
            ),
            paths["case"],
        )
        del forcing  # owned recursively by the Boundary models
        try:
            native_model.save(recurse=True)
            reloaded = types.fm_model(paths["case"])
            native_dimr = _new_file_model(
                types.dimr(
                    documentation=types.dimr_documentation(
                        fileVersion="1.3",
                        createdBy=(
                            f"Dayu via HYDROLIB-core {HYDROLIB_CORE_REQUIRED_VERSION}"
                        ),
                        creationDate=datetime(2020, 1, 1),
                    ),
                    # HYDROLIB-core 1.0.1 performs its discriminated-union lookup
                    # before accepting a typed Start instance.  Supplying schema
                    # input here still produces a typed Start, while also exercising
                    # the exact public validation path used when loading the XML.
                    control=[{"start": {"name": "dflowfm"}}],
                    component=[
                        types.fm_component(
                            name="dflowfm",
                            workingDir=Path("../input"),
                            inputFile=Path(CASE_FILENAME),
                            process=1,
                            model=reloaded,
                        )
                    ],
                ),
                paths["dimr"],
            )
            native_dimr.save()
            reloaded_dimr = types.dimr(paths["dimr"])
        except Exception as exc:
            raise Hydraulic1DValidationError(
                "DFLOW_NATIVE_MODEL_INVALID",
                f"HYDROLIB save/load failed: {exc}",
                field_path="hydraulic_model",
            ) from exc
        self._assert_saved(paths, structure_file=structures is not None)
        manifest = self._manifest(
            model,
            paths,
            branches,
            structure_file=structures is not None,
        )
        paths["manifest"].write_text(
            dumps(manifest, ensure_ascii=True, indent=2, sort_keys=True) + "\n",
            encoding="ascii",
        )
        return DFlowFMPreparedCase(
            workspace=resolved,
            job_workspace=job_workspace,
            dimr_config_file=paths["dimr"],
            case_file=paths["case"],
            network_file=paths["network"],
            cross_definition_file=paths["cross_def"],
            cross_location_file=paths["cross_loc"],
            roughness_file=paths["roughness"],
            forcing_file=paths["forcing"],
            external_forcing_file=paths["external_forcing"],
            observation_file=paths["observations"],
            observation_cross_section_file=paths["observation_cross_sections"],
            structure_file=paths["structures"] if structures is not None else None,
            manifest_file=paths["manifest"],
            result_file=paths["result"],
            native_model=reloaded,
            native_dimr_model=reloaded_dimr,
        )

    @staticmethod
    def _paths(workspace: DFlowJobWorkspace) -> dict[str, Path]:
        return {
            "root": workspace.path,
            "dimr": workspace.control_dir / DIMR_FILENAME,
            "case": workspace.input_dir / CASE_FILENAME,
            "network": workspace.input_dir / NETWORK_FILENAME,
            "cross_def": workspace.input_dir / CROSS_DEF_FILENAME,
            "cross_loc": workspace.input_dir / CROSS_LOC_FILENAME,
            "roughness": workspace.input_dir / ROUGHNESS_FILENAME,
            "forcing": workspace.input_dir / FORCING_FILENAME,
            "external_forcing": workspace.input_dir / EXTERNAL_FORCING_FILENAME,
            "observations": workspace.input_dir / OBSERVATION_FILENAME,
            "observation_cross_sections": (
                workspace.input_dir / OBSERVATION_CROSS_SECTION_FILENAME
            ),
            "structures": workspace.input_dir / STRUCTURE_FILENAME,
            "manifest": workspace.metadata_dir / MANIFEST_FILENAME,
            "result": workspace.output_dir / RESULT_FILENAME,
        }

    def _network(
        self,
        model: Hydraulic1DModel,
        branches: Sequence[HydraulicBranch],
        types: _HydrolibTypes,
    ) -> Any:
        network = types.network(is_geographic=False)
        edge_length = self.validator.mesh_edge_length(model)
        sections_by_branch = self._sections_by_branch(model)
        structures_by_branch: dict[str, list[float]] = {
            item.id: [] for item in branches
        }
        for structure in model.structures:
            if structure.status == "active":
                branch = next(
                    item for item in branches if item.id == structure.branch_id
                )
                structures_by_branch[branch.id].append(
                    float(structure.chainage_m - branch.start_chainage_m)
                )
        for branch in branches:
            coordinates = self.validator.branch_coordinates(
                model,
                branch,
                field_path=f"branches[{branch.id}]",
            )
            anchors = [
                float(section.chainage_m - branch.start_chainage_m)
                for section in sections_by_branch[branch.id]
            ]
            anchors.extend(structures_by_branch[branch.id])
            offsets = self._mesh_offsets(
                float(branch.end_chainage_m - branch.start_chainage_m),
                edge_length,
                anchors,
            )
            native_branch = types.branch(
                geometry=types.np.asarray(coordinates, dtype=float),
                branch_offsets=types.np.asarray(offsets, dtype=float),
            )
            network.mesh1d_add_branch(
                native_branch,
                name=branch.id,
                long_name=branch.code,
                branch_order=-1,
                force_midpoint=False,
            )
        self._apply_dayu_node_ids(model, network, types)
        return network

    @staticmethod
    def _mesh_offsets(
        length: float,
        maximum_edge_length: float,
        anchors: Iterable[float],
    ) -> tuple[float, ...]:
        """Create a deterministic mesh containing every authoritative Dayu location."""

        ordered = sorted({0.0, length, *(float(item) for item in anchors)})
        offsets: list[float] = []
        for left, right in zip(ordered, ordered[1:]):
            segment_length = right - left
            if segment_length <= 0.0:
                raise Hydraulic1DValidationError(
                    "DFLOW_MESH_ANCHOR_INVALID",
                    "cross-section and structure mesh anchors must be strictly ordered",
                    field_path="cross_sections",
                )
            divisions = max(1, ceil(segment_length / maximum_edge_length))
            offsets.extend(
                left + segment_length * index / divisions for index in range(divisions)
            )
        offsets.append(length)
        return tuple(offsets)

    def _apply_dayu_node_ids(
        self,
        model: Hydraulic1DModel,
        network: Any,
        types: _HydrolibTypes,
    ) -> None:
        """Replace coordinate-derived network node labels with authoritative Dayu IDs."""

        native_mesh = network._mesh1d
        node_by_xy = {
            self.validator.node_xy(
                model,
                node,
                field_path=f"metadata.dflow_fm.node_coordinates.{node.id}",
            ): node
            for node in model.nodes
        }
        if len(node_by_xy) != len(model.nodes):
            raise Hydraulic1DValidationError(
                "DFLOW_NODE_COORDINATE_DUPLICATE",
                "different Dayu nodes must not share one coordinate",
                field_path="nodes",
            )
        ids: list[str] = []
        names: list[str] = []
        for x, y in zip(native_mesh.network1d_node_x, native_mesh.network1d_node_y):
            node = node_by_xy.get((float(x), float(y)))
            if node is None:
                raise Hydraulic1DValidationError(
                    "DFLOW_NATIVE_TOPOLOGY_MISMATCH",
                    "HYDROLIB created a network endpoint without an exact Dayu node",
                    field_path="nodes",
                )
            ids.append(node.id)
            names.append(node.name or node.code)
        native_mesh.network1d_node_id = types.np.asarray(ids, dtype=object)
        native_mesh.network1d_node_long_name = types.np.asarray(names, dtype=object)

    def _cross_sections(
        self,
        model: Hydraulic1DModel,
        branch_map: Mapping[str, HydraulicBranch],
        paths: Mapping[str, Path],
        types: _HydrolibTypes,
    ) -> tuple[Any, Any, Any]:
        definitions: list[Any] = []
        locations: list[Any] = []
        global_roughness: list[Any] = []
        for section in self._ordered_sections(model):
            friction_positions, friction_values = self.validator.roughness_values(
                section,
                field_path=f"cross_sections[{section.id}]",
            )
            friction_ids = [
                self._roughness_id(section.id, index)
                for index in range(len(friction_values))
            ]
            global_roughness.extend(
                types.friction_global(
                    frictionId=friction_id,
                    frictionType="Manning",
                    frictionValue=value,
                )
                for friction_id, value in zip(friction_ids, friction_values)
            )
            definition_values: dict[str, Any] = {
                "id": section.id,
                "type": "yz",
                "singleValuedZ": True,
                "yzCount": len(section.points),
                "yCoordinates": [float(item.station_m) for item in section.points],
                "zCoordinates": [float(item.elevation_m) for item in section.points],
                "conveyance": "lumped" if friction_positions is None else "segmented",
                "sectionCount": len(friction_values),
                "frictionIds": friction_ids,
            }
            if friction_positions is not None:
                definition_values["frictionPositions"] = list(friction_positions)
            definitions.append(types.yz_cross_section(**definition_values))
            branch = branch_map[section.branch_id]
            locations.append(
                types.cross_section(
                    id=section.id,
                    branchId=section.branch_id,
                    chainage=float(section.chainage_m - branch.start_chainage_m),
                    shift=0.0,
                    definitionId=section.id,
                )
            )
        return (
            _new_file_model(
                types.cross_def_model(definition=definitions), paths["cross_def"]
            ),
            _new_file_model(
                types.cross_loc_model(crosssection=locations), paths["cross_loc"]
            ),
            _new_file_model(
                types.friction_model(global_=global_roughness), paths["roughness"]
            ),
        )

    @staticmethod
    def _roughness_id(section_id: str, zone_index: int) -> str:
        """Return an ASCII, collision-resistant native roughness variable id."""

        digest = sha256(f"{section_id}\x00{zone_index}".encode("utf-8")).hexdigest()
        return f"dayu-manning-{digest[:24]}"

    def _boundaries(
        self,
        model: Hydraulic1DModel,
        branch_map: Mapping[str, HydraulicBranch],
        paths: Mapping[str, Path],
        types: _HydrolibTypes,
    ) -> tuple[Any, Any]:
        forcings: list[Any] = []
        bindings: list[tuple[str, str]] = []
        duration = float(model.settings.duration_seconds)
        for boundary in sorted(model.boundaries, key=lambda item: item.id):
            branch = branch_map[boundary.branch_id]
            node_id = (
                branch.upstream_node_id
                if boundary.location == "upstream"
                else branch.downstream_node_id
            )
            quantity = (
                "dischargebnd" if boundary.variable == "discharge" else "waterlevelbnd"
            )
            unit = "m3/s" if boundary.variable == "discharge" else "m"
            rows = self._boundary_rows(boundary, duration=duration)
            forcings.append(
                types.time_series(
                    name=node_id,
                    function="timeseries",
                    timeInterpolation="linear",
                    quantityunitpair=[
                        types.quantity_unit_pair(
                            quantity="time",
                            unit=DFLOW_TIME_UNIT,
                        ),
                        types.quantity_unit_pair(quantity=quantity, unit=unit),
                    ],
                    datablock=rows,
                )
            )
            bindings.append((node_id, quantity))
        forcing_model = _new_file_model(
            types.forcing_model(forcing=forcings),
            paths["forcing"],
        )
        native_boundaries = [
            types.boundary(
                quantity=quantity,
                nodeid=node_id,
                forcingfile=forcing_model,
            )
            for node_id, quantity in bindings
        ]
        return forcing_model, _new_file_model(
            types.ext_model(boundary=native_boundaries),
            paths["external_forcing"],
        )

    @staticmethod
    def _boundary_rows(
        boundary: BoundaryCondition,
        *,
        duration: float,
    ) -> list[list[float]]:
        rows = [
            [float(item.time_seconds), float(item.value)] for item in boundary.series
        ]
        if len(rows) == 1:
            rows.append([duration, rows[0][1]])
        return rows

    def _observations(
        self,
        model: Hydraulic1DModel,
        branch_map: Mapping[str, HydraulicBranch],
        paths: Mapping[str, Path],
        types: _HydrolibTypes,
    ) -> tuple[Any, Any]:
        points: list[Any] = []
        cross_sections: list[Any] = []
        for section in self._ordered_sections(model):
            branch = branch_map[section.branch_id]
            native_chainage = float(section.chainage_m - branch.start_chainage_m)
            points.append(
                types.observation_point(
                    name=section.id,
                    branchId=section.branch_id,
                    chainage=native_chainage,
                )
            )
            cross_sections.append(
                types.observation_cross_section(
                    name=section.id,
                    branchId=section.branch_id,
                    chainage=native_chainage,
                )
            )
        return (
            _new_file_model(
                types.observation_point_model(observationpoint=points),
                paths["observations"],
            ),
            _new_file_model(
                types.observation_cross_section_model(
                    observationcrosssection=cross_sections
                ),
                paths["observation_cross_sections"],
            ),
        )

    def _structures(
        self,
        branch_map: Mapping[str, HydraulicBranch],
        *,
        gate_specs: Sequence[GateHydraulicSpec],
        pump_specs: Sequence[PumpHydraulicSpec],
        path: Path,
        types: _HydrolibTypes,
    ) -> Any | None:
        native: list[Any] = []
        for spec in sorted(gate_specs, key=lambda item: item.structure_id):
            branch = branch_map[spec.branch_id]
            local = spec.model_copy(
                update={"chainage_m": float(spec.chainage_m - branch.start_chainage_m)}
            )
            native.append(self.structure_mapper.map_gate(local))
        for spec in sorted(pump_specs, key=lambda item: item.structure_id):
            branch = branch_map[spec.branch_id]
            local = spec.model_copy(
                update={"chainage_m": float(spec.chainage_m - branch.start_chainage_m)}
            )
            native.append(self.structure_mapper.map_pump(local))
        if not native:
            return None
        return _new_file_model(types.structure_model(structure=native), path)

    @staticmethod
    def _sections_by_branch(
        model: Hydraulic1DModel,
    ) -> dict[str, tuple[HydraulicCrossSection, ...]]:
        return {
            branch.id: tuple(
                sorted(
                    (
                        item
                        for item in model.cross_sections
                        if item.branch_id == branch.id
                    ),
                    key=lambda item: item.chainage_m,
                )
            )
            for branch in model.branches
        }

    @staticmethod
    def _ordered_sections(model: Hydraulic1DModel) -> tuple[HydraulicCrossSection, ...]:
        branch_order = {
            branch.id: index
            for index, branch in enumerate(
                sorted(model.branches, key=lambda item: (item.code, item.id))
            )
        }
        return tuple(
            sorted(
                model.cross_sections,
                key=lambda item: (branch_order[item.branch_id], item.chainage_m),
            )
        )

    @staticmethod
    def _assert_saved(paths: Mapping[str, Path], *, structure_file: bool) -> None:
        required = [
            "dimr",
            "case",
            "network",
            "cross_def",
            "cross_loc",
            "roughness",
            "forcing",
            "external_forcing",
            "observations",
            "observation_cross_sections",
        ]
        if structure_file:
            required.append("structures")
        missing = [key for key in required if not paths[key].is_file()]
        if missing:
            raise Hydraulic1DValidationError(
                "DFLOW_NATIVE_ARTIFACT_MISSING",
                "HYDROLIB did not save required artifacts: " + ", ".join(missing),
                field_path="workspace",
            )

    def _manifest(
        self,
        model: Hydraulic1DModel,
        paths: Mapping[str, Path],
        branches: Sequence[HydraulicBranch],
        *,
        structure_file: bool,
    ) -> dict[str, Any]:
        artifact_keys = [
            "dimr",
            "case",
            "network",
            "cross_def",
            "cross_loc",
            "roughness",
            "forcing",
            "external_forcing",
            "observations",
            "observation_cross_sections",
        ]
        if structure_file:
            artifact_keys.append("structures")
        return {
            "schema_version": "dayu.dflow-fm-manifest.v1",
            "simulation_id": model.simulation_id,
            "scenario_id": model.scenario_id,
            "engine": DFLOW_ENGINE_ID,
            "engine_version": DFLOW_ENGINE_VERSION,
            "native_engine_version": DFLOW_NATIVE_VERSION,
            "hydrolib_core_version": HYDROLIB_CORE_REQUIRED_VERSION,
            "reference_date": DFLOW_REFERENCE_DATE,
            "time_unit": DFLOW_TIME_UNIT,
            "coordinate_reference_system": model.metadata["engineering_crs"],
            "native_coordinate_source": "metadata.dflow_fm",
            "result_file": paths["result"].relative_to(paths["root"]).as_posix(),
            "top_level_runtime": {
                "launcher": "dimr",
                "config": f"control/{DIMR_FILENAME}",
                "component": "dflowfm",
                "component_working_directory": "../input",
                "direct_dflowfm_launch_allowed": False,
            },
            "result_contract": {
                "station_dimension": "stations",
                "station_id_variable": "station_name",
                "water_level_variable": "waterlevel",
                "cross_section_dimension": "cross_section",
                "cross_section_id_variable": "cross_section_name",
                "discharge_variable": "cross_section_discharge",
                "flow_area_variable": "cross_section_area",
                "velocity_variable": "cross_section_velocity",
            },
            "branches": [
                {
                    "dayu_id": branch.id,
                    "native_id": branch.id,
                    "native_chainage_offset_m": -float(branch.start_chainage_m),
                }
                for branch in branches
            ],
            "cross_sections": [
                {
                    "dayu_id": section.id,
                    "native_observation_id": section.id,
                    "branch_id": section.branch_id,
                    "dayu_chainage_m": float(section.chainage_m),
                    "native_chainage_m": float(
                        section.chainage_m
                        - next(
                            branch.start_chainage_m
                            for branch in branches
                            if branch.id == section.branch_id
                        )
                    ),
                }
                for section in self._ordered_sections(model)
            ],
            "roughness_mapping": (
                "crossDef.yz.frictionIds -> roughness.ini Global(Manning)"
            ),
            "roughness_variables": [
                {
                    "cross_section_id": section.id,
                    "native_ids": [
                        self._roughness_id(section.id, index)
                        for index in range(
                            len(
                                self.validator.roughness_values(
                                    section,
                                    field_path=f"cross_sections[{section.id}]",
                                )[1]
                            )
                        )
                    ],
                }
                for section in self._ordered_sections(model)
            ],
            "initial_state": {
                "water_level": "Geometry.waterLevIni",
                "discharge": "verified-zero-only",
            },
            "artifacts": [
                {
                    "path": paths[key].relative_to(paths["root"]).as_posix(),
                    "sha256": sha256(paths[key].read_bytes()).hexdigest(),
                }
                for key in artifact_keys
            ],
            "input_sha256": sha256(
                model.model_dump_json(exclude_none=False).encode("utf-8")
            ).hexdigest(),
        }


__all__ = [
    "CASE_FILENAME",
    "DFLOW_ENGINE_ID",
    "DFLOW_ENGINE_VERSION",
    "DFLOW_NATIVE_VERSION",
    "DFLOW_REFERENCE_DATE",
    "DFLOW_TIME_UNIT",
    "DIMR_FILENAME",
    "DFlowFMModelBuilder",
    "DFlowFMModelValidator",
    "DFlowFMPreparedCase",
    "MANIFEST_FILENAME",
    "RESULT_FILENAME",
    "ROUGHNESS_FILENAME",
]
