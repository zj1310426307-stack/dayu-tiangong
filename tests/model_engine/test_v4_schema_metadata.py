"""Additive D2 ORM and migration contract tests."""

from pathlib import Path

from app.gis.models import (
    BoundaryCondition,
    Gate,
    HydraulicTaskArtifact,
    HydraulicTaskControlEvent,
    HydraulicTaskGateResult,
    HydraulicTaskPumpResult,
    HydraulicTaskSectionResult,
    Pump,
    SimulationCase,
    SimulationTask,
    SimulationTaskGroup,
)


def test_d2_columns_are_additive_and_authoritative() -> None:
    """Expose explicit v4 identity/provenance fields without removing legacy columns."""

    assert "v4_configuration" in SimulationCase.__table__.columns
    assert "hydraulic_node_id" in BoundaryCondition.__table__.columns
    assert "hydraulic_upstream_section_id" in Gate.__table__.columns
    assert "hydraulic_downstream_section_id" in Gate.__table__.columns
    assert "hydraulic_section_id" in Pump.__table__.columns
    for name in (
        "solver_id",
        "capability_id",
        "runtime_adapter_id",
        "result_schema_version",
        "execution_phase",
        "runtime_projection_hash",
        "mesh_hash",
        "solver_policy_hash",
        "validation_policy_hash",
        "registry_hash",
    ):
        assert name in SimulationTask.__table__.columns
    assert "config" in SimulationTask.__table__.columns
    assert "input_snapshot" in SimulationTask.__table__.columns


def test_d2_result_artifact_and_shadow_tables_are_separate() -> None:
    """Keep native v4 output out of legacy SimulationResult and StructureResult."""

    assert SimulationTaskGroup.__tablename__ == "simulation_task_group"
    assert HydraulicTaskSectionResult.__tablename__ == "hydraulic_task_section_result"
    assert HydraulicTaskGateResult.__tablename__ == "hydraulic_task_gate_result"
    assert HydraulicTaskPumpResult.__tablename__ == "hydraulic_task_pump_result"
    assert HydraulicTaskControlEvent.__tablename__ == "hydraulic_task_control_event"
    artifact = HydraulicTaskArtifact.__table__
    assert artifact.name == "hydraulic_task_artifact"
    assert {"storage_key", "sha256", "record_count", "status"}.issubset(
        artifact.columns.keys()
    )


def test_0020_migration_has_single_head_and_reversible_d2_boundary() -> None:
    """Statically guard migration lineage; real PostGIS upgrade/downgrade is a separate gate."""

    source = (
        Path(__file__).parents[2]
        / "database"
        / "migrations"
        / "versions"
        / "20260828_0020_hydraulic_v4_task_chain.py"
    ).read_text(encoding="utf-8")
    assert 'down_revision: str | None = "20260818_0019"' in source
    assert "def upgrade()" in source
    assert "def downgrade()" in source
    assert "hydraulic_task_artifact" in source
    assert "simulation_result" not in source
