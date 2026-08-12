"""Add Phase 4 snapshots, hydraulic topology, dispatch and async lifecycle.

Revision ID: 20260812_0004
Revises: 20260812_0003
Create Date: 2026-08-12
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "20260812_0004"
down_revision: str | None = "20260812_0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _add_structure_topology() -> None:
    """扩展闸泵的明确水力拓扑和设备约束，不改写静态可用状态。"""

    gate_columns = (
        sa.Column("river_segment_id", sa.Integer(), nullable=True),
        sa.Column("station", sa.Float(), nullable=True),
        sa.Column("upstream_node_id", sa.Integer(), nullable=True),
        sa.Column("downstream_node_id", sa.Integer(), nullable=True),
        sa.Column("crest_elevation", sa.Float(), nullable=True),
        sa.Column("discharge_coefficient", sa.Float(), nullable=True),
        sa.Column("minimum_opening", sa.Float(), nullable=True),
        sa.Column("maximum_opening", sa.Float(), nullable=True),
        sa.Column("opening_rate_limit", sa.Float(), nullable=True),
        sa.Column("minimum_hold_seconds", sa.Float(), nullable=True),
        sa.Column("allow_reverse_flow", sa.Boolean(), server_default=sa.false(), nullable=False),
    )
    for column in gate_columns:
        op.add_column("gate", column)
    op.create_foreign_key(
        "fk_gate_river_segment_id", "gate", "river_segment", ["river_segment_id"], ["id"], ondelete="SET NULL"
    )
    op.create_foreign_key(
        "fk_gate_upstream_node_id", "gate", "river_node", ["upstream_node_id"], ["id"], ondelete="SET NULL"
    )
    op.create_foreign_key(
        "fk_gate_downstream_node_id", "gate", "river_node", ["downstream_node_id"], ["id"], ondelete="SET NULL"
    )

    pump_columns = (
        sa.Column("head_curve", sa.JSON(), nullable=True),
        sa.Column("intake_node_id", sa.Integer(), nullable=True),
        sa.Column("outlet_node_id", sa.Integer(), nullable=True),
        sa.Column("transfer_type", sa.String(24), nullable=True),
        sa.Column("unit_count", sa.Integer(), nullable=True),
        sa.Column("minimum_running_units", sa.Integer(), nullable=True),
        sa.Column("maximum_running_units", sa.Integer(), nullable=True),
        sa.Column("minimum_run_seconds", sa.Float(), nullable=True),
        sa.Column("minimum_stop_seconds", sa.Float(), nullable=True),
        sa.Column("maximum_starts_per_run", sa.Integer(), nullable=True),
        sa.Column("minimum_operating_head", sa.Float(), nullable=True),
        sa.Column("maximum_operating_head", sa.Float(), nullable=True),
        sa.Column("reverse_flow_protection", sa.Boolean(), server_default=sa.true(), nullable=False),
    )
    for column in pump_columns:
        op.add_column("pump", column)
    op.create_foreign_key(
        "fk_pump_intake_node_id", "pump", "river_node", ["intake_node_id"], ["id"], ondelete="SET NULL"
    )
    op.create_foreign_key(
        "fk_pump_outlet_node_id", "pump", "river_node", ["outlet_node_id"], ["id"], ondelete="SET NULL"
    )


def _add_task_provenance() -> None:
    """增加冻结快照、队列跟踪、心跳、取消和重试字段。"""

    op.create_table(
        "simulation_case_boundary",
        sa.Column("case_id", sa.Integer(), nullable=False),
        sa.Column("boundary_condition_id", sa.Integer(), nullable=False),
        sa.Column("role", sa.String(32), nullable=False),
        sa.Column("created_time", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["case_id"], ["simulation_case.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["boundary_condition_id"], ["boundary_condition.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("case_id", "boundary_condition_id"),
        sa.UniqueConstraint("case_id", "boundary_condition_id", name="uq_case_boundary_link"),
    )
    op.create_index("ix_simulation_case_boundary_case_id", "simulation_case_boundary", ["case_id"])
    op.execute(
        sa.text(
            """
            INSERT INTO simulation_case_boundary (case_id, boundary_condition_id, role)
            SELECT id, boundary_condition_id, 'legacy_primary'
            FROM simulation_case
            ON CONFLICT DO NOTHING
            """
        )
    )
    op.drop_constraint("ck_simulation_task_status", "simulation_task", type_="check")
    op.create_check_constraint(
        "ck_simulation_task_status",
        "simulation_task",
        "status IN ('pending', 'queued', 'running', 'cancel_requested', 'cancelled', 'success', 'failed')",
    )
    columns = (
        sa.Column("input_schema_version", sa.String(48), nullable=True),
        sa.Column("input_snapshot", sa.JSON(), nullable=True),
        sa.Column("input_snapshot_hash", sa.String(64), nullable=True),
        sa.Column("engine_version", sa.String(64), nullable=True),
        sa.Column("engine_commit", sa.String(64), nullable=True),
        sa.Column("queue_job_id", sa.String(128), nullable=True),
        sa.Column("worker_id", sa.String(128), nullable=True),
        sa.Column("queued_time", sa.DateTime(timezone=True), nullable=True),
        sa.Column("heartbeat_time", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cancel_requested", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("retry_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("retry_reason", sa.Text(), nullable=True),
        sa.Column("current_simulation_time", sa.Float(), nullable=True),
        sa.Column("current_cfl", sa.Float(), nullable=True),
    )
    for column in columns:
        op.add_column("simulation_task", column)
    op.create_index("ix_simulation_task_snapshot_hash", "simulation_task", ["input_snapshot_hash"])


def _create_dispatch_tables() -> None:
    """创建计划、动作、规则、运行、审计和模型结果表。"""

    op.create_table(
        "dispatch_plan",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("dataset_version_id", sa.Integer(), nullable=False),
        sa.Column("simulation_case_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        sa.Column("status", sa.String(16), server_default="draft", nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("duration_seconds", sa.Float(), nullable=False),
        sa.Column("evaluation_config", sa.JSON(), nullable=False),
        sa.Column("storage_level", sa.String(16), server_default="key_sections", nullable=False),
        sa.Column("created_by", sa.String(64), nullable=False),
        sa.Column("created_time", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_time", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("frozen_time", sa.DateTime(timezone=True), nullable=True),
        sa.Column("frozen_snapshot", sa.JSON(), nullable=True),
        sa.Column("frozen_snapshot_hash", sa.String(64), nullable=True),
        sa.CheckConstraint("status IN ('draft', 'validated', 'frozen', 'archived')", name="ck_dispatch_plan_status"),
        sa.CheckConstraint("storage_level IN ('summary', 'key_sections', 'full')", name="ck_dispatch_plan_storage_level"),
        sa.ForeignKeyConstraint(["dataset_version_id"], ["dataset_version.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["simulation_case_id"], ["simulation_case.id"], ondelete="RESTRICT"),
        sa.UniqueConstraint("name", "version", name="uq_dispatch_plan_name_version"),
    )
    op.create_index("ix_dispatch_plan_dataset_version_id", "dispatch_plan", ["dataset_version_id"])
    op.create_index("ix_dispatch_plan_status", "dispatch_plan", ["status"])

    op.create_table(
        "dispatch_action",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("plan_id", sa.Integer(), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("time_seconds", sa.Float(), nullable=False),
        sa.Column("structure_type", sa.String(16), nullable=False),
        sa.Column("gate_id", sa.Integer(), nullable=True),
        sa.Column("pump_id", sa.Integer(), nullable=True),
        sa.Column("command_type", sa.String(32), nullable=False),
        sa.Column("target_value", sa.Float(), nullable=False),
        sa.Column("interpolation", sa.String(16), server_default="step", nullable=False),
        sa.Column("priority", sa.Integer(), server_default="0", nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.CheckConstraint("structure_type IN ('gate', 'pump')", name="ck_dispatch_action_type"),
        sa.CheckConstraint("(gate_id IS NOT NULL AND pump_id IS NULL) OR (gate_id IS NULL AND pump_id IS NOT NULL)", name="ck_dispatch_action_single_asset"),
        sa.ForeignKeyConstraint(["plan_id"], ["dispatch_plan.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["gate_id"], ["gate.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["pump_id"], ["pump.id"], ondelete="RESTRICT"),
    )
    op.create_index("ix_dispatch_action_plan_time", "dispatch_action", ["plan_id", "time_seconds"])

    op.create_table(
        "dispatch_rule",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("plan_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("enabled", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column("observation_type", sa.String(32), nullable=False),
        sa.Column("observation_object_id", sa.Integer(), nullable=True),
        sa.Column("operator", sa.String(4), nullable=False),
        sa.Column("threshold", sa.Float(), nullable=False),
        sa.Column("hysteresis", sa.Float(), server_default="0", nullable=False),
        sa.Column("minimum_hold_seconds", sa.Float(), server_default="0", nullable=False),
        sa.Column("cooldown_seconds", sa.Float(), server_default="0", nullable=False),
        sa.Column("action_template", sa.JSON(), nullable=False),
        sa.Column("priority", sa.Integer(), server_default="0", nullable=False),
        sa.ForeignKeyConstraint(["plan_id"], ["dispatch_plan.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_dispatch_rule_plan_id", "dispatch_rule", ["plan_id"])

    op.create_table(
        "dispatch_run",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("plan_id", sa.Integer(), nullable=False),
        sa.Column("baseline_task_id", sa.Integer(), nullable=True),
        sa.Column("controlled_task_id", sa.Integer(), nullable=True),
        sa.Column("status", sa.String(24), server_default="pending", nullable=False),
        sa.Column("progress", sa.Integer(), server_default="0", nullable=False),
        sa.Column("metrics", sa.JSON(), nullable=True),
        sa.Column("queue_job_id", sa.String(128), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_time", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("start_time", sa.DateTime(timezone=True), nullable=True),
        sa.Column("end_time", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["plan_id"], ["dispatch_plan.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["baseline_task_id"], ["simulation_task.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["controlled_task_id"], ["simulation_task.id"], ondelete="SET NULL"),
    )
    op.create_index("ix_dispatch_run_plan_id", "dispatch_run", ["plan_id"])
    op.create_index("ix_dispatch_run_status", "dispatch_run", ["status"])

    op.create_table(
        "dispatch_event",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("run_id", sa.Integer(), nullable=False),
        sa.Column("time_seconds", sa.Float(), nullable=False),
        sa.Column("source_type", sa.String(16), nullable=False),
        sa.Column("source_id", sa.Integer(), nullable=True),
        sa.Column("structure_type", sa.String(16), nullable=False),
        sa.Column("structure_id", sa.Integer(), nullable=False),
        sa.Column("requested_command", sa.JSON(), nullable=False),
        sa.Column("applied_command", sa.JSON(), nullable=True),
        sa.Column("outcome", sa.String(16), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("created_time", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["run_id"], ["dispatch_run.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_dispatch_event_run_time", "dispatch_event", ["run_id", "time_seconds"])

    op.create_table(
        "structure_result",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("task_id", sa.Integer(), nullable=False),
        sa.Column("dispatch_run_id", sa.Integer(), nullable=True),
        sa.Column("time_seconds", sa.Float(), nullable=False),
        sa.Column("structure_type", sa.String(16), nullable=False),
        sa.Column("structure_id", sa.Integer(), nullable=False),
        sa.Column("requested_value", sa.Float(), nullable=True),
        sa.Column("actual_value", sa.Float(), nullable=True),
        sa.Column("flow", sa.Float(), nullable=False),
        sa.Column("upstream_level", sa.Float(), nullable=True),
        sa.Column("downstream_level", sa.Float(), nullable=True),
        sa.Column("power_kw", sa.Float(), nullable=True),
        sa.Column("energy_kwh", sa.Float(), nullable=True),
        sa.Column("regime", sa.String(32), nullable=True),
        sa.Column("constraint_flags", sa.JSON(), nullable=False),
        sa.ForeignKeyConstraint(["task_id"], ["simulation_task.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["dispatch_run_id"], ["dispatch_run.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("task_id", "time_seconds", "structure_type", "structure_id", name="uq_structure_result_task_time_asset"),
    )
    op.create_index("ix_structure_result_run_time", "structure_result", ["dispatch_run_id", "time_seconds"])

    op.create_table(
        "junction_result",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("task_id", sa.Integer(), nullable=False),
        sa.Column("node_id", sa.Integer(), nullable=False),
        sa.Column("time_seconds", sa.Float(), nullable=False),
        sa.Column("water_level", sa.Float(), nullable=False),
        sa.Column("inflow", sa.Float(), nullable=False),
        sa.Column("outflow", sa.Float(), nullable=False),
        sa.Column("source_sink", sa.Float(), nullable=False),
        sa.Column("balance_residual", sa.Float(), nullable=False),
        sa.ForeignKeyConstraint(["task_id"], ["simulation_task.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["node_id"], ["river_node.id"], ondelete="RESTRICT"),
        sa.UniqueConstraint("task_id", "node_id", "time_seconds", name="uq_junction_task_node_time"),
    )
    op.create_index("ix_junction_result_task_time", "junction_result", ["task_id", "time_seconds"])


def upgrade() -> None:
    """升级到 Phase 4 数据模型并保留全部既有记录。"""

    _add_structure_topology()
    _add_task_provenance()
    _create_dispatch_tables()


def downgrade() -> None:
    """移除 Phase 4 新表和列，恢复 Phase 3 状态约束。"""

    for table in (
        "junction_result", "structure_result", "dispatch_event", "dispatch_run",
        "dispatch_rule", "dispatch_action", "dispatch_plan",
    ):
        op.drop_table(table)
    op.drop_index("ix_simulation_task_snapshot_hash", table_name="simulation_task")
    for column in (
        "current_cfl", "current_simulation_time", "retry_reason", "retry_count",
        "cancel_requested", "heartbeat_time", "queued_time", "worker_id", "queue_job_id",
        "engine_commit", "engine_version", "input_snapshot_hash", "input_snapshot",
        "input_schema_version",
    ):
        op.drop_column("simulation_task", column)
    op.drop_constraint("ck_simulation_task_status", "simulation_task", type_="check")
    op.create_check_constraint(
        "ck_simulation_task_status", "simulation_task",
        "status IN ('pending', 'running', 'success', 'failed')",
    )
    op.drop_table("simulation_case_boundary")
    for constraint in ("fk_pump_outlet_node_id", "fk_pump_intake_node_id"):
        op.drop_constraint(constraint, "pump", type_="foreignkey")
    for column in (
        "reverse_flow_protection", "maximum_operating_head", "minimum_operating_head",
        "maximum_starts_per_run", "minimum_stop_seconds", "minimum_run_seconds",
        "maximum_running_units", "minimum_running_units", "unit_count", "transfer_type",
        "outlet_node_id", "intake_node_id", "head_curve",
    ):
        op.drop_column("pump", column)
    for constraint in (
        "fk_gate_downstream_node_id", "fk_gate_upstream_node_id", "fk_gate_river_segment_id",
    ):
        op.drop_constraint(constraint, "gate", type_="foreignkey")
    for column in (
        "allow_reverse_flow", "minimum_hold_seconds", "opening_rate_limit",
        "maximum_opening", "minimum_opening", "discharge_coefficient", "crest_elevation",
        "downstream_node_id", "upstream_node_id", "station", "river_segment_id",
    ):
        op.drop_column("gate", column)
