"""Clone the version-owned unified hydraulic engineering graph with ID remapping.

This module intentionally excludes execution Tasks, solver workspaces, and result
products.  Those are derived evidence and must be recreated from the cloned,
editable Dataset Version.  Legacy GIS foreign keys are not carried across a
version boundary; the cloned unified graph retains its source IDs in metadata
only when already recorded by the source object.
"""

from __future__ import annotations

from collections.abc import Callable
from copy import deepcopy
from typing import Any, TypeVar

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.gis.models import (
    BoundaryCondition,
    ModelParameter,
    SimulationCase,
    SimulationCaseBoundary,
)
from app.hydraulic.models import (
    HydraulicBranch,
    HydraulicBranchVertex,
    HydraulicCrossSection,
    HydraulicCrossSectionHydraulicRow,
    HydraulicCrossSectionPoint,
    HydraulicCrossSectionProcessing,
    HydraulicCrossSectionProfile,
    HydraulicExternalResult,
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


Row = TypeVar("Row")


_VOLATILE_COLUMNS = {
    "id",
    "dataset_version_id",
    "created_at",
    "updated_at",
    "created_time",
    "completed_at",
    "generated_at",
    "imported_at",
}


def _row_values(row: Any, *, excluded: set[str] | None = None) -> dict[str, Any]:
    """Copy persisted business columns but never surrogate IDs or lifecycle timestamps."""

    omitted = _VOLATILE_COLUMNS | (excluded or set())
    return {
        column.name: getattr(row, column.name)
        for column in row.__table__.columns
        if column.name not in omitted
    }


def _copy_family(
    session: Session,
    source_model: type[Row],
    target_model: type[Row],
    source_version_id: int,
    target_version_id: int,
    *,
    mutate: Callable[[Row, dict[str, Any]], None] | None = None,
) -> dict[int, int]:
    """Clone one independent family and return its source-to-target primary-key map."""

    mapping: dict[int, int] = {}
    rows = session.scalars(
        select(source_model)
        .where(source_model.dataset_version_id == source_version_id)
        .order_by(source_model.id)
    ).all()
    for source in rows:
        values = _row_values(source)
        values["dataset_version_id"] = target_version_id
        if mutate is not None:
            mutate(source, values)
        target = target_model(**values)
        session.add(target)
        session.flush()
        mapping[source.id] = target.id
    return mapping


def _remap(required: int | None, mapping: dict[int, int], field: str) -> int | None:
    """Resolve one version-local FK and reject incomplete source graph references."""

    if required is None:
        return None
    target = mapping.get(required)
    if target is None:
        raise ValueError(f"工程图克隆失败：{field}={required} 未在源版本映射中找到")
    return target


def _clone_case_name(source_name: str, target_version: str) -> str:
    """Keep the globally unique case-name constraint while preserving human context."""

    suffix = f" [{target_version}]"
    return f"{source_name[: max(1, 128 - len(suffix))]}{suffix}"


def _remap_case_configuration(
    configuration: dict[str, Any] | None,
    *,
    structures: dict[int, int],
    sections: dict[int, int],
) -> dict[str, Any] | None:
    """Remap explicit version-local structure and section selections in a Case.

    The public case configuration admits a structure selection and optional
    section-specific initial states.  Keeping source Version IDs in either field
    would create an apparently valid clone that later fails model construction.
    Other configuration keys are scalar solver settings and remain unchanged.
    """

    if configuration is None:
        return None
    cloned = deepcopy(configuration)
    if not isinstance(cloned, dict):
        raise ValueError("工程图克隆失败：hydraulic_1d_configuration 必须是对象")
    structures_config = cloned.get("structures")
    if isinstance(structures_config, dict) and isinstance(
        structures_config.get("structure_ids"), list
    ):
        structures_config["structure_ids"] = [
            _remap(int(source_id), structures, "configuration.structures.structure_ids")
            for source_id in structures_config["structure_ids"]
        ]
    initial = cloned.get("initial_condition")
    if isinstance(initial, dict) and isinstance(initial.get("by_section"), list):
        for item in initial["by_section"]:
            if not isinstance(item, dict) or "cross_section_id" not in item:
                raise ValueError("工程图克隆失败：initial_condition.by_section 缺少 cross_section_id")
            item["cross_section_id"] = str(
                _remap(int(item["cross_section_id"]), sections, "configuration.initial_condition")
            )
    return cloned


def clone_unified_engineering_graph(
    session: Session,
    *,
    source_version_id: int,
    target_version_id: int,
    target_version: str,
) -> None:
    """Clone every editable unified engineering input with new version-local IDs.

    The dependency order is deliberate: source evidence and network identities,
    then topology and survey geometry, then boundary/scenario controls.  Derived
    execution evidence is excluded so a clone cannot masquerade as a rerun.
    """

    import_jobs = _copy_family(
        session,
        HydraulicImportJob,
        HydraulicImportJob,
        source_version_id,
        target_version_id,
        mutate=lambda source, values: values.update(
            job_code=f"CLONE-{target_version_id}-{source.id}"[:32]
        ),
    )
    mapping_profiles = _copy_family(
        session,
        HydraulicImportMappingProfile,
        HydraulicImportMappingProfile,
        source_version_id,
        target_version_id,
    )
    networks = _copy_family(
        session,
        HydraulicNetwork,
        HydraulicNetwork,
        source_version_id,
        target_version_id,
    )
    nodes = _copy_family(
        session,
        HydraulicNode,
        HydraulicNode,
        source_version_id,
        target_version_id,
        mutate=lambda source, values: values.update(network_id=_remap(source.network_id, networks, "node.network_id")),
    )
    branches = _copy_family(
        session,
        HydraulicBranch,
        HydraulicBranch,
        source_version_id,
        target_version_id,
        mutate=lambda source, values: values.update(
            network_id=_remap(source.network_id, networks, "branch.network_id"),
            upstream_node_id=_remap(source.upstream_node_id, nodes, "branch.upstream_node_id"),
            downstream_node_id=_remap(source.downstream_node_id, nodes, "branch.downstream_node_id"),
            legacy_river_id=None,
        ),
    )
    _copy_family(
        session,
        HydraulicBranchVertex,
        HydraulicBranchVertex,
        source_version_id,
        target_version_id,
        mutate=lambda source, values: values.update(
            branch_id=_remap(source.branch_id, branches, "branch_vertex.branch_id"),
            import_job_id=_remap(source.import_job_id, import_jobs, "branch_vertex.import_job_id"),
        ),
    )
    _copy_family(
        session,
        HydraulicReach,
        HydraulicReach,
        source_version_id,
        target_version_id,
        mutate=lambda source, values: values.update(
            branch_id=_remap(source.branch_id, branches, "reach.branch_id"),
            upstream_node_id=_remap(source.upstream_node_id, nodes, "reach.upstream_node_id"),
            downstream_node_id=_remap(source.downstream_node_id, nodes, "reach.downstream_node_id"),
        ),
    )
    sections = _copy_family(
        session,
        HydraulicCrossSection,
        HydraulicCrossSection,
        source_version_id,
        target_version_id,
        mutate=lambda source, values: values.update(
            branch_id=_remap(source.branch_id, branches, "cross_section.branch_id"),
            legacy_cross_section_id=None,
        ),
    )
    profiles = _copy_family(
        session,
        HydraulicCrossSectionProfile,
        HydraulicCrossSectionProfile,
        source_version_id,
        target_version_id,
        mutate=lambda source, values: values.update(
            cross_section_id=_remap(source.cross_section_id, sections, "profile.cross_section_id"),
        ),
    )
    _copy_family(
        session,
        HydraulicCrossSectionPoint,
        HydraulicCrossSectionPoint,
        source_version_id,
        target_version_id,
        mutate=lambda source, values: values.update(
            profile_id=_remap(source.profile_id, profiles, "cross_section_point.profile_id"),
        ),
    )
    _copy_family(
        session,
        HydraulicRoughnessZone,
        HydraulicRoughnessZone,
        source_version_id,
        target_version_id,
        mutate=lambda source, values: values.update(
            profile_id=_remap(source.profile_id, profiles, "roughness_zone.profile_id"),
        ),
    )
    processing = _copy_family(
        session,
        HydraulicCrossSectionProcessing,
        HydraulicCrossSectionProcessing,
        source_version_id,
        target_version_id,
        mutate=lambda source, values: values.update(
            profile_id=_remap(source.profile_id, profiles, "processing.profile_id"),
        ),
    )
    _copy_family(
        session,
        HydraulicCrossSectionHydraulicRow,
        HydraulicCrossSectionHydraulicRow,
        source_version_id,
        target_version_id,
        mutate=lambda source, values: values.update(
            processing_id=_remap(source.processing_id, processing, "hydraulic_row.processing_id"),
        ),
    )
    structures = _copy_family(
        session,
        HydraulicStructure,
        HydraulicStructure,
        source_version_id,
        target_version_id,
        mutate=lambda source, values: values.update(
            network_id=_remap(source.network_id, networks, "structure.network_id"),
            branch_id=_remap(source.branch_id, branches, "structure.branch_id"),
            legacy_gate_id=None,
            legacy_pump_id=None,
        ),
    )
    _copy_family(
        session,
        ModelParameter,
        ModelParameter,
        source_version_id,
        target_version_id,
    )
    boundaries = _copy_family(
        session,
        BoundaryCondition,
        BoundaryCondition,
        source_version_id,
        target_version_id,
        mutate=lambda source, values: values.update(
            target_node_id=None,
            hydraulic_node_id=_remap(source.hydraulic_node_id, nodes, "boundary.hydraulic_node_id"),
            branch_id=_remap(source.branch_id, branches, "boundary.branch_id"),
        ),
    )
    cases: dict[int, int] = {}
    for source in session.scalars(
        select(SimulationCase)
        .where(SimulationCase.dataset_version_id == source_version_id)
        .order_by(SimulationCase.id)
    ).all():
        values = _row_values(source)
        values.update(
            dataset_version_id=target_version_id,
            name=_clone_case_name(source.name, target_version),
            boundary_condition_id=_remap(
                source.boundary_condition_id, boundaries, "simulation_case.boundary_condition_id"
            ),
            hydraulic_1d_configuration=_remap_case_configuration(
                source.hydraulic_1d_configuration,
                structures=structures,
                sections=sections,
            ),
        )
        target = SimulationCase(**values)
        session.add(target)
        session.flush()
        cases[source.id] = target.id
    for source in session.scalars(
        select(SimulationCaseBoundary)
        .join(SimulationCase, SimulationCase.id == SimulationCaseBoundary.case_id)
        .where(SimulationCase.dataset_version_id == source_version_id)
        .order_by(SimulationCaseBoundary.case_id, SimulationCaseBoundary.boundary_condition_id)
    ).all():
        session.add(
            SimulationCaseBoundary(
                case_id=_remap(source.case_id, cases, "simulation_case_boundary.case_id"),
                boundary_condition_id=_remap(
                    source.boundary_condition_id,
                    boundaries,
                    "simulation_case_boundary.boundary_condition_id",
                ),
                role=source.role,
            )
        )
    _copy_family(
        session,
        HydraulicStructureScenario,
        HydraulicStructureScenario,
        source_version_id,
        target_version_id,
        mutate=lambda source, values: values.update(
            structure_id=_remap(source.structure_id, structures, "structure_scenario.structure_id"),
            case_id=_remap(source.case_id, cases, "structure_scenario.case_id"),
        ),
    )
    _copy_family(
        session,
        HydraulicObservationSeries,
        HydraulicObservationSeries,
        source_version_id,
        target_version_id,
        mutate=lambda source, values: values.update(
            branch_id=_remap(source.branch_id, branches, "observation.branch_id"),
            mapping_profile_id=_remap(
                source.mapping_profile_id, mapping_profiles, "observation.mapping_profile_id"
            ),
        ),
    )
    _copy_family(
        session,
        HydraulicExternalResult,
        HydraulicExternalResult,
        source_version_id,
        target_version_id,
    )
    session.flush()
