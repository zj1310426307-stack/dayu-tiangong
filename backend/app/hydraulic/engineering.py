"""Engineering network graph, structure CRUD, and capability-facing services."""

from __future__ import annotations

from json import loads
from math import isclose
from typing import Any

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.dataset.lifecycle import assert_dataset_version_mutable
from app.gis.models import BoundaryCondition as BoundaryConditionRow
from app.gis.models import SimulationCase
from app.hydraulic.location import locate_geometry_on_branch
from app.hydraulic.models import (
    HydraulicBranch,
    HydraulicCrossSection,
    HydraulicNetwork,
    HydraulicNode,
    HydraulicStructure,
    HydraulicStructureScenario,
)
from app.hydraulic.schemas import (
    HydraulicNetworkGraphRecord,
    HydraulicStructureCreate,
    HydraulicStructureRecord,
    HydraulicStructureScenarioRecord,
    HydraulicStructureScenarioUpsert,
    HydraulicStructureUpdate,
    SolverCapabilityRecord,
)
from model.hydraulic_1d.capabilities import capabilities_for
from model.hydraulic_1d.registry import (
    DEFAULT_HYDRAULIC_1D_ENGINE_ID,
    DEFAULT_HYDRAULIC_1D_ENGINE_VERSION,
    engine_registrations,
)


STRUCTURE_SNAP_TOLERANCE_M = 5.0
STRUCTURE_CHAINAGE_TOLERANCE_M = 5.0


def engine_capabilities() -> list[SolverCapabilityRecord]:
    """Return every registered engine matrix from the source-controlled catalog."""

    return [
        SolverCapabilityRecord.model_validate(item.to_dict())
        for registration in engine_registrations()
        for item in capabilities_for(
            registration.engine_id,
            registration.engine_version,
        )
    ]


def _capability(structure_type: str) -> tuple[str, str]:
    """Resolve a structure type against the exact engine and adapter version."""

    item = next(
        (
            value
            for value in capabilities_for(
                DEFAULT_HYDRAULIC_1D_ENGINE_ID,
                DEFAULT_HYDRAULIC_1D_ENGINE_VERSION,
            )
            if value.feature == structure_type.upper()
        ),
        None,
    )
    return (
        (item.status.value, item.reason)
        if item is not None
        else ("UNSUPPORTED", "feature is absent from the capability registry")
    )


def _geometry_json(session: Session, geometry: Any) -> dict[str, Any]:
    """Serialize one authoritative PostGIS geometry as GeoJSON."""

    raw = session.scalar(select(func.ST_AsGeoJSON(geometry)))
    if not isinstance(raw, str):
        raise ValueError("Hydraulic structure geometry is unavailable")
    return loads(raw)


def _record(session: Session, value: HydraulicStructure) -> HydraulicStructureRecord:
    """Map persistence into the public solver-neutral structure contract."""

    solver_status, solver_reason = _capability(value.structure_type)
    return HydraulicStructureRecord(
        id=value.id,
        dataset_version_id=value.dataset_version_id,
        network_id=value.network_id,
        branch_id=value.branch_id,
        structure_code=value.structure_code,
        structure_name=value.structure_name,
        structure_type=value.structure_type,
        chainage_m=value.chainage_m,
        location_geometry=_geometry_json(session, value.location),
        crest_elevation_m=value.crest_elevation_m,
        invert_elevation_m=value.invert_elevation_m,
        width_m=value.width_m,
        height_m=value.height_m,
        hydraulic_law_type=value.hydraulic_law_type,
        hydraulic_parameters=value.hydraulic_parameters,
        operation_rule_type=value.operation_rule_type,
        operation_parameters=value.operation_parameters,
        status=value.status,
        metadata=value.metadata_json,
        legacy_gate_id=value.legacy_gate_id,
        legacy_pump_id=value.legacy_pump_id,
        solver_status=solver_status,
        solver_reason=solver_reason,
    )


def list_structures(
    session: Session,
    *,
    dataset_version_id: int,
    network_id: int | None = None,
) -> list[HydraulicStructureRecord]:
    """List structures in deterministic network/branch/chainage order."""

    statement = select(HydraulicStructure).where(
        HydraulicStructure.dataset_version_id == dataset_version_id
    )
    if network_id is not None:
        statement = statement.where(HydraulicStructure.network_id == network_id)
    rows = session.scalars(
        statement.order_by(
            HydraulicStructure.network_id,
            HydraulicStructure.branch_id,
            HydraulicStructure.chainage_m,
            HydraulicStructure.id,
        )
    ).all()
    return [_record(session, item) for item in rows]


def get_structure(session: Session, structure_id: int) -> HydraulicStructureRecord | None:
    """Return one structure or None for router-level not-found handling."""

    value = session.get(HydraulicStructure, structure_id)
    return None if value is None else _record(session, value)


def _branch_network(
    session: Session,
    *,
    branch_id: int,
    network_id: int,
    dataset_version_id: int,
) -> tuple[HydraulicBranch, HydraulicNetwork]:
    """Resolve one branch only within its authoritative network and dataset version."""

    branch = session.get(HydraulicBranch, branch_id)
    network = session.get(HydraulicNetwork, network_id)
    if (
        branch is None
        or network is None
        or branch.network_id != network_id
        or branch.dataset_version_id != dataset_version_id
        or network.dataset_version_id != dataset_version_id
    ):
        raise ValueError("Structure branch/network/version reference is invalid")
    return branch, network


def _validated_location(
    session: Session,
    *,
    branch: HydraulicBranch,
    network: HydraulicNetwork,
    chainage_m: float,
    x: float,
    y: float,
) -> Any:
    """Validate XY and chainage through the shared engineering mapping service."""

    if not branch.start_chainage <= chainage_m <= branch.end_chainage:
        raise ValueError("STRUCTURE_LOCATION_INVALID: chainage lies outside Branch")
    geometry = func.ST_SetSRID(func.ST_MakePoint(x, y), 4490)
    computed, distance_m = locate_geometry_on_branch(session, branch, network, geometry)
    if distance_m > STRUCTURE_SNAP_TOLERANCE_M:
        raise ValueError(
            "STRUCTURE_LOCATION_INVALID: geometry is outside the Branch snap tolerance"
        )
    if not isclose(
        computed,
        chainage_m,
        rel_tol=0.0,
        abs_tol=STRUCTURE_CHAINAGE_TOLERANCE_M,
    ):
        raise ValueError(
            "STRUCTURE_LOCATION_INVALID: XY-to-Branch chainage conflicts with chainage_m"
        )
    return geometry


def create_structure(
    session: Session, payload: HydraulicStructureCreate
) -> HydraulicStructureRecord:
    """Create a validated structure without requiring current solver support."""

    assert_dataset_version_mutable(session, payload.dataset_version_id)
    branch, network = _branch_network(
        session,
        branch_id=payload.branch_id,
        network_id=payload.network_id,
        dataset_version_id=payload.dataset_version_id,
    )
    geometry = _validated_location(
        session,
        branch=branch,
        network=network,
        chainage_m=payload.chainage_m,
        x=payload.x,
        y=payload.y,
    )
    value = HydraulicStructure(
        dataset_version_id=payload.dataset_version_id,
        network_id=payload.network_id,
        branch_id=payload.branch_id,
        structure_code=payload.structure_code,
        structure_name=payload.structure_name,
        structure_type=payload.structure_type,
        chainage_m=payload.chainage_m,
        location=geometry,
        crest_elevation_m=payload.crest_elevation_m,
        invert_elevation_m=payload.invert_elevation_m,
        width_m=payload.width_m,
        height_m=payload.height_m,
        hydraulic_law_type=payload.hydraulic_law_type,
        hydraulic_parameters=payload.hydraulic_parameters,
        operation_rule_type=payload.operation_rule_type,
        operation_parameters=payload.operation_parameters,
        status=payload.status,
        metadata_json=payload.metadata,
    )
    session.add(value)
    session.flush()
    return _record(session, value)


def update_structure(
    session: Session,
    structure_id: int,
    payload: HydraulicStructureUpdate,
) -> HydraulicStructureRecord:
    """Update one structure atomically and revalidate any location change."""

    value = session.get(HydraulicStructure, structure_id)
    if value is None:
        raise LookupError("Hydraulic structure does not exist")
    assert_dataset_version_mutable(session, value.dataset_version_id)
    updates = payload.model_dump(exclude_unset=True)
    non_nullable_fields = {
        "branch_id",
        "structure_code",
        "structure_name",
        "structure_type",
        "chainage_m",
        "hydraulic_law_type",
        "hydraulic_parameters",
        "operation_rule_type",
        "operation_parameters",
        "status",
        "metadata",
    }
    null_fields = sorted(
        field for field in non_nullable_fields if field in updates and updates[field] is None
    )
    if null_fields:
        raise ValueError("Hydraulic structure fields cannot be null: " + ", ".join(null_fields))
    branch_id = int(updates.get("branch_id", value.branch_id))
    branch, network = _branch_network(
        session,
        branch_id=branch_id,
        network_id=value.network_id,
        dataset_version_id=value.dataset_version_id,
    )
    x = updates.pop("x", None)
    y = updates.pop("y", None)
    chainage = float(updates.get("chainage_m", value.chainage_m))
    if x is not None and y is not None:
        value.location = _validated_location(
            session,
            branch=branch,
            network=network,
            chainage_m=chainage,
            x=float(x),
            y=float(y),
        )
    elif "chainage_m" in updates or "branch_id" in updates:
        computed, distance_m = locate_geometry_on_branch(session, branch, network, value.location)
        if distance_m > STRUCTURE_SNAP_TOLERANCE_M or not isclose(
            computed, chainage, rel_tol=0.0, abs_tol=STRUCTURE_CHAINAGE_TOLERANCE_M
        ):
            raise ValueError(
                "STRUCTURE_LOCATION_INVALID: updated branch/chainage conflicts with XY"
            )
    field_map = {
        "metadata": "metadata_json",
    }
    for key, item in updates.items():
        setattr(value, field_map.get(key, key), item)
    session.flush()
    return _record(session, value)


def delete_structure(session: Session, structure_id: int) -> None:
    """Delete only the unified structure; linked legacy source assets remain intact."""

    value = session.get(HydraulicStructure, structure_id)
    if value is None:
        raise LookupError("Hydraulic structure does not exist")
    assert_dataset_version_mutable(session, value.dataset_version_id)
    session.delete(value)
    session.flush()


def upsert_structure_scenario(
    session: Session,
    structure_id: int,
    case_id: int,
    payload: HydraulicStructureScenarioUpsert,
) -> HydraulicStructureScenarioRecord:
    """Create or replace one case-specific operation override."""

    structure = session.get(HydraulicStructure, structure_id)
    case = session.get(SimulationCase, case_id)
    if structure is None or case is None:
        raise LookupError("Hydraulic structure or Simulation Case does not exist")
    if case.dataset_version_id != structure.dataset_version_id:
        raise ValueError("Scenario and structure belong to different Dataset Versions")
    assert_dataset_version_mutable(session, structure.dataset_version_id)
    value = session.scalar(
        select(HydraulicStructureScenario).where(
            HydraulicStructureScenario.structure_id == structure_id,
            HydraulicStructureScenario.case_id == case_id,
        )
    )
    if value is None:
        value = HydraulicStructureScenario(
            dataset_version_id=structure.dataset_version_id,
            structure_id=structure_id,
            case_id=case_id,
        )
        session.add(value)
    value.status_override = payload.status_override
    value.hydraulic_parameters_override = payload.hydraulic_parameters_override
    value.operation_rule_type_override = payload.operation_rule_type_override
    value.operation_parameters_override = payload.operation_parameters_override
    value.metadata_json = payload.metadata
    session.flush()
    return _scenario_record(value)


def _scenario_record(value: HydraulicStructureScenario) -> HydraulicStructureScenarioRecord:
    """Map one scenario override into the API contract."""

    return HydraulicStructureScenarioRecord(
        id=value.id,
        dataset_version_id=value.dataset_version_id,
        case_id=value.case_id,
        structure_id=value.structure_id,
        status_override=value.status_override,
        hydraulic_parameters_override=value.hydraulic_parameters_override,
        operation_rule_type_override=value.operation_rule_type_override,
        operation_parameters_override=value.operation_parameters_override,
        metadata=value.metadata_json,
        updated_at=value.updated_at,
    )


def network_graph(session: Session, network_id: int) -> HydraulicNetworkGraphRecord:
    """Return reusable branch/node/structure/boundary relationships for one network."""

    network = session.get(HydraulicNetwork, network_id)
    if network is None:
        raise LookupError("Hydraulic network does not exist")
    nodes = session.scalars(
        select(HydraulicNode)
        .where(HydraulicNode.network_id == network_id)
        .order_by(HydraulicNode.node_code, HydraulicNode.id)
    ).all()
    branches = session.scalars(
        select(HydraulicBranch)
        .where(HydraulicBranch.network_id == network_id)
        .order_by(HydraulicBranch.branch_code, HydraulicBranch.id)
    ).all()
    branch_ids = [item.id for item in branches]
    node_ids = [item.id for item in nodes]
    boundaries = (
        session.scalars(
            select(BoundaryConditionRow)
            .where(
                BoundaryConditionRow.dataset_version_id == network.dataset_version_id,
                or_(
                    BoundaryConditionRow.branch_id.in_(branch_ids),
                    BoundaryConditionRow.hydraulic_node_id.in_(node_ids),
                ),
            )
            .order_by(BoundaryConditionRow.id)
        ).all()
        if branch_ids or node_ids
        else []
    )
    cross_sections = (
        session.execute(
            select(
                HydraulicCrossSection,
                func.ST_AsGeoJSON(HydraulicCrossSection.location_geometry),
            )
            .where(HydraulicCrossSection.branch_id.in_(branch_ids))
            .order_by(
                HydraulicCrossSection.branch_id,
                HydraulicCrossSection.chainage,
                HydraulicCrossSection.id,
            )
        ).all()
        if branch_ids
        else []
    )
    incoming_by_node: dict[int, list[int]] = {}
    outgoing_by_node: dict[int, list[int]] = {}
    for branch in branches:
        if branch.downstream_node_id is not None:
            incoming_by_node.setdefault(branch.downstream_node_id, []).append(branch.id)
        if branch.upstream_node_id is not None:
            outgoing_by_node.setdefault(branch.upstream_node_id, []).append(branch.id)
    return HydraulicNetworkGraphRecord(
        network_id=network_id,
        nodes=[
            {
                "id": item.id,
                "code": item.node_code,
                "name": item.node_name,
                "node_type": item.node_type,
                "incoming_branch_ids": incoming_by_node.get(item.id, []),
                "outgoing_branch_ids": outgoing_by_node.get(item.id, []),
                "location_geometry": _geometry_json(session, item.geometry),
            }
            for item in nodes
        ],
        branches=[
            {
                "id": item.id,
                "code": item.branch_code,
                "name": item.branch_name,
                "upstream_node_id": item.upstream_node_id,
                "downstream_node_id": item.downstream_node_id,
                "chainage_start_m": item.start_chainage,
                "chainage_end_m": item.end_chainage,
                "direction_status": item.direction_status,
            }
            for item in branches
        ],
        cross_sections=[
            {
                "id": item.id,
                "code": item.section_code,
                "name": item.section_name,
                "branch_id": item.branch_id,
                "chainage_m": item.chainage,
                "chainage_source": item.chainage_source,
                "orientation_status": item.orientation_status,
                "location_geometry": loads(location_geojson),
            }
            for item, location_geojson in cross_sections
        ],
        structures=list_structures(
            session,
            dataset_version_id=network.dataset_version_id,
            network_id=network_id,
        ),
        boundaries=[
            {
                "id": item.id,
                "name": item.name,
                "boundary_type": item.boundary_type,
                "branch_id": item.branch_id,
                "hydraulic_node_id": item.hydraulic_node_id,
                "chainage_m": item.chainage_m,
                "unit": item.unit,
            }
            for item in boundaries
        ],
    )
