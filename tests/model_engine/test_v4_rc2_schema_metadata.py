"""RC2 ORM and reversible migration metadata contracts."""

from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import CheckConstraint

from app.gis.models import SimulationTask


REPOSITORY_ROOT = Path(__file__).parents[2]
MIGRATION = (
    REPOSITORY_ROOT
    / "database"
    / "migrations"
    / "versions"
    / "20260828_0022_hydraulic_runtime_build_identity.py"
)


def test_rc2_task_build_and_delivery_fields_are_durable() -> None:
    task = SimulationTask.__table__
    assert {
        "solver_build_id",
        "build_mode",
        "build_verified",
        "delivery_attempt_count",
        "last_delivery_time",
    } <= set(task.columns.keys())
    assert task.c.solver_build_id.type.length == 96
    assert task.c.build_mode.type.length == 16
    assert task.c.build_verified.nullable is False
    assert task.c.delivery_attempt_count.nullable is False
    assert str(task.c.delivery_attempt_count.server_default.arg) == "0"
    constraint_names = {
        item.name
        for item in task.constraints
        if isinstance(item, CheckConstraint) and item.name is not None
    }
    assert "ck_simulation_task_build_mode" in constraint_names
    assert "delivery_attempt_count >= 0" in str(
        next(
            item.sqltext
            for item in task.constraints
            if item.name == "ck_simulation_task_counters_nonnegative"
        )
    )
    assert "ix_simulation_task_queued_delivery_recovery" in {
        index.name for index in task.indexes
    }


def test_0022_is_the_single_reversible_migration_head() -> None:
    config = Config(str(REPOSITORY_ROOT / "database" / "alembic.ini"))
    script = ScriptDirectory.from_config(config)
    assert script.get_heads() == ["20260828_0022"]
    source = MIGRATION.read_text(encoding="utf-8")
    assert 'down_revision: str | None = "20260828_0021"' in source
    assert "def upgrade()" in source
    assert "def downgrade()" in source
    assert "build_verified = false" in source
    assert "ix_simulation_task_queued_delivery_recovery" in source
