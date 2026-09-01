"""Build a solver-neutral 1D snapshot directly from authoritative HYDRO-DATA rows."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.common.spatial import geometry_json
from app.gis.models import (
    BoundaryCondition as BoundaryConditionRow,
    DatasetVersion,
    SimulationCase,
    SimulationCaseBoundary,
)
from app.hydraulic.models import (
    HydraulicBranch as HydraulicBranchRow,
    HydraulicCrossSection as HydraulicCrossSectionRow,
    HydraulicCrossSectionPoint,
    HydraulicCrossSectionProfile,
    HydraulicNetwork,
    HydraulicNode as HydraulicNodeRow,
    HydraulicRoughnessZone,
    HydraulicStructure as HydraulicStructureRow,
    HydraulicStructureScenario,
)
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
    SectionInitialState,
    SimulationSettings,
    TimeValue,
)
from model.hydraulic_1d.errors import Hydraulic1DValidationError
from model.hydraulic_1d.factory import create_hydraulic_1d_engine
from model.provenance import snapshot_hash


def _reject(code: str, message: str, field_path: str) -> None:
    """Raise one stable readiness error before any task or workspace is created."""

    raise Hydraulic1DValidationError(code, message, field_path=field_path)


def _number(
    task_config: Mapping[str, Any],
    case_config: Mapping[str, Any],
    name: str,
    *aliases: str,
) -> float:
    """Resolve a required task value with a case-level Standard 1D fallback."""

    value = task_config.get(name)
    if value is None:
        for candidate in (name, *aliases):
            value = case_config.get(candidate)
            if value is not None:
                break
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        _reject(
            "DAYU_HYDRAULIC_1D_CONFIGURATION_MISSING",
            f"{name} must be configured as a finite number",
            f"simulation_case.hydraulic_1d_configuration.{name}",
        )
    return float(value)


def _time_values(
    row: BoundaryConditionRow,
    *,
    variable: str,
) -> tuple[TimeValue, ...]:
    """Normalize legacy constants and current Q(t)/H(t) JSON without extrapolation."""

    values = row.values
    if not isinstance(values, Mapping):
        _reject(
            "DAYU_BOUNDARY_VALUES_INVALID",
            "boundary values must be an object",
            f"boundary_condition[{row.id}].values",
        )
    mode = str(values.get("mode", "")).lower()
    if mode == "constant" or (
        "value" in values and "time_seconds" not in values and "series" not in values
    ):
        value = values.get("value")
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            _reject(
                "DAYU_BOUNDARY_VALUES_INVALID",
                "constant boundary requires numeric value",
                f"boundary_condition[{row.id}].values.value",
            )
        return (TimeValue(time_seconds=0.0, value=float(value)),)
    series = values.get("series")
    if isinstance(series, Sequence) and not isinstance(series, (str, bytes)):
        samples: list[TimeValue] = []
        for index, sample in enumerate(series):
            if not isinstance(sample, Mapping):
                _reject(
                    "DAYU_BOUNDARY_VALUES_INVALID",
                    "boundary series samples must be objects",
                    f"boundary_condition[{row.id}].values.series[{index}]",
                )
            raw_time = sample.get("time_seconds")
            raw_value = sample.get("value")
            if raw_value is None:
                raw_value = sample.get("flow_m3_s" if variable == "discharge" else "water_level_m")
            samples.append(TimeValue(time_seconds=raw_time, value=raw_value))
        return tuple(samples)
    times = values.get("time_seconds")
    ordinates = values.get("flow_m3_s" if variable == "discharge" else "water_level_m")
    if (
        not isinstance(times, Sequence)
        or isinstance(times, (str, bytes))
        or not isinstance(ordinates, Sequence)
        or isinstance(ordinates, (str, bytes))
        or len(times) != len(ordinates)
        or not times
    ):
        _reject(
            "DAYU_BOUNDARY_VALUES_INVALID",
            "boundary requires aligned non-empty time and value arrays",
            f"boundary_condition[{row.id}].values",
        )
    return tuple(TimeValue(time_seconds=time, value=value) for time, value in zip(times, ordinates))


def _boundary(
    row: BoundaryConditionRow,
    branches: list[HydraulicBranchRow],
) -> BoundaryCondition:
    """Bind endpoint boundaries to hydraulic nodes and lateral points to Branch/chainage."""

    branch_by_id = {item.id: item for item in branches}
    if row.boundary_type == "upstream_discharge":
        candidates = [item for item in branches if item.upstream_node_id == row.hydraulic_node_id]
        location = "upstream"
        variable = "discharge"
        chainage = None
    elif row.boundary_type == "downstream_water_level":
        candidates = [item for item in branches if item.downstream_node_id == row.hydraulic_node_id]
        location = "downstream"
        variable = "water_level"
        chainage = None
    elif row.boundary_type == "lateral_inflow":
        branch_id = row.branch_id
        chainage = row.chainage_m
        if (
            isinstance(branch_id, bool)
            or not isinstance(branch_id, int)
            or branch_id not in branch_by_id
        ):
            _reject(
                "DAYU_LATERAL_LOCATION_INVALID",
                "lateral boundary requires an authoritative hydraulic branch_id",
                f"boundary_condition[{row.id}].branch_id",
            )
        if isinstance(chainage, bool) or not isinstance(chainage, (int, float)):
            _reject(
                "DAYU_LATERAL_LOCATION_INVALID",
                "lateral boundary requires chainage_m",
                f"boundary_condition[{row.id}].chainage_m",
            )
        branch = branch_by_id[branch_id]
        if not branch.start_chainage <= float(chainage) <= branch.end_chainage:
            _reject(
                "DAYU_LATERAL_LOCATION_INVALID",
                "lateral boundary chainage_m lies outside its hydraulic Branch",
                f"boundary_condition[{row.id}].chainage_m",
            )
        candidates = [branch]
        location = "lateral"
        variable = "discharge"
    else:
        _reject(
            "DAYU_BOUNDARY_TYPE_UNSUPPORTED",
            f"unsupported boundary type {row.boundary_type!r}",
            f"boundary_condition[{row.id}].boundary_type",
        )
    if len(candidates) != 1:
        _reject(
            "DAYU_BOUNDARY_BINDING_INVALID",
            "endpoint boundary must bind exactly one hydraulic Branch endpoint",
            f"boundary_condition[{row.id}].hydraulic_node_id",
        )
    return BoundaryCondition(
        id=str(row.id),
        branch_id=str(candidates[0].id),
        location=location,  # type: ignore[arg-type]
        variable=variable,  # type: ignore[arg-type]
        chainage_m=float(chainage) if chainage is not None else None,
        series=_time_values(row, variable=variable),
    )


def _structures(
    session: Session,
    case: SimulationCase,
    case_config: Mapping[str, Any],
    network_id: int,
) -> tuple[HydraulicStructure, ...]:
    """Build unified structures with case overrides before capability validation."""

    raw = case_config.get("structures", {})
    if raw is None:
        _reject(
            "DAYU_STRUCTURE_CONFIGURATION_INVALID",
            "structures configuration must be an object, not null",
            "simulation_case.hydraulic_1d_configuration.structures",
        )
    if not isinstance(raw, Mapping):
        _reject(
            "DAYU_STRUCTURE_CONFIGURATION_INVALID",
            "structures configuration must be an object",
            "simulation_case.hydraulic_1d_configuration.structures",
        )
    gates = raw.get("gates", [])
    if not isinstance(gates, Sequence) or isinstance(gates, (str, bytes)):
        _reject(
            "DAYU_STRUCTURE_CONFIGURATION_INVALID",
            "structures.gates must be an array",
            "simulation_case.hydraulic_1d_configuration.structures.gates",
        )
    pumps = raw.get("pumps", [])
    if not isinstance(pumps, Sequence) or isinstance(pumps, (str, bytes)):
        _reject(
            "DAYU_STRUCTURE_CONFIGURATION_INVALID",
            "structures.pumps must be an array",
            "simulation_case.hydraulic_1d_configuration.structures.pumps",
        )
    if gates or pumps:
        _reject(
            "MODEL_ENGINE_INCOMPATIBLE",
            "legacy Gate/Pump case lists are unsupported; use unified structures and capability status",
            "simulation_case.hydraulic_1d_configuration.structures",
        )
    selected = raw.get("structure_ids")
    if selected is not None and (
        not isinstance(selected, Sequence) or isinstance(selected, (str, bytes))
    ):
        _reject(
            "DAYU_STRUCTURE_CONFIGURATION_INVALID",
            "structures.structure_ids must be an array",
            "simulation_case.hydraulic_1d_configuration.structures.structure_ids",
        )
    selected_ids: list[int] | None = None
    if selected is not None:
        try:
            selected_ids = [int(value) for value in selected]
        except (TypeError, ValueError):
            _reject(
                "DAYU_STRUCTURE_CONFIGURATION_INVALID",
                "structures.structure_ids must contain integer identifiers",
                "simulation_case.hydraulic_1d_configuration.structures.structure_ids",
            )
        if len(set(selected_ids)) != len(selected_ids):
            _reject(
                "DAYU_STRUCTURE_CONFIGURATION_INVALID",
                "structures.structure_ids must not contain duplicates",
                "simulation_case.hydraulic_1d_configuration.structures.structure_ids",
            )
    statement = (
        select(HydraulicStructureRow)
        .where(
            HydraulicStructureRow.dataset_version_id == case.dataset_version_id,
            HydraulicStructureRow.network_id == network_id,
        )
        .order_by(
            HydraulicStructureRow.branch_id,
            HydraulicStructureRow.chainage_m,
            HydraulicStructureRow.id,
        )
    )
    rows = list(session.scalars(statement).all())
    overrides = (
        {
            item.structure_id: item
            for item in session.scalars(
                select(HydraulicStructureScenario).where(
                    HydraulicStructureScenario.case_id == case.id,
                    HydraulicStructureScenario.structure_id.in_([item.id for item in rows]),
                )
            ).all()
        }
        if rows
        else {}
    )
    result: list[HydraulicStructure] = []
    for row in rows:
        override = overrides.get(row.id)
        hydraulic_parameters = dict(row.hydraulic_parameters)
        operation_parameters = dict(row.operation_parameters)
        if override is not None:
            hydraulic_parameters.update(override.hydraulic_parameters_override)
            operation_parameters.update(override.operation_parameters_override)
        geometry = {
            key: value
            for key, value in {
                "crest_elevation_m": row.crest_elevation_m,
                "invert_elevation_m": row.invert_elevation_m,
                "crest_width_m": row.width_m,
                "height_m": row.height_m,
            }.items()
            if value is not None
        }
        result.append(
            HydraulicStructure(
                id=str(row.id),
                name=row.structure_name,
                branch_id=str(row.branch_id),
                kind=row.structure_type,
                chainage_m=row.chainage_m,
                location_geometry=geometry_json(session, row.location),
                geometry=geometry,
                hydraulic_law_type=row.hydraulic_law_type,
                hydraulic_law_parameters=hydraulic_parameters,
                operation_rule_type=(
                    override.operation_rule_type_override
                    if override is not None and override.operation_rule_type_override
                    else row.operation_rule_type
                ),
                operation_parameters=operation_parameters,
                scenario_id=str(case.id) if override is not None else None,
                status=(
                    override.status_override
                    if override is not None and override.status_override
                    else row.status
                ),
                metadata={
                    **row.metadata_json,
                    "structure_code": row.structure_code,
                    "scenario_override_id": override.id if override is not None else None,
                },
            )
        )
    if selected_ids is not None:
        active_ids = {int(item.id) for item in result if item.status == "active"}
        if set(selected_ids) != active_ids:
            _reject(
                "DAYU_STRUCTURE_CONFIGURATION_INVALID",
                "structures.structure_ids must exactly match every effectively active "
                "Structure in the case Network",
                "simulation_case.hydraulic_1d_configuration.structures.structure_ids",
            )
    return tuple(result)


def _with_simulation_identity(model: Hydraulic1DModel) -> Hydraulic1DModel:
    """Derive the simulation identity from every canonical physical input field."""

    identity_payload = model.model_dump(mode="json", exclude={"simulation_id"})
    identity = snapshot_hash(identity_payload)
    return model.model_copy(update={"simulation_id": f"sim-{identity[:20]}"})


def build_hydraulic_1d_model(
    session: Session,
    case_id: int,
    task_config: Mapping[str, Any],
) -> Hydraulic1DModel:
    """Freeze one Standard 1D model from HYDRO-DATA without legacy projections."""

    case = session.get(SimulationCase, case_id)
    if case is None:
        raise LookupError("simulation case does not exist")
    dataset = session.get(DatasetVersion, case.dataset_version_id)
    if dataset is None:
        raise LookupError("simulation case Dataset Version does not exist")
    if dataset.status not in {"approved", "published"}:
        _reject(
            "DAYU_DATASET_NOT_AUTHORITATIVE",
            "Standard 1D requires an approved or published Dataset Version",
            "dataset_version.status",
        )
    case_config = case.hydraulic_1d_configuration or {}
    if not isinstance(case_config, Mapping):
        _reject(
            "DAYU_HYDRAULIC_1D_CONFIGURATION_INVALID",
            "hydraulic_1d_configuration must be an object",
            "simulation_case.hydraulic_1d_configuration",
        )
    networks = list(
        session.scalars(
            select(HydraulicNetwork)
            .where(HydraulicNetwork.dataset_version_id == case.dataset_version_id)
            .order_by(HydraulicNetwork.id)
        ).all()
    )
    if len(networks) != 1 or not networks[0].engineering_crs:
        _reject(
            "DAYU_NETWORK_NOT_READY",
            "Standard 1D requires exactly one Network with a confirmed engineering CRS",
            "network",
        )
    network = networks[0]
    branch_rows = list(
        session.scalars(
            select(HydraulicBranchRow)
            .where(HydraulicBranchRow.network_id == network.id)
            .order_by(HydraulicBranchRow.id)
        ).all()
    )
    if not branch_rows:
        _reject("DAYU_BRANCH_MISSING", "Network contains no hydraulic Branch", "branches")
    branches: list[HydraulicBranch] = []
    for index, row in enumerate(branch_rows):
        if (
            row.direction_status != "confirmed"
            or row.upstream_node_id is None
            or row.downstream_node_id is None
        ):
            _reject(
                "DAYU_BRANCH_DIRECTION_UNCONFIRMED",
                "Branch direction and both hydraulic endpoint nodes must be confirmed",
                f"branches[{index}]",
            )
        branches.append(
            HydraulicBranch(
                id=str(row.id),
                code=row.branch_code,
                upstream_node_id=str(row.upstream_node_id),
                downstream_node_id=str(row.downstream_node_id),
                start_chainage_m=row.start_chainage,
                end_chainage_m=row.end_chainage,
            )
        )
    incoming_counts: dict[int, int] = {}
    outgoing_counts: dict[int, int] = {}
    for row in branch_rows:
        assert row.upstream_node_id is not None and row.downstream_node_id is not None
        outgoing_counts[row.upstream_node_id] = outgoing_counts.get(row.upstream_node_id, 0) + 1
        incoming_counts[row.downstream_node_id] = incoming_counts.get(row.downstream_node_id, 0) + 1
    node_rows = list(
        session.scalars(
            select(HydraulicNodeRow)
            .where(HydraulicNodeRow.network_id == network.id)
            .order_by(HydraulicNodeRow.node_code, HydraulicNodeRow.id)
        ).all()
    )
    nodes: list[HydraulicNode] = []
    for row in node_rows:
        incoming = incoming_counts.get(row.id, 0)
        outgoing = outgoing_counts.get(row.id, 0)
        if row.node_type == "storage_connection":
            node_type = "storage_connection"
        elif incoming == 0 or outgoing == 0:
            node_type = "boundary"
        elif incoming >= 1 and outgoing >= 2:
            node_type = "bifurcation"
        elif incoming >= 2 and outgoing >= 1:
            node_type = "junction"
        else:
            node_type = "internal"
        nodes.append(
            HydraulicNode(
                id=str(row.id),
                code=row.node_code,
                name=row.node_name,
                node_type=node_type,
                location_geometry=geometry_json(session, row.geometry),
                metadata=row.metadata_json,
            )
        )
    section_rows = list(
        session.scalars(
            select(HydraulicCrossSectionRow)
            .where(HydraulicCrossSectionRow.dataset_version_id == case.dataset_version_id)
            .order_by(HydraulicCrossSectionRow.branch_id, HydraulicCrossSectionRow.chainage)
        ).all()
    )
    cross_sections: list[HydraulicCrossSection] = []
    for index, row in enumerate(section_rows):
        if row.orientation_status != "confirmed":
            _reject(
                "DAYU_CROSS_SECTION_ORIENTATION_UNCONFIRMED",
                "Cross Section orientation must be confirmed",
                f"cross_sections[{index}]",
            )
        profiles = list(
            session.scalars(
                select(HydraulicCrossSectionProfile).where(
                    HydraulicCrossSectionProfile.cross_section_id == row.id,
                    HydraulicCrossSectionProfile.is_active.is_(True),
                )
            ).all()
        )
        if len(profiles) != 1 or profiles[0].vertical_unit != "m":
            _reject(
                "DAYU_CROSS_SECTION_PROFILE_NOT_READY",
                "Cross Section requires exactly one active metre-based Profile",
                f"cross_sections[{index}].profile",
            )
        profile = profiles[0]
        if (
            not network.vertical_datum
            or network.vertical_datum.strip().lower() == "unknown"
            or not profile.vertical_datum
            or profile.vertical_datum.strip().lower() == "unknown"
            or profile.vertical_datum != network.vertical_datum
        ):
            _reject(
                "DAYU_VERTICAL_DATUM_MISMATCH",
                "Network and active Cross Section Profile require one confirmed matching vertical datum",
                f"cross_sections[{index}].profile.vertical_datum",
            )
        points = list(
            session.scalars(
                select(HydraulicCrossSectionPoint)
                .where(HydraulicCrossSectionPoint.profile_id == profile.id)
                .order_by(HydraulicCrossSectionPoint.sequence)
            ).all()
        )
        zones = list(
            session.scalars(
                select(HydraulicRoughnessZone)
                .where(HydraulicRoughnessZone.profile_id == profile.id)
                .order_by(HydraulicRoughnessZone.zone_order)
            ).all()
        )
        cross_sections.append(
            HydraulicCrossSection(
                id=str(row.id),
                branch_id=str(row.branch_id),
                code=row.section_code,
                chainage_m=row.chainage,
                vertical_datum=profile.vertical_datum,
                points=tuple(
                    CrossSectionPoint(
                        station_m=point.distance,
                        elevation_m=point.elevation,
                        source_x=point.source_x,
                        source_y=point.source_y,
                        source_z=point.source_z,
                        source_crs=point.source_crs,
                        source_axis_mapping=point.source_axis_mapping,
                    )
                    for point in points
                ),
                manning_n=profile.default_manning_n,
                roughness_zones=tuple(
                    RoughnessZone(
                        start_station_m=zone.offset_start_m,
                        end_station_m=zone.offset_end_m,
                        manning_n=zone.manning_n,
                    )
                    for zone in zones
                ),
                location_geometry=geometry_json(session, row.location_geometry),
                axis_geometry=(
                    geometry_json(session, row.axis_geometry)
                    if row.axis_geometry is not None
                    else None
                ),
                left_bank=(
                    geometry_json(session, row.left_bank) if row.left_bank is not None else None
                ),
                right_bank=(
                    geometry_json(session, row.right_bank) if row.right_bank is not None else None
                ),
            )
        )
    boundary_rows = list(
        session.scalars(
            select(BoundaryConditionRow)
            .join(
                SimulationCaseBoundary,
                SimulationCaseBoundary.boundary_condition_id == BoundaryConditionRow.id,
            )
            .where(SimulationCaseBoundary.case_id == case.id)
            .order_by(BoundaryConditionRow.id)
        ).all()
    )
    if not boundary_rows and case.boundary_condition_id is not None:
        legacy_boundary = session.get(BoundaryConditionRow, case.boundary_condition_id)
        if legacy_boundary is not None:
            boundary_rows = [legacy_boundary]
    boundaries = tuple(_boundary(row, branch_rows) for row in boundary_rows)
    initial_config = case_config.get("initial_condition", {})
    if not isinstance(initial_config, Mapping):
        _reject(
            "DAYU_INITIAL_CONDITION_INVALID",
            "initial_condition must be an object",
            "simulation_case.hydraulic_1d_configuration.initial_condition",
        )
    by_section = initial_config.get("by_section", [])
    if by_section:
        if not isinstance(by_section, Sequence) or isinstance(by_section, (str, bytes)):
            _reject(
                "DAYU_INITIAL_CONDITION_INVALID",
                "initial_condition.by_section must be an array",
                "simulation_case.hydraulic_1d_configuration.initial_condition.by_section",
            )
        initial = InitialCondition(
            by_section=tuple(SectionInitialState.model_validate(item) for item in by_section)
        )
    else:
        initial = InitialCondition(
            water_level_m=_number(
                task_config,
                initial_config,
                "initial_water_level",
                "water_level_m",
            ),
            discharge_m3s=_number(
                task_config,
                initial_config,
                "initial_flow",
                "discharge_m3s",
            ),
        )
    settings_config = case_config.get("settings", {})
    if not isinstance(settings_config, Mapping):
        _reject(
            "DAYU_HYDRAULIC_1D_CONFIGURATION_INVALID",
            "settings must be an object",
            "simulation_case.hydraulic_1d_configuration.settings",
        )
    settings = SimulationSettings(
        duration_seconds=_number(task_config, settings_config, "duration_seconds"),
        time_step_seconds=_number(task_config, settings_config, "time_step_seconds"),
        output_interval_seconds=_number(task_config, settings_config, "output_interval_seconds"),
    )
    structures = _structures(session, case, case_config, network.id)
    configuration_hash = snapshot_hash(dict(case_config))
    provisional = Hydraulic1DModel(
        simulation_id="pending-identity",
        scenario_id=str(case.id),
        network_id=str(network.id),
        nodes=tuple(nodes),
        branches=tuple(branches),
        cross_sections=tuple(cross_sections),
        boundaries=boundaries,
        initial_condition=initial,
        settings=settings,
        structures=structures,
        metadata={
            "dataset_version_id": dataset.id,
            "dataset_content_hash": dataset.content_hash,
            "engineering_crs": network.engineering_crs,
            "display_crs": network.display_crs,
            "horizontal_unit": network.horizontal_unit,
            "vertical_unit": network.vertical_unit,
            "vertical_datum": network.vertical_datum,
            "hydraulic_1d_configuration_hash": configuration_hash,
        },
    )
    model = _with_simulation_identity(provisional)
    create_hydraulic_1d_engine().validate(model)
    return model


def freeze_hydraulic_1d_input(
    session: Session,
    case_id: int,
    task_config: Mapping[str, Any],
) -> tuple[dict[str, Any], str]:
    """Return a canonical JSON snapshot and SHA-256 digest for immutable execution."""

    snapshot = build_hydraulic_1d_model(session, case_id, task_config).model_dump(mode="json")
    return snapshot, snapshot_hash(snapshot)
