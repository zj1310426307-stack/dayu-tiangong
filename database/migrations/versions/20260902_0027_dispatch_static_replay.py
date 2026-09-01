"""Harden deterministic Gate/Pump scheduling contracts.

Revision ID: 20260902_0027
Revises: 20260902_0026
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "20260902_0027"
down_revision: str | None = "20260902_0026"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add database-level action domains and nullable-safe conflict indexes."""

    # Never rewrite or discard legacy scheduling data in a schema migration.
    # Old APIs allowed these rows, so stop with actionable IDs before adding
    # constraints that would otherwise fail with an opaque database error.
    op.execute(
        """
        DO $dayu_dispatch_0027$
        DECLARE
            discrete_ids text;
            conflict_ids text;
        BEGIN
            SELECT string_agg(id::text, ',' ORDER BY id)
              INTO discrete_ids
              FROM dispatch_action
             WHERE command_type IN ('pump_enabled', 'pump_unit_count')
               AND interpolation <> 'step';
            IF discrete_ids IS NOT NULL THEN
                RAISE EXCEPTION USING
                    MESSAGE = format(
                        'DISPATCH_0027_PREFLIGHT_DISCRETE_INTERPOLATION ids=%s',
                        discrete_ids
                    ),
                    HINT = 'Review and explicitly replace each legacy linear '
                           'discrete action with a step action before retrying.';
            END IF;

            SELECT string_agg(action.id::text, ',' ORDER BY action.id)
              INTO conflict_ids
              FROM dispatch_action AS action
             WHERE EXISTS (
                SELECT 1
                  FROM dispatch_action AS other
                 WHERE other.id <> action.id
                   AND other.plan_id = action.plan_id
                   AND other.time_seconds = action.time_seconds
                   AND (
                        (action.gate_id IS NOT NULL AND other.gate_id = action.gate_id)
                     OR (action.pump_id IS NOT NULL AND other.pump_id = action.pump_id)
                   )
             );
            IF conflict_ids IS NOT NULL THEN
                RAISE EXCEPTION USING
                    MESSAGE = format(
                        'DISPATCH_0027_PREFLIGHT_ASSET_TIME_CONFLICT ids=%s',
                        conflict_ids
                    ),
                    HINT = 'Clone/review the affected plans and explicitly '
                           'resolve same-actuator same-time actions before retrying.';
            END IF;
        END;
        $dayu_dispatch_0027$
        """
    )
    op.create_check_constraint(
        "ck_dispatch_action_time_nonnegative",
        "dispatch_action",
        "time_seconds >= 0",
    )
    op.create_check_constraint(
        "ck_dispatch_action_interpolation",
        "dispatch_action",
        "interpolation IN ('step', 'linear')",
    )
    op.create_check_constraint(
        "ck_dispatch_action_command_type",
        "dispatch_action",
        "command_type IN ('gate_opening_m', 'gate_opening_ratio', "
        "'pump_enabled', 'pump_unit_count', 'pump_target_flow')",
    )
    op.create_check_constraint(
        "ck_dispatch_action_structure_command_asset",
        "dispatch_action",
        "(structure_type = 'gate' AND gate_id IS NOT NULL "
        "AND pump_id IS NULL AND command_type IN "
        "('gate_opening_m', 'gate_opening_ratio')) OR "
        "(structure_type = 'pump' AND pump_id IS NOT NULL "
        "AND gate_id IS NULL AND command_type IN "
        "('pump_enabled', 'pump_unit_count', 'pump_target_flow'))",
    )
    op.create_check_constraint(
        "ck_dispatch_action_discrete_step",
        "dispatch_action",
        "command_type NOT IN ('pump_enabled', 'pump_unit_count') "
        "OR interpolation = 'step'",
    )
    op.create_index(
        "uq_dispatch_action_gate_time",
        "dispatch_action",
        ["plan_id", "time_seconds", "gate_id"],
        unique=True,
        postgresql_where=sa.text("gate_id IS NOT NULL"),
    )
    op.create_index(
        "uq_dispatch_action_pump_time",
        "dispatch_action",
        ["plan_id", "time_seconds", "pump_id"],
        unique=True,
        postgresql_where=sa.text("pump_id IS NOT NULL"),
    )


def downgrade() -> None:
    """Remove only the additive static scheduling guards."""

    op.drop_index("uq_dispatch_action_pump_time", table_name="dispatch_action")
    op.drop_index("uq_dispatch_action_gate_time", table_name="dispatch_action")
    op.drop_constraint(
        "ck_dispatch_action_discrete_step", "dispatch_action", type_="check"
    )
    op.drop_constraint(
        "ck_dispatch_action_structure_command_asset",
        "dispatch_action",
        type_="check",
    )
    op.drop_constraint(
        "ck_dispatch_action_command_type", "dispatch_action", type_="check"
    )
    op.drop_constraint(
        "ck_dispatch_action_interpolation", "dispatch_action", type_="check"
    )
    op.drop_constraint(
        "ck_dispatch_action_time_nonnegative", "dispatch_action", type_="check"
    )
