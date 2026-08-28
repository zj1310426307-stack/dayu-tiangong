"""Strengthen native-v4 execution, artifact, and Dataset identities.

Revision ID: 20260828_0021
Revises: 20260828_0020
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "20260828_0021"
down_revision: str | None = "20260828_0020"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_TASK_COUNTERS = (
    "execution_attempt_count",
    "manual_retry_count",
    "infrastructure_retry_count",
    "numerical_retry_count",
)


def _fail_fast_on_inconsistent_rows() -> None:
    """Reject pre-existing contradictions instead of blessing them with new FKs."""

    op.execute(
        """
        DO $$
        BEGIN
          IF EXISTS (
            SELECT 1
              FROM hydraulic_task_gate_result AS result
              LEFT JOIN simulation_task AS task ON task.id = result.task_id
              LEFT JOIN simulation_case AS simulation_case
                ON simulation_case.id = task.case_id
              LEFT JOIN gate AS asset
                ON asset.id = result.canonical_gate_id
               AND asset.dataset_version_id = result.dataset_version_id
             WHERE asset.id IS NULL
                OR simulation_case.id IS NULL
                OR simulation_case.dataset_version_id <> result.dataset_version_id
          ) THEN
            RAISE EXCEPTION '0021 preflight: Gate result does not match its Task Dataset';
          END IF;

          IF EXISTS (
            SELECT 1
              FROM hydraulic_task_pump_result AS result
              LEFT JOIN simulation_task AS task ON task.id = result.task_id
              LEFT JOIN simulation_case AS simulation_case
                ON simulation_case.id = task.case_id
              LEFT JOIN pump AS asset
                ON asset.id = result.canonical_pump_id
               AND asset.dataset_version_id = result.dataset_version_id
             WHERE asset.id IS NULL
                OR simulation_case.id IS NULL
                OR simulation_case.dataset_version_id <> result.dataset_version_id
          ) THEN
            RAISE EXCEPTION '0021 preflight: Pump result does not match its Task Dataset';
          END IF;

          IF EXISTS (
            SELECT 1
              FROM hydraulic_task_section_result AS result
              LEFT JOIN simulation_task AS task ON task.id = result.task_id
              LEFT JOIN simulation_case AS simulation_case
                ON simulation_case.id = task.case_id
              LEFT JOIN hydraulic.branch AS branch
                ON branch.id = result.branch_id
               AND branch.dataset_version_id = result.dataset_version_id
             WHERE branch.id IS NULL
                OR simulation_case.id IS NULL
                OR simulation_case.dataset_version_id <> result.dataset_version_id
          ) THEN
            RAISE EXCEPTION '0021 preflight: Section result does not match its Task Dataset';
          END IF;

          IF EXISTS (
            SELECT 1
              FROM hydraulic_task_control_event AS event
              LEFT JOIN simulation_task AS task ON task.id = event.task_id
              LEFT JOIN simulation_case AS simulation_case
                ON simulation_case.id = task.case_id
              LEFT JOIN gate AS gate_asset
                ON event.structure_type = 'gate'
               AND gate_asset.id = event.canonical_structure_id
               AND gate_asset.dataset_version_id = simulation_case.dataset_version_id
              LEFT JOIN pump AS pump_asset
                ON event.structure_type = 'pump'
               AND pump_asset.id = event.canonical_structure_id
               AND pump_asset.dataset_version_id = simulation_case.dataset_version_id
             WHERE task.id IS NULL
                OR simulation_case.id IS NULL
                OR event.structure_type NOT IN ('gate', 'pump')
                OR (event.structure_type = 'gate' AND gate_asset.id IS NULL)
                OR (event.structure_type = 'pump' AND pump_asset.id IS NULL)
          ) THEN
            RAISE EXCEPTION '0021 preflight: Control Event has an invalid typed Dataset identity';
          END IF;

          IF EXISTS (
            SELECT 1
              FROM simulation_task
             WHERE retry_count < 0
                OR accepted_step_count < 0
                OR cfl_reduction_count < 0
                OR positivity_retry_count < 0
                OR event_refinement_count < 0
                OR gate_solver_retry_count < 0
                OR pump_solver_retry_count < 0
                OR minimum_dt_failure_count < 0
          ) THEN
            RAISE EXCEPTION '0021 preflight: Simulation Task contains a negative counter';
          END IF;

          IF EXISTS (
            SELECT 1
              FROM simulation_task_group
             WHERE status NOT IN (
               'pending', 'running', 'ready', 'not_ready', 'failed', 'cancelled'
             )
          ) THEN
            RAISE EXCEPTION '0021 preflight: Simulation Task Group has an unknown status';
          END IF;

          IF EXISTS (
            SELECT 1
              FROM simulation_task
             WHERE comparison_group_id IS NOT NULL
               AND group_role IS NOT NULL
             GROUP BY comparison_group_id, group_role
            HAVING count(*) > 1
          ) THEN
            RAISE EXCEPTION '0021 preflight: Shadow Group contains a duplicate role';
          END IF;
        END
        $$
        """
    )


def _add_execution_attempt_state() -> None:
    """Add explicit lifecycle attempts without changing legacy retry_count values."""

    for name in _TASK_COUNTERS:
        op.add_column(
            "simulation_task",
            sa.Column(name, sa.Integer(), nullable=False, server_default="0"),
        )
    op.add_column(
        "simulation_task",
        sa.Column("active_execution_token", sa.String(length=64), nullable=True),
    )
    op.add_column(
        "simulation_task",
        sa.Column("last_execution_token", sa.String(length=64), nullable=True),
    )
    op.add_column(
        "simulation_task",
        sa.Column("last_infrastructure_error", sa.Text(), nullable=True),
    )
    op.create_check_constraint(
        "ck_simulation_task_counters_nonnegative",
        "simulation_task",
        "retry_count >= 0 AND execution_attempt_count >= 0 "
        "AND manual_retry_count >= 0 AND infrastructure_retry_count >= 0 "
        "AND numerical_retry_count >= 0 AND accepted_step_count >= 0 "
        "AND cfl_reduction_count >= 0 AND positivity_retry_count >= 0 "
        "AND event_refinement_count >= 0 AND gate_solver_retry_count >= 0 "
        "AND pump_solver_retry_count >= 0 AND minimum_dt_failure_count >= 0",
    )
    op.create_check_constraint(
        "ck_simulation_task_execution_token_length",
        "simulation_task",
        "(active_execution_token IS NULL OR length(active_execution_token) BETWEEN 1 AND 64) "
        "AND (last_execution_token IS NULL OR length(last_execution_token) BETWEEN 1 AND 64)",
    )


def _strengthen_artifact_and_group_state() -> None:
    """Make reconciliation states durable and shadow roles unambiguous."""

    op.drop_constraint(
        "ck_simulation_task_artifact_status", "simulation_task", type_="check"
    )
    op.alter_column(
        "simulation_task",
        "artifact_status",
        existing_type=sa.String(length=16),
        type_=sa.String(length=32),
        existing_nullable=True,
    )
    op.create_check_constraint(
        "ck_simulation_task_artifact_status",
        "simulation_task",
        "artifact_status IS NULL OR artifact_status IN "
        "('none','preparing','prepared','publishing','published','failed',"
        "'orphaned','reconciliation_required')",
    )

    op.drop_constraint("ck_d2_artifact_status", "hydraulic_task_artifact", type_="check")
    op.alter_column(
        "hydraulic_task_artifact",
        "status",
        existing_type=sa.String(length=16),
        type_=sa.String(length=32),
        existing_nullable=False,
    )
    op.create_check_constraint(
        "ck_d2_artifact_status",
        "hydraulic_task_artifact",
        "status IN ('prepared','publishing','published','failed','orphaned',"
        "'reconciliation_required')",
    )

    op.create_check_constraint(
        "ck_simulation_task_group_status",
        "simulation_task_group",
        "status IN ('pending','running','ready','not_ready','failed','cancelled')",
    )
    op.create_unique_constraint(
        "uq_simulation_task_group_role",
        "simulation_task",
        ["comparison_group_id", "group_role"],
    )


def _strengthen_result_dataset_identities() -> None:
    """Bind every native-v4 result identity to the same Dataset Version."""

    op.create_unique_constraint(
        "uq_simulation_case_id_dataset",
        "simulation_case",
        ["id", "dataset_version_id"],
    )
    op.add_column(
        "simulation_task",
        sa.Column("dataset_version_id", sa.Integer(), nullable=True),
    )
    op.execute(
        """
        UPDATE simulation_task AS task
           SET dataset_version_id = simulation_case.dataset_version_id
          FROM simulation_case
         WHERE simulation_case.id = task.case_id
        """
    )
    op.alter_column(
        "simulation_task",
        "dataset_version_id",
        existing_type=sa.Integer(),
        nullable=False,
    )
    op.create_foreign_key(
        "fk_simulation_task_case_dataset",
        "simulation_task",
        "simulation_case",
        ["case_id", "dataset_version_id"],
        ["id", "dataset_version_id"],
        ondelete="RESTRICT",
    )
    op.create_unique_constraint(
        "uq_simulation_task_id_dataset",
        "simulation_task",
        ["id", "dataset_version_id"],
    )
    op.create_index(
        "ix_simulation_task_dataset_version_id",
        "simulation_task",
        ["dataset_version_id"],
    )

    op.create_unique_constraint(
        "uq_gate_id_version", "gate", ["id", "dataset_version_id"]
    )
    op.create_unique_constraint(
        "uq_pump_id_version", "pump", ["id", "dataset_version_id"]
    )
    op.create_foreign_key(
        "fk_d2_gate_result_gate_version",
        "hydraulic_task_gate_result",
        "gate",
        ["canonical_gate_id", "dataset_version_id"],
        ["id", "dataset_version_id"],
        ondelete="RESTRICT",
    )
    op.create_foreign_key(
        "fk_d2_pump_result_pump_version",
        "hydraulic_task_pump_result",
        "pump",
        ["canonical_pump_id", "dataset_version_id"],
        ["id", "dataset_version_id"],
        ondelete="RESTRICT",
    )
    op.create_foreign_key(
        "fk_d2_section_result_branch_version",
        "hydraulic_task_section_result",
        "branch",
        ["branch_id", "dataset_version_id"],
        ["id", "dataset_version_id"],
        referent_schema="hydraulic",
        ondelete="RESTRICT",
    )
    for table, name in (
        ("hydraulic_task_section_result", "fk_d2_section_result_task_dataset"),
        ("hydraulic_task_gate_result", "fk_d2_gate_result_task_dataset"),
        ("hydraulic_task_pump_result", "fk_d2_pump_result_task_dataset"),
    ):
        op.create_foreign_key(
            name,
            table,
            "simulation_task",
            ["task_id", "dataset_version_id"],
            ["id", "dataset_version_id"],
            ondelete="CASCADE",
        )

    op.add_column(
        "hydraulic_task_control_event",
        sa.Column("dataset_version_id", sa.Integer(), nullable=True),
    )
    op.add_column(
        "hydraulic_task_control_event",
        sa.Column("canonical_gate_id", sa.Integer(), nullable=True),
    )
    op.add_column(
        "hydraulic_task_control_event",
        sa.Column("canonical_pump_id", sa.Integer(), nullable=True),
    )
    op.execute(
        """
        UPDATE hydraulic_task_control_event AS event
           SET dataset_version_id = simulation_case.dataset_version_id,
               canonical_gate_id = CASE
                 WHEN event.structure_type = 'gate' THEN event.canonical_structure_id
                 ELSE NULL
               END,
               canonical_pump_id = CASE
                 WHEN event.structure_type = 'pump' THEN event.canonical_structure_id
                 ELSE NULL
               END
          FROM simulation_task AS task
          JOIN simulation_case ON simulation_case.id = task.case_id
         WHERE task.id = event.task_id
        """
    )
    op.alter_column(
        "hydraulic_task_control_event",
        "dataset_version_id",
        existing_type=sa.Integer(),
        nullable=False,
    )
    op.create_foreign_key(
        "fk_d2_control_event_dataset_version",
        "hydraulic_task_control_event",
        "dataset_version",
        ["dataset_version_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_foreign_key(
        "fk_d2_control_event_task_dataset",
        "hydraulic_task_control_event",
        "simulation_task",
        ["task_id", "dataset_version_id"],
        ["id", "dataset_version_id"],
        ondelete="CASCADE",
    )
    op.create_foreign_key(
        "fk_d2_control_event_gate_version",
        "hydraulic_task_control_event",
        "gate",
        ["canonical_gate_id", "dataset_version_id"],
        ["id", "dataset_version_id"],
        ondelete="RESTRICT",
    )
    op.create_foreign_key(
        "fk_d2_control_event_pump_version",
        "hydraulic_task_control_event",
        "pump",
        ["canonical_pump_id", "dataset_version_id"],
        ["id", "dataset_version_id"],
        ondelete="RESTRICT",
    )
    op.create_check_constraint(
        "ck_d2_control_event_structure_type",
        "hydraulic_task_control_event",
        "structure_type IN ('gate','pump')",
    )
    op.create_check_constraint(
        "ck_d2_control_event_typed_identity",
        "hydraulic_task_control_event",
        "(structure_type = 'gate' AND canonical_gate_id IS NOT NULL "
        "AND canonical_pump_id IS NULL "
        "AND canonical_gate_id = canonical_structure_id) OR "
        "(structure_type = 'pump' AND canonical_pump_id IS NOT NULL "
        "AND canonical_gate_id IS NULL "
        "AND canonical_pump_id = canonical_structure_id)",
    )
    op.create_index(
        "ix_d2_control_event_dataset_version",
        "hydraulic_task_control_event",
        ["dataset_version_id"],
    )


def upgrade() -> None:
    """Install RC1 consistency fields and constraints without rewriting 0020."""

    _fail_fast_on_inconsistent_rows()
    _add_execution_attempt_state()
    _strengthen_artifact_and_group_state()
    _strengthen_result_dataset_identities()


def _require_legacy_artifact_states_for_downgrade() -> None:
    """Refuse a lossy status truncation when RC1 reconciliation is still active."""

    op.execute(
        """
        DO $$
        BEGIN
          IF EXISTS (
            SELECT 1 FROM simulation_task
             WHERE artifact_status IS NOT NULL
               AND artifact_status NOT IN ('none','preparing','prepared','published','failed')
          ) OR EXISTS (
            SELECT 1 FROM hydraulic_task_artifact
             WHERE status NOT IN ('prepared','published','failed')
          ) THEN
            RAISE EXCEPTION '0021 downgrade blocked: reconcile RC1 Artifact states first';
          END IF;
        END
        $$
        """
    )


def downgrade() -> None:
    """Remove RC1 strengthening while retaining every pre-0021 legacy column."""

    _require_legacy_artifact_states_for_downgrade()

    op.drop_index(
        "ix_d2_control_event_dataset_version",
        table_name="hydraulic_task_control_event",
    )
    for name, type_ in (
        ("ck_d2_control_event_typed_identity", "check"),
        ("ck_d2_control_event_structure_type", "check"),
        ("fk_d2_control_event_pump_version", "foreignkey"),
        ("fk_d2_control_event_gate_version", "foreignkey"),
        ("fk_d2_control_event_dataset_version", "foreignkey"),
    ):
        op.drop_constraint(name, "hydraulic_task_control_event", type_=type_)
    op.execute(
        "ALTER TABLE hydraulic_task_control_event "
        "DROP CONSTRAINT IF EXISTS fk_d2_control_event_task_dataset"
    )
    for name in ("canonical_pump_id", "canonical_gate_id", "dataset_version_id"):
        op.drop_column("hydraulic_task_control_event", name)

    op.drop_constraint(
        "fk_d2_section_result_branch_version",
        "hydraulic_task_section_result",
        type_="foreignkey",
    )
    for table, name in (
        ("hydraulic_task_pump_result", "fk_d2_pump_result_task_dataset"),
        ("hydraulic_task_gate_result", "fk_d2_gate_result_task_dataset"),
        ("hydraulic_task_section_result", "fk_d2_section_result_task_dataset"),
    ):
        op.execute(f"ALTER TABLE {table} DROP CONSTRAINT IF EXISTS {name}")
    op.drop_constraint(
        "fk_d2_pump_result_pump_version",
        "hydraulic_task_pump_result",
        type_="foreignkey",
    )
    op.drop_constraint(
        "fk_d2_gate_result_gate_version",
        "hydraulic_task_gate_result",
        type_="foreignkey",
    )
    op.drop_constraint("uq_pump_id_version", "pump", type_="unique")
    op.drop_constraint("uq_gate_id_version", "gate", type_="unique")

    op.execute("DROP INDEX IF EXISTS ix_simulation_task_dataset_version_id")
    op.execute(
        "ALTER TABLE simulation_task "
        "DROP CONSTRAINT IF EXISTS uq_simulation_task_id_dataset"
    )
    op.execute(
        "ALTER TABLE simulation_task "
        "DROP CONSTRAINT IF EXISTS fk_simulation_task_case_dataset"
    )
    op.execute("ALTER TABLE simulation_task DROP COLUMN IF EXISTS dataset_version_id")
    op.execute(
        "ALTER TABLE simulation_case "
        "DROP CONSTRAINT IF EXISTS uq_simulation_case_id_dataset"
    )

    op.drop_constraint(
        "uq_simulation_task_group_role", "simulation_task", type_="unique"
    )
    op.drop_constraint(
        "ck_simulation_task_group_status", "simulation_task_group", type_="check"
    )

    op.drop_constraint("ck_d2_artifact_status", "hydraulic_task_artifact", type_="check")
    op.alter_column(
        "hydraulic_task_artifact",
        "status",
        existing_type=sa.String(length=32),
        type_=sa.String(length=16),
        existing_nullable=False,
    )
    op.create_check_constraint(
        "ck_d2_artifact_status",
        "hydraulic_task_artifact",
        "status IN ('prepared','published','failed')",
    )

    op.drop_constraint(
        "ck_simulation_task_artifact_status", "simulation_task", type_="check"
    )
    op.alter_column(
        "simulation_task",
        "artifact_status",
        existing_type=sa.String(length=32),
        type_=sa.String(length=16),
        existing_nullable=True,
    )
    op.create_check_constraint(
        "ck_simulation_task_artifact_status",
        "simulation_task",
        "artifact_status IS NULL OR artifact_status IN "
        "('none','preparing','prepared','published','failed')",
    )

    op.drop_constraint(
        "ck_simulation_task_execution_token_length", "simulation_task", type_="check"
    )
    op.drop_constraint(
        "ck_simulation_task_counters_nonnegative", "simulation_task", type_="check"
    )
    for name in (
        "last_infrastructure_error",
        "last_execution_token",
        "active_execution_token",
        *_TASK_COUNTERS[::-1],
    ):
        op.drop_column("simulation_task", name)
