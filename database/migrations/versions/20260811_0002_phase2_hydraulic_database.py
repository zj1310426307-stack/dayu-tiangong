"""升级为 Phase 2 版本化水利数据库。

修订号：20260811_0002
上一修订：20260811_0001
创建时间：2026-08-11
"""

from collections.abc import Sequence

from alembic import op
from geoalchemy2 import Geometry
import sqlalchemy as sa


revision: str = "20260811_0002"
down_revision: str | None = "20260811_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """无损扩展 Phase 1 四类对象，并建立拓扑、版本和模型输入表。"""

    op.create_table(
        "dataset_version",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("version", sa.String(length=32), nullable=False),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("creator", sa.String(length=64), nullable=False),
        sa.Column(
            "created_time",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name="pk_dataset_version"),
        sa.UniqueConstraint("version", name="uq_dataset_version_version"),
    )
    op.execute(
        """
        INSERT INTO dataset_version (id, version, name, description, creator)
        VALUES (1, 'V1.0', '2026现状河网（DEMO）',
                'Phase 1 DEMO DATA 迁移基线，不代表真实工程。', 'Codex DEMO')
        """
    )
    op.execute("SELECT setval(pg_get_serial_sequence('dataset_version', 'id'), 1, true)")

    op.drop_constraint("uq_river_code", "river", type_="unique")
    op.drop_constraint("uq_river_name", "river", type_="unique")
    op.add_column("river", sa.Column("dataset_version_id", sa.Integer(), nullable=True))
    op.add_column(
        "river", sa.Column("level", sa.String(length=32), server_default="main", nullable=True)
    )
    op.add_column(
        "river", sa.Column("status", sa.String(length=24), server_default="active", nullable=True)
    )
    op.execute("UPDATE river SET dataset_version_id = 1, level = 'main', status = 'active'")
    op.alter_column("river", "dataset_version_id", nullable=False)
    op.alter_column("river", "level", nullable=False, server_default=None)
    op.alter_column("river", "status", nullable=False)
    op.create_foreign_key(
        "fk_river_dataset_version_id",
        "river",
        "dataset_version",
        ["dataset_version_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_unique_constraint(
        "uq_river_version_code", "river", ["dataset_version_id", "code"]
    )
    op.create_check_constraint(
        "ck_river_status", "river", "status IN ('active', 'inactive', 'planned')"
    )
    op.create_index("ix_river_dataset_version_id", "river", ["dataset_version_id"])

    op.drop_constraint("uq_cross_section_river_station", "cross_section", type_="unique")
    op.alter_column("cross_section", "elevation_points", new_column_name="points")
    op.add_column("cross_section", sa.Column("dataset_version_id", sa.Integer(), nullable=True))
    op.add_column("cross_section", sa.Column("section_code", sa.String(length=64), nullable=True))
    op.add_column("cross_section", sa.Column("section_name", sa.String(length=128), nullable=True))
    op.add_column("cross_section", sa.Column("elevation_min", sa.Float(), nullable=True))
    op.add_column("cross_section", sa.Column("survey_date", sa.Date(), nullable=True))
    op.execute(
        """
        UPDATE cross_section
        SET dataset_version_id = 1,
            section_code = 'DEMO-CS-' || lpad(id::text, 3, '0'),
            section_name = 'DEMO 横断面 ' || lpad(id::text, 3, '0'),
            roughness = COALESCE(roughness, 0.035),
            elevation_min = (
                SELECT min((point_value->>1)::double precision)
                FROM json_array_elements(points->'points') AS point_value
            )
        """
    )
    op.alter_column("cross_section", "dataset_version_id", nullable=False)
    op.alter_column("cross_section", "section_code", nullable=False)
    op.alter_column("cross_section", "section_name", nullable=False)
    op.alter_column("cross_section", "roughness", nullable=False)
    op.alter_column("cross_section", "elevation_min", nullable=False)
    op.create_foreign_key(
        "fk_cross_section_dataset_version_id",
        "cross_section",
        "dataset_version",
        ["dataset_version_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_unique_constraint(
        "uq_cross_section_version_code",
        "cross_section",
        ["dataset_version_id", "section_code"],
    )
    op.create_unique_constraint(
        "uq_cross_section_version_river_station",
        "cross_section",
        ["dataset_version_id", "river_id", "station"],
    )
    op.create_index(
        "ix_cross_section_dataset_version_id", "cross_section", ["dataset_version_id"]
    )

    op.drop_constraint("uq_gate_name", "gate", type_="unique")
    op.add_column("gate", sa.Column("dataset_version_id", sa.Integer(), nullable=True))
    op.add_column("gate", sa.Column("gate_code", sa.String(length=64), nullable=True))
    op.add_column("gate", sa.Column("opening_direction", sa.String(length=32), nullable=True))
    op.add_column("gate", sa.Column("control_mode", sa.String(length=32), nullable=True))
    op.add_column("gate", sa.Column("max_flow", sa.Float(), nullable=True))
    op.add_column("gate", sa.Column("bottom_elevation", sa.Float(), nullable=True))
    op.execute(
        """
        UPDATE gate
        SET dataset_version_id = 1,
            gate_code = 'DEMO-GATE-' || lpad(id::text, 3, '0'),
            opening_direction = 'vertical',
            control_mode = 'local',
            max_flow = width * height * 1.2,
            bottom_elevation = 5.0
        """
    )
    for column in (
        "dataset_version_id",
        "gate_code",
        "opening_direction",
        "control_mode",
        "max_flow",
        "bottom_elevation",
    ):
        op.alter_column("gate", column, nullable=False)
    op.create_foreign_key(
        "fk_gate_dataset_version_id",
        "gate",
        "dataset_version",
        ["dataset_version_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_unique_constraint(
        "uq_gate_version_code", "gate", ["dataset_version_id", "gate_code"]
    )
    op.create_check_constraint("ck_gate_max_flow_nonnegative", "gate", "max_flow >= 0")
    op.create_index("ix_gate_dataset_version_id", "gate", ["dataset_version_id"])

    op.drop_constraint("uq_pump_name", "pump", type_="unique")
    op.drop_constraint("ck_pump_capacity_nonnegative", "pump", type_="check")
    op.alter_column("pump", "capacity", new_column_name="design_flow")
    op.add_column("pump", sa.Column("dataset_version_id", sa.Integer(), nullable=True))
    op.add_column("pump", sa.Column("pump_code", sa.String(length=64), nullable=True))
    op.add_column("pump", sa.Column("head", sa.Float(), nullable=True))
    op.add_column(
        "pump", sa.Column("efficiency_curve", sa.JSON(), server_default=sa.text("'{}'::json"), nullable=True)
    )
    op.add_column("pump", sa.Column("control_mode", sa.String(length=32), nullable=True))
    op.execute(
        """
        UPDATE pump
        SET dataset_version_id = 1,
            pump_code = 'DEMO-PUMP-' || lpad(id::text, 3, '0'),
            head = 6.0,
            efficiency_curve = '{"points": [[0.0, 0.0], [0.5, 0.78], [1.0, 0.84]]}'::json,
            control_mode = 'local'
        """
    )
    for column in (
        "dataset_version_id",
        "pump_code",
        "head",
        "efficiency_curve",
        "control_mode",
    ):
        op.alter_column("pump", column, nullable=False)
    op.alter_column("pump", "efficiency_curve", server_default=None)
    op.create_foreign_key(
        "fk_pump_dataset_version_id",
        "pump",
        "dataset_version",
        ["dataset_version_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_unique_constraint(
        "uq_pump_version_code", "pump", ["dataset_version_id", "pump_code"]
    )
    op.create_check_constraint(
        "ck_pump_design_flow_nonnegative", "pump", "design_flow >= 0"
    )
    op.create_check_constraint("ck_pump_head_nonnegative", "pump", "head >= 0")
    op.create_index("ix_pump_dataset_version_id", "pump", ["dataset_version_id"])

    op.create_table(
        "river_node",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("dataset_version_id", sa.Integer(), nullable=False),
        sa.Column("node_code", sa.String(length=64), nullable=False),
        sa.Column("node_type", sa.String(length=24), nullable=False),
        sa.Column("longitude", sa.Float(), nullable=False),
        sa.Column("latitude", sa.Float(), nullable=False),
        sa.Column(
            "geometry",
            Geometry(geometry_type="POINT", srid=4326, spatial_index=False),
            nullable=False,
        ),
        sa.CheckConstraint("longitude BETWEEN -180 AND 180", name="ck_river_node_longitude"),
        sa.CheckConstraint("latitude BETWEEN -90 AND 90", name="ck_river_node_latitude"),
        sa.CheckConstraint(
            "node_type IN ('start', 'end', 'confluence', 'bifurcation', 'gate_control')",
            name="ck_river_node_type",
        ),
        sa.ForeignKeyConstraint(
            ["dataset_version_id"],
            ["dataset_version.id"],
            name="fk_river_node_dataset_version_id",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_river_node"),
        sa.UniqueConstraint(
            "dataset_version_id", "node_code", name="uq_river_node_version_code"
        ),
    )
    op.create_index(
        "ix_river_node_geometry_gist", "river_node", ["geometry"], postgresql_using="gist"
    )
    op.create_index(
        "ix_river_node_dataset_version_id", "river_node", ["dataset_version_id"]
    )

    op.create_table(
        "river_segment",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("dataset_version_id", sa.Integer(), nullable=False),
        sa.Column("river_id", sa.Integer(), nullable=False),
        sa.Column("segment_code", sa.String(length=64), nullable=False),
        sa.Column("upstream_node_id", sa.Integer(), nullable=False),
        sa.Column("downstream_node_id", sa.Integer(), nullable=False),
        sa.Column("length", sa.Float(), nullable=False),
        sa.Column(
            "geometry",
            Geometry(geometry_type="LINESTRING", srid=4326, spatial_index=False),
            nullable=False,
        ),
        sa.CheckConstraint("length >= 0", name="ck_river_segment_length_nonnegative"),
        sa.ForeignKeyConstraint(
            ["dataset_version_id"],
            ["dataset_version.id"],
            name="fk_river_segment_dataset_version_id",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["river_id"], ["river.id"], name="fk_river_segment_river_id", ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["upstream_node_id"],
            ["river_node.id"],
            name="fk_river_segment_upstream_node_id",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["downstream_node_id"],
            ["river_node.id"],
            name="fk_river_segment_downstream_node_id",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_river_segment"),
        sa.UniqueConstraint(
            "dataset_version_id", "segment_code", name="uq_river_segment_version_code"
        ),
    )
    op.create_index(
        "ix_river_segment_geometry_gist",
        "river_segment",
        ["geometry"],
        postgresql_using="gist",
    )
    op.create_index("ix_river_segment_river_id", "river_segment", ["river_id"])

    op.create_table(
        "river_connection",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("dataset_version_id", sa.Integer(), nullable=False),
        sa.Column("from_node_id", sa.Integer(), nullable=False),
        sa.Column("to_node_id", sa.Integer(), nullable=False),
        sa.Column("river_id", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(
            ["dataset_version_id"],
            ["dataset_version.id"],
            name="fk_river_connection_dataset_version_id",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["from_node_id"],
            ["river_node.id"],
            name="fk_river_connection_from_node_id",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["to_node_id"],
            ["river_node.id"],
            name="fk_river_connection_to_node_id",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["river_id"],
            ["river.id"],
            name="fk_river_connection_river_id",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_river_connection"),
        sa.UniqueConstraint(
            "dataset_version_id",
            "from_node_id",
            "to_node_id",
            "river_id",
            name="uq_river_connection_edge",
        ),
    )
    op.create_index("ix_river_connection_river_id", "river_connection", ["river_id"])
    op.create_index(
        "ix_river_connection_from_node_id", "river_connection", ["from_node_id"]
    )
    op.create_index("ix_river_connection_to_node_id", "river_connection", ["to_node_id"])

    op.create_table(
        "model_parameter",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("dataset_version_id", sa.Integer(), nullable=False),
        sa.Column("parameter_type", sa.String(length=64), nullable=False),
        sa.Column("parameter_name", sa.String(length=128), nullable=False),
        sa.Column("value", sa.Float(), nullable=False),
        sa.Column("unit", sa.String(length=32), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(
            ["dataset_version_id"],
            ["dataset_version.id"],
            name="fk_model_parameter_dataset_version_id",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_model_parameter"),
        sa.UniqueConstraint(
            "dataset_version_id",
            "parameter_type",
            "parameter_name",
            name="uq_model_parameter_version_name",
        ),
    )
    op.create_index(
        "ix_model_parameter_dataset_version_id", "model_parameter", ["dataset_version_id"]
    )

    op.create_table(
        "boundary_condition",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("dataset_version_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("boundary_type", sa.String(length=64), nullable=False),
        sa.Column("target_node_id", sa.Integer(), nullable=True),
        sa.Column("values", sa.JSON(), nullable=False),
        sa.Column("unit", sa.String(length=32), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(
            ["dataset_version_id"],
            ["dataset_version.id"],
            name="fk_boundary_condition_dataset_version_id",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["target_node_id"],
            ["river_node.id"],
            name="fk_boundary_condition_target_node_id",
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_boundary_condition"),
        sa.UniqueConstraint(
            "dataset_version_id", "name", name="uq_boundary_condition_version_name"
        ),
    )
    op.create_index(
        "ix_boundary_condition_dataset_version_id",
        "boundary_condition",
        ["dataset_version_id"],
    )

    op.create_table(
        "simulation_case",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("dataset_version_id", sa.Integer(), nullable=False),
        sa.Column("boundary_condition_id", sa.Integer(), nullable=False),
        sa.Column(
            "created_time",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["dataset_version_id"],
            ["dataset_version.id"],
            name="fk_simulation_case_dataset_version_id",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["boundary_condition_id"],
            ["boundary_condition.id"],
            name="fk_simulation_case_boundary_condition_id",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_simulation_case"),
        sa.UniqueConstraint("name", name="uq_simulation_case_name"),
    )
    op.create_index(
        "ix_simulation_case_dataset_version_id", "simulation_case", ["dataset_version_id"]
    )


def downgrade() -> None:
    """移除 Phase 2 对象并恢复 Phase 1 字段命名和约束。"""

    op.drop_table("simulation_case")
    op.drop_table("boundary_condition")
    op.drop_table("model_parameter")
    op.drop_table("river_connection")
    op.drop_table("river_segment")
    op.drop_table("river_node")

    op.drop_index("ix_pump_dataset_version_id", table_name="pump")
    op.drop_constraint("ck_pump_head_nonnegative", "pump", type_="check")
    op.drop_constraint("ck_pump_design_flow_nonnegative", "pump", type_="check")
    op.drop_constraint("uq_pump_version_code", "pump", type_="unique")
    op.drop_constraint("fk_pump_dataset_version_id", "pump", type_="foreignkey")
    for column in ("control_mode", "efficiency_curve", "head", "pump_code", "dataset_version_id"):
        op.drop_column("pump", column)
    op.alter_column("pump", "design_flow", new_column_name="capacity")
    op.create_check_constraint("ck_pump_capacity_nonnegative", "pump", "capacity >= 0")
    op.create_unique_constraint("uq_pump_name", "pump", ["name"])

    op.drop_index("ix_gate_dataset_version_id", table_name="gate")
    op.drop_constraint("ck_gate_max_flow_nonnegative", "gate", type_="check")
    op.drop_constraint("uq_gate_version_code", "gate", type_="unique")
    op.drop_constraint("fk_gate_dataset_version_id", "gate", type_="foreignkey")
    for column in (
        "bottom_elevation",
        "max_flow",
        "control_mode",
        "opening_direction",
        "gate_code",
        "dataset_version_id",
    ):
        op.drop_column("gate", column)
    op.create_unique_constraint("uq_gate_name", "gate", ["name"])

    op.drop_index("ix_cross_section_dataset_version_id", table_name="cross_section")
    op.drop_constraint(
        "uq_cross_section_version_river_station", "cross_section", type_="unique"
    )
    op.drop_constraint("uq_cross_section_version_code", "cross_section", type_="unique")
    op.drop_constraint(
        "fk_cross_section_dataset_version_id", "cross_section", type_="foreignkey"
    )
    for column in ("survey_date", "elevation_min", "section_name", "section_code", "dataset_version_id"):
        op.drop_column("cross_section", column)
    op.alter_column("cross_section", "roughness", nullable=True)
    op.alter_column("cross_section", "points", new_column_name="elevation_points")
    op.create_unique_constraint(
        "uq_cross_section_river_station", "cross_section", ["river_id", "station"]
    )

    op.drop_index("ix_river_dataset_version_id", table_name="river")
    op.drop_constraint("ck_river_status", "river", type_="check")
    op.drop_constraint("uq_river_version_code", "river", type_="unique")
    op.drop_constraint("fk_river_dataset_version_id", "river", type_="foreignkey")
    op.drop_column("river", "status")
    op.drop_column("river", "level")
    op.drop_column("river", "dataset_version_id")
    op.create_unique_constraint("uq_river_code", "river", ["code"])
    op.create_unique_constraint("uq_river_name", "river", ["name"])

    op.drop_table("dataset_version")
