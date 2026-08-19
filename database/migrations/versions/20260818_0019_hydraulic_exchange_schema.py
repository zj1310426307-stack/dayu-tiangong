"""Add the production hydraulic domain without replacing GIS core tables.

Revision ID: 20260818_0019
Revises: 20260817_0018
"""

from collections.abc import Sequence

from alembic import op
from geoalchemy2 import Geometry
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "20260818_0019"
down_revision: str | None = "20260817_0018"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _identity() -> list[sa.Column]:
    """Return the common primary key and Dataset Version identity columns."""

    return [
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("dataset_version_id", sa.Integer(), nullable=False),
    ]


def _h_table(name: str, *columns: object, **kwargs: object) -> None:
    """Create one table in the hydraulic schema with concise call sites."""

    op.create_table(name, *columns, schema="hydraulic", **kwargs)


def _strengthen_legacy_version_keys() -> None:
    """Close cross-version holes in legacy relations touched by this migration."""

    op.create_unique_constraint("uq_river_id_version", "river", ["id", "dataset_version_id"])
    op.create_unique_constraint(
        "uq_river_node_id_version", "river_node", ["id", "dataset_version_id"]
    )
    op.create_unique_constraint(
        "uq_river_segment_id_version", "river_segment", ["id", "dataset_version_id"]
    )

    op.drop_constraint("fk_cross_section_river_id", "cross_section", type_="foreignkey")
    op.create_foreign_key(
        "fk_cross_section_river_version", "cross_section", "river",
        ["river_id", "dataset_version_id"], ["id", "dataset_version_id"],
        ondelete="CASCADE",
    )

    for constraint in (
        "fk_river_segment_river_id",
        "fk_river_segment_upstream_node_id",
        "fk_river_segment_downstream_node_id",
    ):
        op.drop_constraint(constraint, "river_segment", type_="foreignkey")
    op.create_foreign_key(
        "fk_river_segment_river_version", "river_segment", "river",
        ["river_id", "dataset_version_id"], ["id", "dataset_version_id"],
        ondelete="CASCADE",
    )
    op.create_foreign_key(
        "fk_river_segment_upstream_version", "river_segment", "river_node",
        ["upstream_node_id", "dataset_version_id"], ["id", "dataset_version_id"],
        ondelete="RESTRICT",
    )
    op.create_foreign_key(
        "fk_river_segment_downstream_version", "river_segment", "river_node",
        ["downstream_node_id", "dataset_version_id"], ["id", "dataset_version_id"],
        ondelete="RESTRICT",
    )

    for constraint in (
        "fk_river_connection_from_node_id",
        "fk_river_connection_to_node_id",
        "fk_river_connection_river_id",
    ):
        op.drop_constraint(constraint, "river_connection", type_="foreignkey")
    op.create_foreign_key(
        "fk_river_connection_from_version", "river_connection", "river_node",
        ["from_node_id", "dataset_version_id"], ["id", "dataset_version_id"],
        ondelete="CASCADE",
    )
    op.create_foreign_key(
        "fk_river_connection_to_version", "river_connection", "river_node",
        ["to_node_id", "dataset_version_id"], ["id", "dataset_version_id"],
        ondelete="CASCADE",
    )
    op.create_foreign_key(
        "fk_river_connection_river_version", "river_connection", "river",
        ["river_id", "dataset_version_id"], ["id", "dataset_version_id"],
        ondelete="CASCADE",
    )


def upgrade() -> None:
    """Create version-safe hydraulic semantics, backfill legacy data, and add adapters."""

    op.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto")
    _strengthen_legacy_version_keys()
    op.execute("CREATE SCHEMA hydraulic")

    _h_table(
        "network", *_identity(),
        sa.Column("code", sa.String(64), nullable=False),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("display_crs", sa.String(32), nullable=False, server_default="EPSG:4490"),
        sa.Column("engineering_crs", sa.String(32)),
        sa.Column("horizontal_unit", sa.String(16), nullable=False, server_default="m"),
        sa.Column("vertical_datum", sa.String(64), nullable=False, server_default="unknown"),
        sa.Column("vertical_unit", sa.String(16), nullable=False, server_default="m"),
        sa.Column("source_kind", sa.String(32), nullable=False, server_default="legacy"),
        sa.Column("metadata_json", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("display_crs = 'EPSG:4490'", name="ck_hydraulic_network_display_crs"),
        sa.CheckConstraint(
            "engineering_crs IS NULL OR engineering_crs ~ '^EPSG:[0-9]{4,6}$'",
            name="ck_hydraulic_network_engineering_crs",
        ),
        sa.CheckConstraint("horizontal_unit = 'm'", name="ck_hydraulic_network_horizontal_unit"),
        sa.CheckConstraint("vertical_unit = 'm'", name="ck_hydraulic_network_vertical_unit"),
        sa.CheckConstraint(
            "source_kind IN ('legacy','mike11','excel','csv','geojson','shp','dxf','api')",
            name="ck_hydraulic_network_source_kind",
        ),
        sa.ForeignKeyConstraint(
            ["dataset_version_id"], ["public.dataset_version.id"],
            name="fk_hydraulic_network_dataset_version", ondelete="CASCADE",
        ),
        sa.UniqueConstraint("id", "dataset_version_id", name="uq_hydraulic_network_id_version"),
        sa.UniqueConstraint("dataset_version_id", "code", name="uq_hydraulic_network_version_code"),
    )
    op.create_index("ix_hydraulic_network_version", "network", ["dataset_version_id"], schema="hydraulic")

    _h_table(
        "node", *_identity(),
        sa.Column("network_id", sa.Integer(), nullable=False),
        sa.Column("node_code", sa.String(64), nullable=False),
        sa.Column("node_name", sa.String(128)),
        sa.Column("node_type", sa.String(24), nullable=False),
        sa.Column("geometry", Geometry("POINT", srid=4490, spatial_index=False), nullable=False),
        sa.Column("elevation_m", sa.Float()),
        sa.Column("metadata_json", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.CheckConstraint(
            "node_type IN ('boundary','junction','structure','lateral','unknown')",
            name="ck_hydraulic_node_type",
        ),
        sa.ForeignKeyConstraint(
            ["network_id", "dataset_version_id"],
            ["hydraulic.network.id", "hydraulic.network.dataset_version_id"],
            name="fk_hydraulic_node_network_version", ondelete="CASCADE",
        ),
        sa.UniqueConstraint("id", "dataset_version_id", name="uq_hydraulic_node_id_version"),
        sa.UniqueConstraint(
            "dataset_version_id", "network_id", "node_code",
            name="uq_hydraulic_node_version_network_code",
        ),
    )
    op.create_index("ix_hydraulic_node_geometry_gist", "node", ["geometry"], postgresql_using="gist", schema="hydraulic")
    op.create_index("ix_hydraulic_node_network", "node", ["network_id"], schema="hydraulic")

    _h_table(
        "branch", *_identity(),
        sa.Column("network_id", sa.Integer(), nullable=False),
        sa.Column("legacy_river_id", sa.Integer()),
        sa.Column("branch_code", sa.String(64), nullable=False),
        sa.Column("river_name", sa.String(128), nullable=False),
        sa.Column("branch_name", sa.String(128), nullable=False),
        sa.Column("upstream_node_id", sa.Integer()),
        sa.Column("downstream_node_id", sa.Integer()),
        sa.Column("chainage_start_m", sa.Float(), nullable=False),
        sa.Column("chainage_end_m", sa.Float(), nullable=False),
        sa.Column("length_m", sa.Float(), nullable=False),
        sa.Column("direction_status", sa.String(16), nullable=False, server_default="unknown"),
        sa.Column("centerline", Geometry("LINESTRING", srid=4490, spatial_index=False), nullable=False),
        sa.Column("source_revision", sa.String(64)),
        sa.Column("metadata_json", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("chainage_start_m >= 0", name="ck_hydraulic_branch_start_chainage"),
        sa.CheckConstraint("chainage_end_m > chainage_start_m", name="ck_hydraulic_branch_chainage_range"),
        sa.CheckConstraint("length_m > 0", name="ck_hydraulic_branch_length_positive"),
        sa.CheckConstraint(
            "direction_status IN ('confirmed','inferred','unknown')",
            name="ck_hydraulic_branch_direction_status",
        ),
        sa.CheckConstraint(
            "upstream_node_id IS NULL OR downstream_node_id IS NULL OR upstream_node_id <> downstream_node_id",
            name="ck_hydraulic_branch_distinct_nodes",
        ),
        sa.ForeignKeyConstraint(
            ["network_id", "dataset_version_id"],
            ["hydraulic.network.id", "hydraulic.network.dataset_version_id"],
            name="fk_hydraulic_branch_network_version", ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["upstream_node_id", "dataset_version_id"],
            ["hydraulic.node.id", "hydraulic.node.dataset_version_id"],
            name="fk_hydraulic_branch_upstream_node_version", ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["downstream_node_id", "dataset_version_id"],
            ["hydraulic.node.id", "hydraulic.node.dataset_version_id"],
            name="fk_hydraulic_branch_downstream_node_version", ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["legacy_river_id", "dataset_version_id"],
            ["public.river.id", "public.river.dataset_version_id"],
            name="fk_hydraulic_branch_legacy_river_version", ondelete="CASCADE",
        ),
        sa.UniqueConstraint("id", "dataset_version_id", name="uq_hydraulic_branch_id_version"),
        sa.UniqueConstraint(
            "dataset_version_id", "network_id", "branch_code",
            name="uq_hydraulic_branch_version_network_code",
        ),
        sa.UniqueConstraint("legacy_river_id", name="uq_hydraulic_branch_legacy_river"),
    )
    op.create_index("ix_hydraulic_branch_geometry_gist", "branch", ["centerline"], postgresql_using="gist", schema="hydraulic")
    op.create_index("ix_hydraulic_branch_network", "branch", ["network_id"], schema="hydraulic")

    _h_table(
        "import_job",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("job_code", sa.String(32), nullable=False),
        sa.Column("dataset_version_id", sa.Integer(), nullable=False),
        sa.Column("gis_import_batch_id", sa.Integer()),
        sa.Column("filename", sa.String(256), nullable=False),
        sa.Column("source_format", sa.String(16), nullable=False),
        sa.Column("source_srid", sa.Integer(), nullable=False),
        sa.Column("source_hash_sha256", sa.String(64), nullable=False),
        sa.Column("config_hash", sa.String(64), nullable=False),
        sa.Column("coordinate_reference", postgresql.JSONB(), nullable=False),
        sa.Column("transformation_evidence", postgresql.JSONB(), nullable=False),
        sa.Column("raw_content", sa.LargeBinary(), nullable=False),
        sa.Column("parser_profile", sa.String(64), nullable=False),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("record_counts", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("issues", postgresql.JSONB(), nullable=False, server_default="[]"),
        sa.Column("normalized_payload", postgresql.JSONB()),
        sa.Column("native_validation_status", sa.String(32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint(
            "source_format IN ('nwk11','xns11','xlsx','csv','geojson','shp','dxf')",
            name="ck_hydraulic_import_job_format",
        ),
        sa.CheckConstraint(
            "status IN ('previewed','validated','rejected','committed','failed')",
            name="ck_hydraulic_import_job_status",
        ),
        sa.ForeignKeyConstraint(
            ["dataset_version_id"], ["public.dataset_version.id"],
            name="fk_hydraulic_import_job_dataset_version", ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["gis_import_batch_id"], ["public.gis_import_batch.id"],
            name="fk_hydraulic_import_job_gis_batch", ondelete="SET NULL",
        ),
        sa.UniqueConstraint("job_code", name="uq_hydraulic_import_job_code"),
        sa.UniqueConstraint(
            "dataset_version_id", "source_hash_sha256", "config_hash",
            name="uq_hydraulic_import_identity",
        ),
    )
    op.create_index(
        "ix_hydraulic_import_job_version_created", "import_job",
        ["dataset_version_id", "created_at"], schema="hydraulic",
    )

    _h_table(
        "branch_vertex", *_identity(),
        sa.Column("branch_id", sa.Integer(), nullable=False),
        sa.Column("vertex_order", sa.Integer(), nullable=False),
        sa.Column("chainage_m", sa.Float(), nullable=False),
        sa.Column("geometry", Geometry("POINT", srid=4490, spatial_index=False), nullable=False),
        sa.Column("source_x", sa.Float(), nullable=False),
        sa.Column("source_y", sa.Float(), nullable=False),
        sa.Column("source_z", sa.Float()),
        sa.Column("source_crs", sa.String(64), nullable=False),
        sa.Column("source_axis_mapping", sa.String(32), nullable=False),
        sa.Column("transform_pipeline", sa.Text(), nullable=False),
        sa.Column("import_job_id", sa.Integer()),
        sa.Column("metadata_json", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.CheckConstraint("vertex_order >= 0", name="ck_hydraulic_branch_vertex_order"),
        sa.CheckConstraint("chainage_m >= 0", name="ck_hydraulic_branch_vertex_chainage"),
        sa.ForeignKeyConstraint(
            ["branch_id", "dataset_version_id"],
            ["hydraulic.branch.id", "hydraulic.branch.dataset_version_id"],
            name="fk_hydraulic_branch_vertex_branch_version", ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["import_job_id"], ["hydraulic.import_job.id"],
            name="fk_hydraulic_branch_vertex_import_job", ondelete="SET NULL",
        ),
        sa.UniqueConstraint("id", "dataset_version_id", name="uq_hydraulic_branch_vertex_id_version"),
        sa.UniqueConstraint("branch_id", "vertex_order", name="uq_hydraulic_branch_vertex_order"),
        sa.UniqueConstraint("branch_id", "chainage_m", name="uq_hydraulic_branch_vertex_chainage"),
    )
    op.create_index("ix_hydraulic_branch_vertex_geometry_gist", "branch_vertex", ["geometry"], postgresql_using="gist", schema="hydraulic")
    op.create_index("ix_hydraulic_branch_vertex_branch", "branch_vertex", ["branch_id", "vertex_order"], schema="hydraulic")

    _h_table(
        "reach", *_identity(),
        sa.Column("branch_id", sa.Integer(), nullable=False),
        sa.Column("reach_code", sa.String(64), nullable=False),
        sa.Column("reach_type", sa.String(24), nullable=False, server_default="channel"),
        sa.Column("start_chainage_m", sa.Float(), nullable=False),
        sa.Column("end_chainage_m", sa.Float(), nullable=False),
        sa.Column("upstream_node_id", sa.Integer(), nullable=False),
        sa.Column("downstream_node_id", sa.Integer(), nullable=False),
        sa.Column("length_m", sa.Float(), nullable=False),
        sa.Column("geometry", Geometry("LINESTRING", srid=4490, spatial_index=False), nullable=False),
        sa.Column("parameter_json", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.CheckConstraint("end_chainage_m > start_chainage_m", name="ck_hydraulic_reach_range"),
        sa.CheckConstraint("length_m > 0", name="ck_hydraulic_reach_length"),
        sa.CheckConstraint(
            "reach_type IN ('channel','structure','junction_link','lateral_link')",
            name="ck_hydraulic_reach_type",
        ),
        sa.CheckConstraint("upstream_node_id <> downstream_node_id", name="ck_hydraulic_reach_distinct_nodes"),
        sa.ForeignKeyConstraint(
            ["branch_id", "dataset_version_id"],
            ["hydraulic.branch.id", "hydraulic.branch.dataset_version_id"],
            name="fk_hydraulic_reach_branch_version", ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["upstream_node_id", "dataset_version_id"],
            ["hydraulic.node.id", "hydraulic.node.dataset_version_id"],
            name="fk_hydraulic_reach_upstream_node_version", ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["downstream_node_id", "dataset_version_id"],
            ["hydraulic.node.id", "hydraulic.node.dataset_version_id"],
            name="fk_hydraulic_reach_downstream_node_version", ondelete="RESTRICT",
        ),
        sa.UniqueConstraint("id", "dataset_version_id", name="uq_hydraulic_reach_id_version"),
        sa.UniqueConstraint("branch_id", "reach_code", name="uq_hydraulic_reach_branch_code"),
    )
    op.create_index("ix_hydraulic_reach_geometry_gist", "reach", ["geometry"], postgresql_using="gist", schema="hydraulic")
    op.create_index("ix_hydraulic_reach_branch_range", "reach", ["branch_id", "start_chainage_m"], schema="hydraulic")

    _h_table(
        "cross_section", *_identity(),
        sa.Column("branch_id", sa.Integer(), nullable=False),
        sa.Column("legacy_cross_section_id", sa.Integer()),
        sa.Column("section_code", sa.String(64), nullable=False),
        sa.Column("section_name", sa.String(128), nullable=False),
        sa.Column("chainage_m", sa.Float(), nullable=False),
        sa.Column("computed_chainage_m", sa.Float()),
        sa.Column("chainage_source", sa.String(24), nullable=False, server_default="imported"),
        sa.Column("snap_distance_m", sa.Float()),
        sa.Column("location", Geometry("POINT", srid=4490, spatial_index=False), nullable=False),
        sa.Column("axis", Geometry("LINESTRING", srid=4490, spatial_index=False)),
        sa.Column("left_bank", Geometry("POINT", srid=4490, spatial_index=False)),
        sa.Column("right_bank", Geometry("POINT", srid=4490, spatial_index=False)),
        sa.Column("orientation_status", sa.String(16), nullable=False, server_default="pending"),
        sa.Column("manual_override_reason", sa.Text()),
        sa.Column("manual_override_actor", sa.String(128)),
        sa.Column("manual_override_at", sa.DateTime(timezone=True)),
        sa.Column("metadata_json", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("chainage_m >= 0", name="ck_hydraulic_cross_section_chainage"),
        sa.CheckConstraint(
            "chainage_source IN ('computed','imported','manual_override')",
            name="ck_hydraulic_cross_section_chainage_source",
        ),
        sa.CheckConstraint(
            "orientation_status IN ('confirmed','pending','reversed','invalid')",
            name="ck_hydraulic_cross_section_orientation_status",
        ),
        sa.ForeignKeyConstraint(
            ["branch_id", "dataset_version_id"],
            ["hydraulic.branch.id", "hydraulic.branch.dataset_version_id"],
            name="fk_hydraulic_cross_section_branch_version", ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["legacy_cross_section_id", "dataset_version_id"],
            ["public.cross_section.id", "public.cross_section.dataset_version_id"],
            name="fk_hydraulic_cross_section_legacy_version", ondelete="CASCADE",
        ),
        sa.UniqueConstraint("id", "dataset_version_id", name="uq_hydraulic_cross_section_id_version"),
        sa.UniqueConstraint("dataset_version_id", "section_code", name="uq_hydraulic_cross_section_version_code"),
        sa.UniqueConstraint("legacy_cross_section_id", name="uq_hydraulic_cross_section_legacy"),
    )
    op.create_index("ix_hydraulic_cross_section_location_gist", "cross_section", ["location"], postgresql_using="gist", schema="hydraulic")
    op.create_index("ix_hydraulic_cross_section_axis_gist", "cross_section", ["axis"], postgresql_using="gist", schema="hydraulic")
    op.create_index("ix_hydraulic_cross_section_branch_chainage", "cross_section", ["branch_id", "chainage_m"], schema="hydraulic")

    _h_table(
        "cross_section_profile", *_identity(),
        sa.Column("cross_section_id", sa.Integer(), nullable=False),
        sa.Column("topography_id", sa.String(64), nullable=False),
        sa.Column("survey_date", sa.Date()),
        sa.Column("survey_method", sa.String(64)),
        sa.Column("vertical_datum", sa.String(64), nullable=False, server_default="unknown"),
        sa.Column("vertical_unit", sa.String(16), nullable=False, server_default="m"),
        sa.Column("default_manning_n", sa.Float(), nullable=False),
        sa.Column("source_revision", sa.String(64)),
        sa.Column("profile_hash", sa.String(64), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("metadata_json", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("default_manning_n > 0", name="ck_hydraulic_profile_manning"),
        sa.ForeignKeyConstraint(
            ["cross_section_id", "dataset_version_id"],
            ["hydraulic.cross_section.id", "hydraulic.cross_section.dataset_version_id"],
            name="fk_hydraulic_profile_section_version", ondelete="CASCADE",
        ),
        sa.UniqueConstraint("id", "dataset_version_id", name="uq_hydraulic_profile_id_version"),
        sa.UniqueConstraint("cross_section_id", "topography_id", name="uq_hydraulic_profile_section_topography"),
    )
    op.create_index("ix_hydraulic_profile_version_active", "cross_section_profile", ["dataset_version_id", "is_active"], schema="hydraulic")
    op.create_index(
        "uq_hydraulic_profile_one_active",
        "cross_section_profile",
        ["cross_section_id"],
        unique=True,
        schema="hydraulic",
        postgresql_where=sa.text("is_active"),
    )

    _h_table(
        "cross_section_point", *_identity(),
        sa.Column("profile_id", sa.Integer(), nullable=False),
        sa.Column("point_order", sa.Integer(), nullable=False),
        sa.Column("offset_m", sa.Float(), nullable=False),
        sa.Column("elevation_m", sa.Float(), nullable=False),
        sa.Column("marker_type", sa.String(24), nullable=False, server_default="none"),
        sa.Column("geometry", Geometry("POINT", srid=4490, spatial_index=False)),
        sa.Column("source_x", sa.Float()),
        sa.Column("source_y", sa.Float()),
        sa.Column("source_z", sa.Float()),
        sa.Column("source_crs", sa.String(64)),
        sa.Column("source_axis_mapping", sa.String(32)),
        sa.Column("point_code", sa.String(64)),
        sa.Column("metadata_json", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.CheckConstraint("point_order >= 0", name="ck_hydraulic_cross_section_point_order"),
        sa.CheckConstraint("offset_m >= 0", name="ck_hydraulic_cross_section_point_offset"),
        sa.CheckConstraint(
            "marker_type IN ('none','left_bank','right_bank','left_levee','right_levee',"
            "'low_flow_left','low_flow_right','thalweg')",
            name="ck_hydraulic_cross_section_point_marker",
        ),
        sa.ForeignKeyConstraint(
            ["profile_id", "dataset_version_id"],
            ["hydraulic.cross_section_profile.id", "hydraulic.cross_section_profile.dataset_version_id"],
            name="fk_hydraulic_cross_section_point_profile_version", ondelete="CASCADE",
        ),
        sa.UniqueConstraint("id", "dataset_version_id", name="uq_hydraulic_point_id_version"),
        sa.UniqueConstraint("profile_id", "point_order", name="uq_hydraulic_point_profile_order"),
        sa.UniqueConstraint("profile_id", "offset_m", name="uq_hydraulic_point_profile_offset"),
    )
    op.create_index("ix_hydraulic_cross_section_point_geometry_gist", "cross_section_point", ["geometry"], postgresql_using="gist", schema="hydraulic")
    op.create_index("ix_hydraulic_cross_section_point_profile", "cross_section_point", ["profile_id", "point_order"], schema="hydraulic")

    _h_table(
        "cross_section_roughness_zone", *_identity(),
        sa.Column("profile_id", sa.Integer(), nullable=False),
        sa.Column("zone_order", sa.Integer(), nullable=False),
        sa.Column("offset_start_m", sa.Float(), nullable=False),
        sa.Column("offset_end_m", sa.Float(), nullable=False),
        sa.Column("manning_n", sa.Float(), nullable=False),
        sa.Column("zone_type", sa.String(32), nullable=False, server_default="channel"),
        sa.CheckConstraint("zone_order >= 0", name="ck_hydraulic_roughness_zone_order"),
        sa.CheckConstraint("offset_end_m > offset_start_m", name="ck_hydraulic_roughness_zone_range"),
        sa.CheckConstraint("manning_n > 0", name="ck_hydraulic_roughness_zone_manning"),
        sa.ForeignKeyConstraint(
            ["profile_id", "dataset_version_id"],
            ["hydraulic.cross_section_profile.id", "hydraulic.cross_section_profile.dataset_version_id"],
            name="fk_hydraulic_roughness_zone_profile_version", ondelete="CASCADE",
        ),
        sa.UniqueConstraint("id", "dataset_version_id", name="uq_hydraulic_roughness_id_version"),
        sa.UniqueConstraint("profile_id", "zone_order", name="uq_hydraulic_roughness_profile_order"),
    )
    op.create_index("ix_hydraulic_roughness_profile", "cross_section_roughness_zone", ["profile_id", "zone_order"], schema="hydraulic")

    _h_table(
        "cross_section_processing", *_identity(),
        sa.Column("profile_id", sa.Integer(), nullable=False),
        sa.Column("profile_hash", sa.String(64), nullable=False),
        sa.Column("processor_version", sa.String(64), nullable=False),
        sa.Column("vertical_step_m", sa.Float(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("minimum_stage_m", sa.Float()),
        sa.Column("maximum_stage_m", sa.Float()),
        sa.Column("generated_at", sa.DateTime(timezone=True)),
        sa.Column("diagnostics_json", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.CheckConstraint("vertical_step_m > 0", name="ck_hydraulic_processing_step"),
        sa.CheckConstraint("status IN ('pending','ready','failed')", name="ck_hydraulic_processing_status"),
        sa.ForeignKeyConstraint(
            ["profile_id", "dataset_version_id"],
            ["hydraulic.cross_section_profile.id", "hydraulic.cross_section_profile.dataset_version_id"],
            name="fk_hydraulic_processing_profile_version", ondelete="CASCADE",
        ),
        sa.UniqueConstraint("id", "dataset_version_id", name="uq_hydraulic_processing_id_version"),
        sa.UniqueConstraint(
            "profile_id", "profile_hash", "processor_version", "vertical_step_m",
            name="uq_hydraulic_processing_cache_key",
        ),
    )
    op.create_index("ix_hydraulic_processing_profile", "cross_section_processing", ["profile_id"], schema="hydraulic")

    _h_table(
        "cross_section_hydraulic_row",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("dataset_version_id", sa.Integer(), nullable=False),
        sa.Column("processing_id", sa.Integer(), nullable=False),
        sa.Column("stage_m", sa.Float(), nullable=False),
        sa.Column("area_m2", sa.Float(), nullable=False),
        sa.Column("top_width_m", sa.Float(), nullable=False),
        sa.Column("wetted_perimeter_m", sa.Float(), nullable=False),
        sa.Column("hydraulic_radius_m", sa.Float(), nullable=False),
        sa.Column("conveyance", sa.Float(), nullable=False),
        sa.ForeignKeyConstraint(
            ["processing_id", "dataset_version_id"],
            ["hydraulic.cross_section_processing.id", "hydraulic.cross_section_processing.dataset_version_id"],
            name="fk_hydraulic_row_processing_version", ondelete="CASCADE",
        ),
        sa.UniqueConstraint("processing_id", "stage_m", name="uq_hydraulic_row_processing_stage"),
    )
    op.create_index("ix_hydraulic_row_processing", "cross_section_hydraulic_row", ["processing_id", "stage_m"], schema="hydraulic")

    _h_table(
        "validation_run",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("run_code", sa.String(32), nullable=False),
        sa.Column("dataset_version_id", sa.Integer(), nullable=False),
        sa.Column("import_job_id", sa.Integer()),
        sa.Column("network_id", sa.Integer()),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("summary", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint("status IN ('running','passed','failed')", name="ck_hydraulic_validation_run_status"),
        sa.ForeignKeyConstraint(
            ["dataset_version_id"], ["public.dataset_version.id"],
            name="fk_hydraulic_validation_run_dataset_version", ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["import_job_id"], ["hydraulic.import_job.id"],
            name="fk_hydraulic_validation_run_import_job", ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["network_id", "dataset_version_id"],
            ["hydraulic.network.id", "hydraulic.network.dataset_version_id"],
            name="fk_hydraulic_validation_run_network_version", ondelete="CASCADE",
        ),
        sa.UniqueConstraint("run_code", name="uq_hydraulic_validation_run_code"),
    )

    _h_table(
        "validation_result",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("run_id", sa.Integer(), nullable=False),
        sa.Column("gis_validation_issue_id", sa.Integer()),
        sa.Column("severity", sa.String(16), nullable=False),
        sa.Column("rule_code", sa.String(64), nullable=False),
        sa.Column("entity_type", sa.String(32), nullable=False),
        sa.Column("entity_id", sa.Integer()),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("context", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint(
            "severity IN ('error','warning','info','passed')",
            name="ck_hydraulic_validation_result_severity",
        ),
        sa.ForeignKeyConstraint(
            ["run_id"], ["hydraulic.validation_run.id"],
            name="fk_hydraulic_validation_result_run", ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["gis_validation_issue_id"], ["public.gis_validation_issue.id"],
            name="fk_hydraulic_validation_result_gis_issue", ondelete="SET NULL",
        ),
    )
    op.create_index("ix_hydraulic_validation_result_run", "validation_result", ["run_id"], schema="hydraulic")

    _backfill_legacy()
    _create_adapters_and_grants()


def _backfill_legacy() -> None:
    """Backfill existing GIS rows without guessing engineering CRS, direction, or axes."""

    op.execute(
        """
        INSERT INTO hydraulic.network
            (dataset_version_id, code, name, display_crs, engineering_crs,
             horizontal_unit, vertical_datum, vertical_unit, source_kind, metadata_json)
        SELECT dv.id, 'LEGACY-V' || dv.id, dv.name || ' 水动力网络', 'EPSG:4490', NULL,
               'm', 'unknown', 'm', 'legacy',
               jsonb_build_object('engineering_crs_status', 'unconfirmed')
          FROM public.dataset_version AS dv
         WHERE EXISTS (SELECT 1 FROM public.river AS r WHERE r.dataset_version_id = dv.id)
        """
    )
    op.execute(
        """
        INSERT INTO hydraulic.branch
            (dataset_version_id, network_id, legacy_river_id, branch_code, river_name,
             branch_name, chainage_start_m, chainage_end_m, length_m,
             direction_status, centerline, metadata_json)
        SELECT r.dataset_version_id, n.id, r.id, r.code, r.name, r.name,
               0.0, GREATEST(r.length, 0.001), GREATEST(r.length, 0.001),
               'inferred', r.geometry,
               jsonb_build_object('legacy_direction_requires_confirmation', true)
          FROM public.river AS r
          JOIN hydraulic.network AS n ON n.dataset_version_id = r.dataset_version_id
        """
    )
    op.execute(
        """
        INSERT INTO hydraulic.branch_vertex
            (dataset_version_id, branch_id, vertex_order, chainage_m, geometry,
             source_x, source_y, source_crs, source_axis_mapping, transform_pipeline,
             metadata_json)
        SELECT b.dataset_version_id, b.id, endpoint.vertex_order, endpoint.chainage_m,
               endpoint.geometry, ST_X(endpoint.geometry), ST_Y(endpoint.geometry),
               'EPSG:4490', 'x_easting_y_northing',
               'legacy EPSG:4490 adopted; engineering transform pending confirmation',
               jsonb_build_object('source', 'legacy river endpoint')
          FROM hydraulic.branch AS b
          CROSS JOIN LATERAL (
              VALUES
                (0, b.chainage_start_m, ST_StartPoint(b.centerline)),
                (1, b.chainage_end_m, ST_EndPoint(b.centerline))
          ) AS endpoint(vertex_order, chainage_m, geometry)
        """
    )
    op.execute(
        """
        INSERT INTO hydraulic.cross_section
            (dataset_version_id, branch_id, legacy_cross_section_id, section_code,
             section_name, chainage_m, chainage_source, location, axis,
             left_bank, right_bank, orientation_status, metadata_json)
        SELECT cs.dataset_version_id, b.id, cs.id, cs.section_code, cs.section_name,
               cs.station, 'imported', COALESCE(location.geometry, cs.geometry), axis.geometry,
               axis.left_bank, axis.right_bank,
               CASE WHEN axis.geometry IS NULL THEN 'pending' ELSE 'confirmed' END,
               jsonb_build_object('legacy_station_adopted', true)
          FROM public.cross_section AS cs
          JOIN hydraulic.branch AS b ON b.legacy_river_id = cs.river_id
          LEFT JOIN public.cross_section_location AS location ON location.cross_section_id = cs.id
          LEFT JOIN public.cross_section_axis AS axis ON axis.cross_section_id = cs.id
        """
    )
    op.execute(
        """
        WITH profile_source AS (
            SELECT cs.id AS legacy_id, h.id AS hydraulic_id, cs.dataset_version_id,
                   cs.survey_date, cs.roughness,
                   COALESCE(axis.vertical_datum, profile.vertical_datum, 'unknown') AS vertical_datum,
                   COALESCE(
                       (SELECT jsonb_agg(jsonb_build_array(p.offset, p.elevation) ORDER BY p.point_order)
                          FROM public.cross_section_point AS p
                         WHERE p.cross_section_id = cs.id),
                       profile.profile -> 'points',
                       cs.points::jsonb -> 'points',
                       '[]'::jsonb
                   ) AS points
              FROM public.cross_section AS cs
              JOIN hydraulic.cross_section AS h ON h.legacy_cross_section_id = cs.id
              LEFT JOIN public.cross_section_axis AS axis ON axis.cross_section_id = cs.id
              LEFT JOIN public.cross_section_profile AS profile ON profile.cross_section_id = cs.id
        )
        INSERT INTO hydraulic.cross_section_profile
            (dataset_version_id, cross_section_id, topography_id, survey_date,
             vertical_datum, vertical_unit, default_manning_n, source_revision,
             profile_hash, is_active, metadata_json)
        SELECT dataset_version_id, hydraulic_id, 'DEFAULT', survey_date,
               vertical_datum, 'm', roughness, 'legacy-0019',
               encode(digest(convert_to(jsonb_build_object(
                   'points', points, 'manning_n', roughness,
                   'vertical_datum', vertical_datum, 'vertical_unit', 'm'
               )::text, 'UTF8'), 'sha256'), 'hex'),
               true, jsonb_build_object('backfill_precedence', 'normalized>profile>legacy_json')
          FROM profile_source
        """
    )
    op.execute(
        """
        INSERT INTO hydraulic.cross_section_point
            (dataset_version_id, profile_id, point_order, offset_m, elevation_m,
             geometry, source_x, source_y, source_z, source_crs,
             source_axis_mapping, marker_type, metadata_json)
        SELECT p.dataset_version_id, hp.id, p.point_order, p.offset, p.elevation,
               p.geometry,
               CASE WHEN p.geometry IS NULL THEN NULL ELSE ST_X(p.geometry) END,
               CASE WHEN p.geometry IS NULL THEN NULL ELSE ST_Y(p.geometry) END,
               p.elevation, CASE WHEN p.geometry IS NULL THEN NULL ELSE 'EPSG:4490' END,
               CASE WHEN p.geometry IS NULL THEN NULL ELSE 'x_easting_y_northing' END,
               'none', jsonb_build_object('backfill_source', 'normalized_point')
          FROM public.cross_section_point AS p
          JOIN hydraulic.cross_section AS hs ON hs.legacy_cross_section_id = p.cross_section_id
          JOIN hydraulic.cross_section_profile AS hp ON hp.cross_section_id = hs.id
        """
    )
    op.execute(
        """
        INSERT INTO hydraulic.cross_section_point
            (dataset_version_id, profile_id, point_order, offset_m, elevation_m,
             source_z, marker_type, metadata_json)
        SELECT hp.dataset_version_id, hp.id, values.ordinality - 1,
               (values.point ->> 0)::double precision,
               (values.point ->> 1)::double precision,
               (values.point ->> 1)::double precision, 'none',
               jsonb_build_object('backfill_source', 'profile_json')
          FROM public.cross_section_profile AS legacy_profile
          JOIN hydraulic.cross_section AS hs
            ON hs.legacy_cross_section_id = legacy_profile.cross_section_id
          JOIN hydraulic.cross_section_profile AS hp ON hp.cross_section_id = hs.id
          CROSS JOIN LATERAL jsonb_array_elements(legacy_profile.profile -> 'points')
            WITH ORDINALITY AS values(point, ordinality)
         WHERE NOT EXISTS (
             SELECT 1 FROM hydraulic.cross_section_point AS existing
              WHERE existing.profile_id = hp.id
         )
        """
    )
    op.execute(
        """
        INSERT INTO hydraulic.cross_section_point
            (dataset_version_id, profile_id, point_order, offset_m, elevation_m,
             source_z, marker_type, metadata_json)
        SELECT hp.dataset_version_id, hp.id, values.ordinality - 1,
               (values.point ->> 0)::double precision,
               (values.point ->> 1)::double precision,
               (values.point ->> 1)::double precision, 'none',
               jsonb_build_object('backfill_source', 'legacy_json')
          FROM public.cross_section AS legacy
          JOIN hydraulic.cross_section AS hs ON hs.legacy_cross_section_id = legacy.id
          JOIN hydraulic.cross_section_profile AS hp ON hp.cross_section_id = hs.id
          CROSS JOIN LATERAL json_array_elements(legacy.points -> 'points')
            WITH ORDINALITY AS values(point, ordinality)
         WHERE NOT EXISTS (
             SELECT 1 FROM hydraulic.cross_section_point AS existing
              WHERE existing.profile_id = hp.id
         )
        """
    )
    op.execute(
        """
        INSERT INTO hydraulic.cross_section_roughness_zone
            (dataset_version_id, profile_id, zone_order, offset_start_m,
             offset_end_m, manning_n, zone_type)
        SELECT hp.dataset_version_id, hp.id, 0, MIN(p.offset_m), MAX(p.offset_m),
               hp.default_manning_n, 'channel'
          FROM hydraulic.cross_section_profile AS hp
          JOIN hydraulic.cross_section_point AS p ON p.profile_id = hp.id
         GROUP BY hp.dataset_version_id, hp.id, hp.default_manning_n
        HAVING MAX(p.offset_m) > MIN(p.offset_m)
        """
    )
    op.execute(
        """
        INSERT INTO hydraulic.validation_run
            (run_code, dataset_version_id, network_id, status, summary, completed_at)
        SELECT 'HYDMIG-0019-V' || n.dataset_version_id, n.dataset_version_id, n.id,
               'failed', jsonb_build_object(
                   'migration', true,
                   'engineering_crs_unconfirmed', true,
                   'axis_missing', COUNT(cs.id) FILTER (WHERE cs.axis IS NULL)
               ), now()
          FROM hydraulic.network AS n
          LEFT JOIN hydraulic.cross_section AS cs ON cs.dataset_version_id = n.dataset_version_id
         GROUP BY n.id, n.dataset_version_id
        """
    )
    op.execute(
        """
        INSERT INTO hydraulic.validation_result
            (run_id, severity, rule_code, entity_type, entity_id, message, context)
        SELECT vr.id, 'error', 'ENGINEERING_CRS_UNCONFIRMED', 'network', n.id,
               '旧数据缺少已确认的米制工程 CRS，正式拓扑和 v3 快照已阻断。',
               jsonb_build_object('network_code', n.code)
          FROM hydraulic.validation_run AS vr
          JOIN hydraulic.network AS n ON n.id = vr.network_id
         WHERE n.engineering_crs IS NULL
        """
    )
    op.execute(
        """
        INSERT INTO hydraulic.validation_result
            (run_id, severity, rule_code, entity_type, entity_id, message, context)
        SELECT vr.id, 'error', 'SECTION_AXIS_MISSING', 'cross_section', cs.id,
               '旧断面没有实测轴线；未生成或伪造替代轴线。',
               jsonb_build_object('section_code', cs.section_code)
          FROM hydraulic.cross_section AS cs
          JOIN hydraulic.validation_run AS vr
            ON vr.dataset_version_id = cs.dataset_version_id
         WHERE cs.axis IS NULL
        """
    )


def _create_adapters_and_grants() -> None:
    """Create read adapters and least-privilege grants for existing runtime roles."""

    op.execute(
        """
        CREATE VIEW hydraulic.gis_river_adapter AS
        SELECT b.legacy_river_id AS id, b.dataset_version_id, b.river_name AS name,
               b.branch_code AS code, b.length_m AS length, b.direction_status,
               b.centerline AS geometry
          FROM hydraulic.branch AS b
         WHERE b.legacy_river_id IS NOT NULL
        """
    )
    op.execute(
        """
        CREATE VIEW hydraulic.gis_cross_section_adapter AS
        SELECT cs.legacy_cross_section_id AS id, cs.dataset_version_id,
               b.legacy_river_id AS river_id, cs.section_code,
               cs.chainage_m AS station, cs.location AS geometry,
               p.topography_id, p.default_manning_n AS roughness
          FROM hydraulic.cross_section AS cs
          JOIN hydraulic.branch AS b ON b.id = cs.branch_id
          JOIN hydraulic.cross_section_profile AS p
            ON p.cross_section_id = cs.id AND p.is_active
         WHERE cs.legacy_cross_section_id IS NOT NULL
        """
    )
    op.execute(
        """
        DO $$
        BEGIN
          IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'dayu_backend') THEN
            GRANT USAGE ON SCHEMA hydraulic TO dayu_backend;
            GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA hydraulic TO dayu_backend;
            GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA hydraulic TO dayu_backend;
          END IF;
          IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'dayu_qgis_reviewer') THEN
            GRANT USAGE ON SCHEMA hydraulic TO dayu_qgis_reviewer;
            GRANT SELECT ON ALL TABLES IN SCHEMA hydraulic TO dayu_qgis_reviewer;
          END IF;
        END $$
        """
    )


def downgrade() -> None:
    """Remove additive hydraulic objects and restore legacy single-column foreign keys."""

    op.execute("DROP SCHEMA hydraulic CASCADE")

    for constraint, table in (
        ("fk_cross_section_river_version", "cross_section"),
        ("fk_river_segment_river_version", "river_segment"),
        ("fk_river_segment_upstream_version", "river_segment"),
        ("fk_river_segment_downstream_version", "river_segment"),
        ("fk_river_connection_from_version", "river_connection"),
        ("fk_river_connection_to_version", "river_connection"),
        ("fk_river_connection_river_version", "river_connection"),
    ):
        op.drop_constraint(constraint, table, type_="foreignkey")

    op.create_foreign_key("fk_cross_section_river_id", "cross_section", "river", ["river_id"], ["id"], ondelete="CASCADE")
    op.create_foreign_key("fk_river_segment_river_id", "river_segment", "river", ["river_id"], ["id"], ondelete="CASCADE")
    op.create_foreign_key("fk_river_segment_upstream_node_id", "river_segment", "river_node", ["upstream_node_id"], ["id"], ondelete="RESTRICT")
    op.create_foreign_key("fk_river_segment_downstream_node_id", "river_segment", "river_node", ["downstream_node_id"], ["id"], ondelete="RESTRICT")
    op.create_foreign_key("fk_river_connection_from_node_id", "river_connection", "river_node", ["from_node_id"], ["id"], ondelete="CASCADE")
    op.create_foreign_key("fk_river_connection_to_node_id", "river_connection", "river_node", ["to_node_id"], ["id"], ondelete="CASCADE")
    op.create_foreign_key("fk_river_connection_river_id", "river_connection", "river", ["river_id"], ["id"], ondelete="CASCADE")

    op.drop_constraint("uq_river_segment_id_version", "river_segment", type_="unique")
    op.drop_constraint("uq_river_node_id_version", "river_node", type_="unique")
    op.drop_constraint("uq_river_id_version", "river", type_="unique")
