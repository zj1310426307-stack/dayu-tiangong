"""RC1 ORM and additive migration metadata contracts."""

from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import CheckConstraint, ForeignKeyConstraint, UniqueConstraint

from app.gis.models import (
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


REPOSITORY_ROOT = Path(__file__).parents[2]
MIGRATION = (
    REPOSITORY_ROOT
    / "database"
    / "migrations"
    / "versions"
    / "20260828_0021_hydraulic_v4_rc1_consistency.py"
)


def _names(table: object, kind: type[object]) -> set[str]:
    """Return named constraints of one SQLAlchemy metadata kind."""

    return {
        constraint.name
        for constraint in table.constraints
        if isinstance(constraint, kind) and constraint.name is not None
    }


def test_rc1_task_attempt_artifact_and_shadow_constraints() -> None:
    """Expose distinct retry domains, lease identities, and recoverable states."""

    task = SimulationTask.__table__
    assert {
        "execution_attempt_count",
        "manual_retry_count",
        "infrastructure_retry_count",
        "numerical_retry_count",
        "active_execution_token",
        "last_execution_token",
        "last_infrastructure_error",
    }.issubset(task.columns.keys())
    for name in (
        "execution_attempt_count",
        "manual_retry_count",
        "infrastructure_retry_count",
        "numerical_retry_count",
    ):
        assert task.c[name].nullable is False
        assert str(task.c[name].server_default.arg) == "0"
    assert task.c.active_execution_token.type.length == 64
    assert task.c.last_execution_token.type.length == 64
    assert task.c.artifact_status.type.length == 32
    assert {
        "ck_simulation_task_counters_nonnegative",
        "ck_simulation_task_execution_token_length",
        "ck_simulation_task_artifact_status",
    } <= _names(task, CheckConstraint)
    assert "uq_simulation_task_group_role" in _names(task, UniqueConstraint)

    group = SimulationTaskGroup.__table__
    assert "ck_simulation_task_group_status" in _names(group, CheckConstraint)

    artifact = HydraulicTaskArtifact.__table__
    assert artifact.c.status.type.length == 32
    artifact_status = next(
        constraint
        for constraint in artifact.constraints
        if constraint.name == "ck_d2_artifact_status"
    )
    expression = str(artifact_status.sqltext)
    assert "reconciliation_required" in expression
    assert "orphaned" in expression


def test_rc1_result_rows_have_dataset_composite_identities() -> None:
    """Require every Section/Gate/Pump/Event asset to share its Dataset Version."""

    assert "uq_simulation_case_id_dataset" in _names(
        SimulationCase.__table__, UniqueConstraint
    )
    assert {
        "fk_simulation_task_case_dataset",
    } <= _names(SimulationTask.__table__, ForeignKeyConstraint)
    assert "uq_simulation_task_id_dataset" in _names(
        SimulationTask.__table__, UniqueConstraint
    )
    assert "uq_gate_id_version" in _names(Gate.__table__, UniqueConstraint)
    assert "uq_pump_id_version" in _names(Pump.__table__, UniqueConstraint)
    assert "fk_d2_section_result_branch_version" in _names(
        HydraulicTaskSectionResult.__table__, ForeignKeyConstraint
    )
    assert "fk_d2_section_result_task_dataset" in _names(
        HydraulicTaskSectionResult.__table__, ForeignKeyConstraint
    )
    assert "fk_d2_gate_result_gate_version" in _names(
        HydraulicTaskGateResult.__table__, ForeignKeyConstraint
    )
    assert "fk_d2_gate_result_task_dataset" in _names(
        HydraulicTaskGateResult.__table__, ForeignKeyConstraint
    )
    assert "fk_d2_pump_result_pump_version" in _names(
        HydraulicTaskPumpResult.__table__, ForeignKeyConstraint
    )
    assert "fk_d2_pump_result_task_dataset" in _names(
        HydraulicTaskPumpResult.__table__, ForeignKeyConstraint
    )

    event = HydraulicTaskControlEvent.__table__
    assert {
        "dataset_version_id",
        "canonical_gate_id",
        "canonical_pump_id",
        "canonical_structure_id",
    } <= set(event.columns.keys())
    assert {
        "fk_d2_control_event_gate_version",
        "fk_d2_control_event_pump_version",
        "fk_d2_control_event_task_dataset",
    } <= _names(event, ForeignKeyConstraint)
    assert {
        "ck_d2_control_event_structure_type",
        "ck_d2_control_event_typed_identity",
    } <= _names(event, CheckConstraint)
    assert "ix_d2_control_event_dataset_version" in {
        index.name for index in event.indexes
    }


def test_0021_is_the_single_reversible_head_with_fail_fast_guards() -> None:
    """Keep 0020 immutable while making 0021 the sole guarded migration head."""

    config = Config(str(REPOSITORY_ROOT / "database" / "alembic.ini"))
    script = ScriptDirectory.from_config(config)
    assert script.get_heads() == ["20260828_0021"]

    source = MIGRATION.read_text(encoding="utf-8")
    assert 'down_revision: str | None = "20260828_0020"' in source
    assert "def upgrade()" in source
    assert "def downgrade()" in source
    assert "_fail_fast_on_inconsistent_rows()" in source
    assert "does not match its Task Dataset" in source
    assert "invalid typed Dataset identity" in source
    assert "duplicate role" in source
    assert "downgrade blocked: reconcile RC1 Artifact states first" in source
