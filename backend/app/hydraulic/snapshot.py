"""Canonical full-engineering graph snapshots for Dataset Version governance."""

from __future__ import annotations

from typing import Any

from sqlalchemy import inspect as sqlalchemy_inspect, select
from sqlalchemy.orm import Session

from app.gis.models import BoundaryCondition, ModelParameter, SimulationCase, SimulationCaseBoundary
from app.gis_governance.hashing import canonical_sha256
from app.gis_governance.repository import row_geometry_hash_value
from app.hydraulic.models import (
    HydraulicBranch,
    HydraulicBranchVertex,
    HydraulicCrossSection,
    HydraulicCrossSectionPoint,
    HydraulicCrossSectionProcessing,
    HydraulicCrossSectionProfile,
    HydraulicImportJob,
    HydraulicImportMappingProfile,
    HydraulicNetwork,
    HydraulicNode,
    HydraulicObservationSeries,
    HydraulicReach,
    HydraulicRoughnessZone,
    HydraulicStructure,
    HydraulicStructureScenario,
)


_ENGINEERING_MODELS: tuple[type[Any], ...] = (
    HydraulicNetwork,
    HydraulicNode,
    HydraulicBranch,
    HydraulicBranchVertex,
    HydraulicReach,
    HydraulicCrossSection,
    HydraulicCrossSectionProfile,
    HydraulicCrossSectionPoint,
    HydraulicRoughnessZone,
    HydraulicCrossSectionProcessing,
    HydraulicStructure,
    HydraulicStructureScenario,
    BoundaryCondition,
    ModelParameter,
    SimulationCase,
    HydraulicObservationSeries,
    HydraulicImportJob,
    HydraulicImportMappingProfile,
)


def _row_snapshot(
    session: Session,
    row: Any,
    references: dict[str, dict[int, str]] | None = None,
) -> dict[str, Any]:
    """Serialize one engineering row without surrogate keys or volatile timestamps."""

    mapper = sqlalchemy_inspect(type(row), raiseerr=False)
    if mapper is None:
        column_bindings = [
            (column, column.name) for column in row.__table__.columns
        ]
    else:
        # SQLAlchemy attributes may intentionally differ from physical column
        # names (for example start_chainage -> chainage_start_m).  Snapshot keys
        # remain database-stable while values must be read through the mapped
        # Python attribute.
        column_bindings = [
            (attribute.columns[0], attribute.key)
            for attribute in mapper.column_attrs
        ]
    values = {
        column.name: getattr(row, attribute_key)
        for column, attribute_key in column_bindings
        if column.name not in {
            "id", "dataset_version_id", "created_at", "updated_at", "created_time",
            "completed_at", "generated_at", "imported_at", "raw_content",
        }
    }
    # These fields are version-local display/transaction identities.  Clone
    # assigns new values to satisfy database uniqueness, but the hydraulic
    # engineering content is unchanged and must retain the same canonical hash.
    table_name = row.__table__.name
    if table_name == "import_job":
        values.pop("job_code", None)
    elif table_name == "simulation_case":
        values.pop("name", None)
    for column, attribute_key in column_bindings:
        if getattr(column.type, "geometry_type", None):
            values[column.name] = row_geometry_hash_value(
                session, getattr(row, attribute_key)
            )
    reference_columns = {
        "network_id": "network",
        "branch_id": "branch",
        "upstream_node_id": "node",
        "downstream_node_id": "node",
        "hydraulic_node_id": "node",
        "cross_section_id": "cross_section",
        "profile_id": "profile",
        "processing_id": "processing",
        "structure_id": "structure",
        "case_id": "simulation_case",
        "boundary_condition_id": "boundary_condition",
        "import_job_id": "import_job",
        "mapping_profile_id": "mapping_profile",
    }
    for column, family in reference_columns.items():
        source_id = values.get(column)
        if source_id is None:
            continue
        reference = (references or {}).get(family, {}).get(int(source_id))
        if reference is None:
            raise ValueError(
                f"完整工程图 hash 无法解析 {row.__table__.name}.{column} 的版本内引用"
            )
        values[column] = reference
    for legacy_column in ("legacy_river_id", "legacy_cross_section_id", "legacy_gate_id", "legacy_pump_id", "target_node_id"):
        values.pop(legacy_column, None)
    values["entity_type"] = f"{row.__table__.schema or 'public'}.{table_name}"
    return values


def _reference_maps(rows_by_model: dict[type[Any], list[Any]]) -> dict[str, dict[int, str]]:
    """Replace version-local foreign keys with stable engineering business keys."""

    networks = {item.id: item.code for item in rows_by_model[HydraulicNetwork]}
    nodes = {
        item.id: f"{networks[item.network_id]}:{item.node_code}"
        for item in rows_by_model[HydraulicNode]
    }
    branches = {
        item.id: f"{networks[item.network_id]}:{item.branch_code}"
        for item in rows_by_model[HydraulicBranch]
    }
    sections = {item.id: item.section_code for item in rows_by_model[HydraulicCrossSection]}
    profiles = {
        item.id: f"{sections[item.cross_section_id]}:{item.topography_id}"
        for item in rows_by_model[HydraulicCrossSectionProfile]
    }
    processing = {
        item.id: f"{profiles[item.profile_id]}:{item.profile_hash}:{item.processor_version}:{item.vertical_step_m}"
        for item in rows_by_model[HydraulicCrossSectionProcessing]
    }
    structures = {
        item.id: f"{networks[item.network_id]}:{item.structure_code}"
        for item in rows_by_model[HydraulicStructure]
    }
    boundaries = {
        item.id: f"{item.boundary_type}:{item.name}" for item in rows_by_model[BoundaryCondition]
    }
    # Case names are global UI identities and are deliberately changed during a
    # version clone.  Boundary-link references therefore use their deterministic
    # version-local order instead of the mutable display name.
    cases = {
        item.id: f"case-{position:06d}"
        for position, item in enumerate(rows_by_model[SimulationCase], start=1)
    }
    imports = {
        item.id: f"{item.source_hash_sha256}:{item.config_hash}"
        for item in rows_by_model[HydraulicImportJob]
    }
    mappings = {item.id: item.name for item in rows_by_model[HydraulicImportMappingProfile]}
    return {
        "network": networks,
        "node": nodes,
        "branch": branches,
        "cross_section": sections,
        "profile": profiles,
        "processing": processing,
        "structure": structures,
        "boundary_condition": boundaries,
        "simulation_case": cases,
        "import_job": imports,
        "mapping_profile": mappings,
    }


def engineering_graph_rows(session: Session, version_id: int) -> list[dict[str, Any]]:
    """Return every version-owned engineering input row used by REAL-01 identity."""

    rows_by_model: dict[type[Any], list[Any]] = {}
    for model in _ENGINEERING_MODELS:
        rows_by_model[model] = list(session.scalars(
            select(model).where(model.dataset_version_id == version_id).order_by(model.id)
        ).all())
    references = _reference_maps(rows_by_model)
    records: list[dict[str, Any]] = []
    for rows in rows_by_model.values():
        records.extend(_row_snapshot(session, row, references) for row in rows)
    links = session.scalars(
        select(SimulationCaseBoundary)
        .join(SimulationCase, SimulationCase.id == SimulationCaseBoundary.case_id)
        .where(SimulationCase.dataset_version_id == version_id)
        .order_by(SimulationCaseBoundary.case_id, SimulationCaseBoundary.boundary_condition_id)
    ).all()
    records.extend(_row_snapshot(session, row, references) for row in links)
    return records


def engineering_graph_content_hash(session: Session, version_id: int) -> str:
    """Hash the full immutable engineering graph, unlike the legacy four-layer hash."""

    return canonical_sha256(engineering_graph_rows(session, version_id))
