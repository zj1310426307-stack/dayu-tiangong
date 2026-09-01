"""Add unified structures, scenario overrides, and engineering node roles.

Revision ID: 20260901_0025
Revises: 20260831_0024
"""

from collections.abc import Sequence

from alembic import op
from geoalchemy2 import Geometry
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "20260901_0025"
down_revision: str | None = "20260831_0024"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create additive engineering objects and preserve legacy Gate/Pump rows."""

    op.drop_constraint(
        "ck_hydraulic_node_type", "node", schema="hydraulic", type_="check"
    )
    op.create_check_constraint(
        "ck_hydraulic_node_type",
        "node",
        "node_type IN ('boundary','junction','bifurcation','internal',"
        "'storage_connection','structure','lateral','unknown')",
        schema="hydraulic",
    )
    op.create_unique_constraint(
        "uq_hydraulic_branch_id_network_version",
        "branch",
        ["id", "network_id", "dataset_version_id"],
        schema="hydraulic",
    )
    op.create_table(
        "structure",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("dataset_version_id", sa.Integer(), nullable=False),
        sa.Column("network_id", sa.Integer(), nullable=False),
        sa.Column("branch_id", sa.Integer(), nullable=False),
        sa.Column("structure_code", sa.String(64), nullable=False),
        sa.Column("structure_name", sa.String(128), nullable=False),
        sa.Column("structure_type", sa.String(32), nullable=False),
        sa.Column("chainage_m", sa.Float(), nullable=False),
        sa.Column(
            "location",
            Geometry("POINT", srid=4490, spatial_index=False),
            nullable=False,
        ),
        sa.Column("crest_elevation_m", sa.Float()),
        sa.Column("invert_elevation_m", sa.Float()),
        sa.Column("width_m", sa.Float()),
        sa.Column("height_m", sa.Float()),
        sa.Column(
            "hydraulic_law_type", sa.String(64), nullable=False, server_default="none"
        ),
        sa.Column(
            "hydraulic_parameters",
            postgresql.JSONB(),
            nullable=False,
            server_default="{}",
        ),
        sa.Column(
            "operation_rule_type", sa.String(32), nullable=False, server_default="fixed"
        ),
        sa.Column(
            "operation_parameters",
            postgresql.JSONB(),
            nullable=False,
            server_default="{}",
        ),
        sa.Column("status", sa.String(16), nullable=False, server_default="draft"),
        sa.Column(
            "metadata_json", postgresql.JSONB(), nullable=False, server_default="{}"
        ),
        sa.Column(
            "legacy_gate_id",
            sa.Integer(),
            sa.ForeignKey("gate.id", ondelete="SET NULL"),
        ),
        sa.Column(
            "legacy_pump_id",
            sa.Integer(),
            sa.ForeignKey("pump.id", ondelete="SET NULL"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint(
            "structure_type IN ('weir','culvert','bridge','gate','sluice','pump',"
            "'orifice','dam','storage_link','compound')",
            name="ck_hydraulic_structure_type",
        ),
        sa.CheckConstraint("chainage_m >= 0", name="ck_hydraulic_structure_chainage"),
        sa.CheckConstraint(
            "width_m IS NULL OR width_m > 0", name="ck_hydraulic_structure_width"
        ),
        sa.CheckConstraint(
            "height_m IS NULL OR height_m > 0", name="ck_hydraulic_structure_height"
        ),
        sa.CheckConstraint(
            "operation_rule_type IN ('fixed','time_series','water_level_controlled','scenario_specific')",
            name="ck_hydraulic_structure_operation_rule",
        ),
        sa.CheckConstraint(
            "status IN ('draft','active','inactive','retired')",
            name="ck_hydraulic_structure_status",
        ),
        sa.ForeignKeyConstraint(
            ["network_id", "dataset_version_id"],
            ["hydraulic.network.id", "hydraulic.network.dataset_version_id"],
            name="fk_hydraulic_structure_network_version",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["branch_id", "network_id", "dataset_version_id"],
            [
                "hydraulic.branch.id",
                "hydraulic.branch.network_id",
                "hydraulic.branch.dataset_version_id",
            ],
            name="fk_hydraulic_structure_branch_network_version",
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint(
            "id", "dataset_version_id", name="uq_hydraulic_structure_id_version"
        ),
        sa.UniqueConstraint(
            "dataset_version_id",
            "network_id",
            "structure_code",
            name="uq_hydraulic_structure_version_network_code",
        ),
        sa.UniqueConstraint(
            "legacy_gate_id", name="uq_hydraulic_structure_legacy_gate"
        ),
        sa.UniqueConstraint(
            "legacy_pump_id", name="uq_hydraulic_structure_legacy_pump"
        ),
        schema="hydraulic",
    )
    op.create_index(
        "ix_hydraulic_structure_geometry_gist",
        "structure",
        ["location"],
        schema="hydraulic",
        postgresql_using="gist",
    )
    op.create_index(
        "ix_hydraulic_structure_branch",
        "structure",
        ["branch_id", "chainage_m"],
        schema="hydraulic",
    )
    op.create_table(
        "structure_scenario",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("dataset_version_id", sa.Integer(), nullable=False),
        sa.Column("case_id", sa.Integer(), nullable=False),
        sa.Column("structure_id", sa.Integer(), nullable=False),
        sa.Column("status_override", sa.String(16)),
        sa.Column(
            "hydraulic_parameters_override",
            postgresql.JSONB(),
            nullable=False,
            server_default="{}",
        ),
        sa.Column("operation_rule_type_override", sa.String(32)),
        sa.Column(
            "operation_parameters_override",
            postgresql.JSONB(),
            nullable=False,
            server_default="{}",
        ),
        sa.Column(
            "metadata_json", postgresql.JSONB(), nullable=False, server_default="{}"
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint(
            "status_override IS NULL OR status_override IN ('draft','active','inactive','retired')",
            name="ck_hydraulic_structure_scenario_status",
        ),
        sa.ForeignKeyConstraint(
            ["structure_id", "dataset_version_id"],
            ["hydraulic.structure.id", "hydraulic.structure.dataset_version_id"],
            name="fk_hydraulic_structure_scenario_structure_version",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["case_id", "dataset_version_id"],
            ["simulation_case.id", "simulation_case.dataset_version_id"],
            name="fk_hydraulic_structure_scenario_case_version",
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint(
            "case_id", "structure_id", name="uq_hydraulic_structure_scenario_case"
        ),
        schema="hydraulic",
    )
    op.create_index(
        "ix_hydraulic_structure_scenario_case",
        "structure_scenario",
        ["case_id"],
        schema="hydraulic",
    )
    _backfill_legacy_structures()
    _grant_runtime_roles()


def _backfill_legacy_structures() -> None:
    """Copy resolvable legacy assets while retaining every original source row."""

    op.execute(
        """
        INSERT INTO hydraulic.structure
            (dataset_version_id, network_id, branch_id, structure_code,
             structure_name, structure_type, chainage_m, location,
             crest_elevation_m, invert_elevation_m, width_m, height_m,
             hydraulic_law_type, hydraulic_parameters, operation_rule_type,
             operation_parameters, status, metadata_json, legacy_gate_id)
        SELECT gate.dataset_version_id, branch.network_id, branch.id,
               'LEGACY-GATE-' || gate.id, gate.name, 'gate',
               CASE
                 WHEN gate.station BETWEEN branch.chainage_start_m AND branch.chainage_end_m
                   THEN gate.station
                 ELSE branch.chainage_start_m +
                      ST_LineLocatePoint(branch.centerline, gate.geometry) *
                      (branch.chainage_end_m - branch.chainage_start_m)
               END,
               ST_ClosestPoint(branch.centerline, gate.geometry),
               gate.crest_elevation, gate.bottom_elevation,
               gate.width, gate.height, 'legacy_gate',
               jsonb_build_object(
                   'discharge_coefficient', gate.discharge_coefficient,
                   'maximum_flow_m3s', gate.max_flow,
                   'allow_reverse_flow', gate.allow_reverse_flow
               ),
               CASE WHEN gate.control_mode = 'time_series' THEN 'time_series'
                    ELSE 'scenario_specific' END,
               jsonb_build_object(
                   'minimum_opening_m', gate.minimum_opening,
                   'maximum_opening_m', gate.maximum_opening,
                   'opening_rate_limit', gate.opening_rate_limit
               ),
               CASE WHEN gate.status = 'online' THEN 'active' ELSE 'inactive' END,
               jsonb_build_object(
                   'migration', '20260901_0025',
                   'legacy_status', gate.status,
                   'solver_capability', 'UNSUPPORTED'
               ), gate.id
          FROM public.gate AS gate
          JOIN hydraulic.branch AS branch
            ON branch.legacy_river_id = gate.river_id
           AND branch.dataset_version_id = gate.dataset_version_id
        """
    )
    op.execute(
        """
        INSERT INTO hydraulic.structure
            (dataset_version_id, network_id, branch_id, structure_code,
             structure_name, structure_type, chainage_m, location,
             hydraulic_law_type, hydraulic_parameters, operation_rule_type,
             operation_parameters, status, metadata_json, legacy_pump_id)
        SELECT pump.dataset_version_id, branch.network_id, branch.id,
               'LEGACY-PUMP-' || pump.id, pump.name, 'pump',
               branch.chainage_start_m +
               ST_LineLocatePoint(branch.centerline, pump.geometry) *
               (branch.chainage_end_m - branch.chainage_start_m),
               ST_ClosestPoint(branch.centerline, pump.geometry), 'pump_curve',
               jsonb_build_object(
                   'design_flow_m3s', pump.design_flow,
                   'head_m', pump.head,
                   'head_curve', pump.head_curve,
                   'efficiency_curve', pump.efficiency_curve
               ),
               CASE WHEN pump.control_mode = 'time_series' THEN 'time_series'
                    ELSE 'scenario_specific' END,
               jsonb_build_object(
                   'unit_count', pump.unit_count,
                   'minimum_running_units', pump.minimum_running_units,
                   'maximum_running_units', pump.maximum_running_units
               ),
               CASE WHEN pump.status = 'online' THEN 'active' ELSE 'inactive' END,
               jsonb_build_object(
                   'migration', '20260901_0025',
                   'legacy_status', pump.status,
                   'solver_capability', 'UNSUPPORTED'
               ), pump.id
          FROM public.pump AS pump
          JOIN hydraulic.branch AS branch
            ON branch.legacy_river_id = pump.river_id
           AND branch.dataset_version_id = pump.dataset_version_id
        """
    )


def _grant_runtime_roles() -> None:
    """Match the existing least-privilege hydraulic schema role policy."""

    op.execute(
        """
        DO $$
        BEGIN
          IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'dayu_backend') THEN
            GRANT SELECT, INSERT, UPDATE, DELETE
              ON hydraulic.structure, hydraulic.structure_scenario TO dayu_backend;
            GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA hydraulic TO dayu_backend;
          END IF;
          IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'dayu_qgis_reviewer') THEN
            GRANT SELECT
              ON hydraulic.structure, hydraulic.structure_scenario TO dayu_qgis_reviewer;
          END IF;
        END $$
        """
    )


def downgrade() -> None:
    """Remove only Engineering-03 copies and restore the prior node-role constraint."""

    op.drop_table("structure_scenario", schema="hydraulic")
    op.drop_table("structure", schema="hydraulic")
    op.drop_constraint(
        "uq_hydraulic_branch_id_network_version",
        "branch",
        schema="hydraulic",
        type_="unique",
    )
    op.drop_constraint(
        "ck_hydraulic_node_type", "node", schema="hydraulic", type_="check"
    )
    op.execute(
        """
        UPDATE hydraulic.node
           SET node_type = CASE
               WHEN node_type = 'bifurcation' THEN 'junction'
               WHEN node_type IN ('internal', 'storage_connection') THEN 'unknown'
               ELSE node_type
           END
         WHERE node_type IN ('bifurcation', 'internal', 'storage_connection')
        """
    )
    op.create_check_constraint(
        "ck_hydraulic_node_type",
        "node",
        "node_type IN ('boundary','junction','structure','lateral','unknown')",
        schema="hydraulic",
    )
