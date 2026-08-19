"""Production hydraulic-domain models layered onto the shared PostGIS database."""

from datetime import date, datetime
from typing import Any

from geoalchemy2 import Geometry
from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    Float,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.gis.models import Base


class HydraulicNetwork(Base):
    """Own one versioned one-dimensional network and its coordinate contract."""

    __tablename__ = "network"
    __table_args__ = (
        CheckConstraint("display_crs = 'EPSG:4490'", name="ck_hydraulic_network_display_crs"),
        CheckConstraint(
            "engineering_crs IS NULL OR engineering_crs ~ '^EPSG:[0-9]{4,6}$'",
            name="ck_hydraulic_network_engineering_crs",
        ),
        CheckConstraint("horizontal_unit = 'm'", name="ck_hydraulic_network_horizontal_unit"),
        CheckConstraint("vertical_unit = 'm'", name="ck_hydraulic_network_vertical_unit"),
        CheckConstraint(
            "source_kind IN ('legacy','mike11','excel','csv','geojson','shp','dxf','api')",
            name="ck_hydraulic_network_source_kind",
        ),
        UniqueConstraint("id", "dataset_version_id", name="uq_hydraulic_network_id_version"),
        UniqueConstraint("dataset_version_id", "code", name="uq_hydraulic_network_version_code"),
        Index("ix_hydraulic_network_version", "dataset_version_id"),
        {"schema": "hydraulic"},
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    dataset_version_id: Mapped[int] = mapped_column(
        ForeignKey("dataset_version.id", ondelete="CASCADE"), nullable=False
    )
    code: Mapped[str] = mapped_column(String(64), nullable=False)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    display_crs: Mapped[str] = mapped_column(String(32), nullable=False, server_default="EPSG:4490")
    engineering_crs: Mapped[str | None] = mapped_column(String(32))
    horizontal_unit: Mapped[str] = mapped_column(String(16), nullable=False, server_default="m")
    vertical_datum: Mapped[str] = mapped_column(String(64), nullable=False, server_default="unknown")
    vertical_unit: Mapped[str] = mapped_column(String(16), nullable=False, server_default="m")
    source_kind: Mapped[str] = mapped_column(String(32), nullable=False, server_default="legacy")
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, server_default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class HydraulicNode(Base):
    """Represent a confirmed hydraulic endpoint, junction, or structure node."""

    __tablename__ = "node"
    __table_args__ = (
        CheckConstraint(
            "node_type IN ('boundary','junction','structure','lateral','unknown')",
            name="ck_hydraulic_node_type",
        ),
        ForeignKeyConstraint(
            ["network_id", "dataset_version_id"],
            ["hydraulic.network.id", "hydraulic.network.dataset_version_id"],
            name="fk_hydraulic_node_network_version", ondelete="CASCADE",
        ),
        UniqueConstraint("id", "dataset_version_id", name="uq_hydraulic_node_id_version"),
        UniqueConstraint(
            "dataset_version_id", "network_id", "node_code",
            name="uq_hydraulic_node_version_network_code",
        ),
        Index("ix_hydraulic_node_geometry_gist", "geometry", postgresql_using="gist"),
        Index("ix_hydraulic_node_network", "network_id"),
        {"schema": "hydraulic"},
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    dataset_version_id: Mapped[int] = mapped_column(nullable=False)
    network_id: Mapped[int] = mapped_column(nullable=False)
    node_code: Mapped[str] = mapped_column(String(64), nullable=False)
    node_name: Mapped[str | None] = mapped_column(String(128))
    node_type: Mapped[str] = mapped_column(String(24), nullable=False)
    geometry: Mapped[Any] = mapped_column(Geometry("POINT", srid=4490, spatial_index=False), nullable=False)
    elevation_m: Mapped[float | None] = mapped_column(Float)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, server_default="{}")


class HydraulicBranch(Base):
    """Represent one directed branch while preserving its legacy GIS projection."""

    __tablename__ = "branch"
    __table_args__ = (
        CheckConstraint("chainage_start_m >= 0", name="ck_hydraulic_branch_start_chainage"),
        CheckConstraint("chainage_end_m > chainage_start_m", name="ck_hydraulic_branch_chainage_range"),
        CheckConstraint("length_m > 0", name="ck_hydraulic_branch_length_positive"),
        CheckConstraint(
            "direction_status IN ('confirmed','inferred','unknown')",
            name="ck_hydraulic_branch_direction_status",
        ),
        CheckConstraint(
            "upstream_node_id IS NULL OR downstream_node_id IS NULL OR upstream_node_id <> downstream_node_id",
            name="ck_hydraulic_branch_distinct_nodes",
        ),
        ForeignKeyConstraint(
            ["network_id", "dataset_version_id"],
            ["hydraulic.network.id", "hydraulic.network.dataset_version_id"],
            name="fk_hydraulic_branch_network_version", ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["upstream_node_id", "dataset_version_id"],
            ["hydraulic.node.id", "hydraulic.node.dataset_version_id"],
            name="fk_hydraulic_branch_upstream_node_version", ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["downstream_node_id", "dataset_version_id"],
            ["hydraulic.node.id", "hydraulic.node.dataset_version_id"],
            name="fk_hydraulic_branch_downstream_node_version", ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["legacy_river_id", "dataset_version_id"],
            ["river.id", "river.dataset_version_id"],
            name="fk_hydraulic_branch_legacy_river_version", ondelete="CASCADE",
        ),
        UniqueConstraint("id", "dataset_version_id", name="uq_hydraulic_branch_id_version"),
        UniqueConstraint(
            "dataset_version_id", "network_id", "branch_code",
            name="uq_hydraulic_branch_version_network_code",
        ),
        UniqueConstraint("legacy_river_id", name="uq_hydraulic_branch_legacy_river"),
        Index("ix_hydraulic_branch_geometry_gist", "centerline", postgresql_using="gist"),
        Index("ix_hydraulic_branch_network", "network_id"),
        {"schema": "hydraulic"},
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    dataset_version_id: Mapped[int] = mapped_column(nullable=False)
    network_id: Mapped[int] = mapped_column(nullable=False)
    legacy_river_id: Mapped[int | None] = mapped_column()
    branch_code: Mapped[str] = mapped_column(String(64), nullable=False)
    river_name: Mapped[str] = mapped_column(String(128), nullable=False)
    branch_name: Mapped[str] = mapped_column(String(128), nullable=False)
    upstream_node_id: Mapped[int | None] = mapped_column()
    downstream_node_id: Mapped[int | None] = mapped_column()
    start_chainage: Mapped[float] = mapped_column("chainage_start_m", Float, nullable=False)
    end_chainage: Mapped[float] = mapped_column("chainage_end_m", Float, nullable=False)
    length_m: Mapped[float] = mapped_column(Float, nullable=False)
    direction_status: Mapped[str] = mapped_column(String(16), nullable=False, server_default="unknown")
    geometry: Mapped[Any] = mapped_column(
        "centerline", Geometry("LINESTRING", srid=4490, spatial_index=False), nullable=False
    )
    source_revision: Mapped[str | None] = mapped_column(String(64))
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, server_default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class HydraulicImportJob(Base):
    """Record immutable source bytes, coordinate configuration, preview, and commit state."""

    __tablename__ = "import_job"
    __table_args__ = (
        CheckConstraint(
            "source_format IN ('nwk11','xns11','xlsx','csv','geojson','shp','dxf')",
            name="ck_hydraulic_import_job_format",
        ),
        CheckConstraint(
            "status IN ('previewed','validated','rejected','committed','failed')",
            name="ck_hydraulic_import_job_status",
        ),
        UniqueConstraint("job_code", name="uq_hydraulic_import_job_code"),
        UniqueConstraint(
            "dataset_version_id", "source_hash_sha256", "config_hash",
            name="uq_hydraulic_import_identity",
        ),
        Index("ix_hydraulic_import_job_version_created", "dataset_version_id", "created_at"),
        {"schema": "hydraulic"},
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    job_code: Mapped[str] = mapped_column(String(32), nullable=False)
    dataset_version_id: Mapped[int] = mapped_column(ForeignKey("dataset_version.id", ondelete="CASCADE"), nullable=False)
    gis_import_batch_id: Mapped[int | None] = mapped_column(ForeignKey("gis_import_batch.id", ondelete="SET NULL"))
    filename: Mapped[str] = mapped_column(String(256), nullable=False)
    source_format: Mapped[str] = mapped_column(String(16), nullable=False)
    source_srid: Mapped[int] = mapped_column(Integer, nullable=False)
    source_hash_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    config_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    coordinate_reference: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    transformation_evidence: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    raw_content: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    parser_profile: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False)
    record_counts: Mapped[dict[str, int]] = mapped_column(JSONB, nullable=False, server_default="{}")
    issues: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False, server_default="[]")
    normalized_payload: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    native_validation_status: Mapped[str] = mapped_column(String(32), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class HydraulicBranchVertex(Base):
    """Preserve ordered branch vertices, chainage, and coordinate transformation provenance."""

    __tablename__ = "branch_vertex"
    __table_args__ = (
        CheckConstraint("vertex_order >= 0", name="ck_hydraulic_branch_vertex_order"),
        CheckConstraint("chainage_m >= 0", name="ck_hydraulic_branch_vertex_chainage"),
        ForeignKeyConstraint(
            ["branch_id", "dataset_version_id"],
            ["hydraulic.branch.id", "hydraulic.branch.dataset_version_id"],
            name="fk_hydraulic_branch_vertex_branch_version", ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["import_job_id"], ["hydraulic.import_job.id"],
            name="fk_hydraulic_branch_vertex_import_job", ondelete="SET NULL",
        ),
        UniqueConstraint("id", "dataset_version_id", name="uq_hydraulic_branch_vertex_id_version"),
        UniqueConstraint("branch_id", "vertex_order", name="uq_hydraulic_branch_vertex_order"),
        UniqueConstraint("branch_id", "chainage_m", name="uq_hydraulic_branch_vertex_chainage"),
        Index("ix_hydraulic_branch_vertex_geometry_gist", "geometry", postgresql_using="gist"),
        Index("ix_hydraulic_branch_vertex_branch", "branch_id", "vertex_order"),
        {"schema": "hydraulic"},
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    dataset_version_id: Mapped[int] = mapped_column(nullable=False)
    branch_id: Mapped[int] = mapped_column(nullable=False)
    vertex_order: Mapped[int] = mapped_column(Integer, nullable=False)
    chainage: Mapped[float] = mapped_column("chainage_m", Float, nullable=False)
    geometry: Mapped[Any] = mapped_column(Geometry("POINT", srid=4490, spatial_index=False), nullable=False)
    source_x: Mapped[float] = mapped_column(Float, nullable=False)
    source_y: Mapped[float] = mapped_column(Float, nullable=False)
    source_z: Mapped[float | None] = mapped_column(Float)
    source_crs: Mapped[str] = mapped_column(String(64), nullable=False)
    source_axis_mapping: Mapped[str] = mapped_column(String(32), nullable=False)
    transform_pipeline: Mapped[str] = mapped_column(Text, nullable=False)
    import_job_id: Mapped[int | None] = mapped_column()
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, server_default="{}")


# Existing service imports keep this name while the physical model is a branch vertex.
HydraulicChainage = HydraulicBranchVertex


class HydraulicReach(Base):
    """Store one solver-ready span between confirmed nodes on a branch."""

    __tablename__ = "reach"
    __table_args__ = (
        CheckConstraint("end_chainage_m > start_chainage_m", name="ck_hydraulic_reach_range"),
        CheckConstraint("length_m > 0", name="ck_hydraulic_reach_length"),
        CheckConstraint(
            "reach_type IN ('channel','structure','junction_link','lateral_link')",
            name="ck_hydraulic_reach_type",
        ),
        CheckConstraint("upstream_node_id <> downstream_node_id", name="ck_hydraulic_reach_distinct_nodes"),
        ForeignKeyConstraint(
            ["branch_id", "dataset_version_id"],
            ["hydraulic.branch.id", "hydraulic.branch.dataset_version_id"],
            name="fk_hydraulic_reach_branch_version", ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["upstream_node_id", "dataset_version_id"],
            ["hydraulic.node.id", "hydraulic.node.dataset_version_id"],
            name="fk_hydraulic_reach_upstream_node_version", ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["downstream_node_id", "dataset_version_id"],
            ["hydraulic.node.id", "hydraulic.node.dataset_version_id"],
            name="fk_hydraulic_reach_downstream_node_version", ondelete="RESTRICT",
        ),
        UniqueConstraint("id", "dataset_version_id", name="uq_hydraulic_reach_id_version"),
        UniqueConstraint("branch_id", "reach_code", name="uq_hydraulic_reach_branch_code"),
        Index("ix_hydraulic_reach_geometry_gist", "geometry", postgresql_using="gist"),
        Index("ix_hydraulic_reach_branch_range", "branch_id", "start_chainage_m"),
        {"schema": "hydraulic"},
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    dataset_version_id: Mapped[int] = mapped_column(nullable=False)
    branch_id: Mapped[int] = mapped_column(nullable=False)
    reach_code: Mapped[str] = mapped_column(String(64), nullable=False)
    reach_type: Mapped[str] = mapped_column(String(24), nullable=False, server_default="channel")
    start_chainage_m: Mapped[float] = mapped_column(Float, nullable=False)
    end_chainage_m: Mapped[float] = mapped_column(Float, nullable=False)
    upstream_node_id: Mapped[int] = mapped_column(nullable=False)
    downstream_node_id: Mapped[int] = mapped_column(nullable=False)
    length_m: Mapped[float] = mapped_column(Float, nullable=False)
    geometry: Mapped[Any] = mapped_column(Geometry("LINESTRING", srid=4490, spatial_index=False), nullable=False)
    parameter_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, server_default="{}")


class HydraulicCrossSection(Base):
    """Store one cross-section location independently from its survey profiles."""

    __tablename__ = "cross_section"
    __table_args__ = (
        CheckConstraint("chainage_m >= 0", name="ck_hydraulic_cross_section_chainage"),
        CheckConstraint(
            "chainage_source IN ('computed','imported','manual_override')",
            name="ck_hydraulic_cross_section_chainage_source",
        ),
        CheckConstraint(
            "orientation_status IN ('confirmed','pending','reversed','invalid')",
            name="ck_hydraulic_cross_section_orientation_status",
        ),
        ForeignKeyConstraint(
            ["branch_id", "dataset_version_id"],
            ["hydraulic.branch.id", "hydraulic.branch.dataset_version_id"],
            name="fk_hydraulic_cross_section_branch_version", ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["legacy_cross_section_id", "dataset_version_id"],
            ["cross_section.id", "cross_section.dataset_version_id"],
            name="fk_hydraulic_cross_section_legacy_version", ondelete="CASCADE",
        ),
        UniqueConstraint("id", "dataset_version_id", name="uq_hydraulic_cross_section_id_version"),
        UniqueConstraint("dataset_version_id", "section_code", name="uq_hydraulic_cross_section_version_code"),
        UniqueConstraint("legacy_cross_section_id", name="uq_hydraulic_cross_section_legacy"),
        Index("ix_hydraulic_cross_section_location_gist", "location", postgresql_using="gist"),
        Index("ix_hydraulic_cross_section_axis_gist", "axis", postgresql_using="gist"),
        Index("ix_hydraulic_cross_section_branch_chainage", "branch_id", "chainage_m"),
        {"schema": "hydraulic"},
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    dataset_version_id: Mapped[int] = mapped_column(nullable=False)
    branch_id: Mapped[int] = mapped_column(nullable=False)
    legacy_cross_section_id: Mapped[int | None] = mapped_column()
    section_code: Mapped[str] = mapped_column(String(64), nullable=False)
    section_name: Mapped[str] = mapped_column(String(128), nullable=False)
    chainage: Mapped[float] = mapped_column("chainage_m", Float, nullable=False)
    computed_chainage_m: Mapped[float | None] = mapped_column(Float)
    chainage_source: Mapped[str] = mapped_column(String(24), nullable=False, server_default="imported")
    snap_distance_m: Mapped[float | None] = mapped_column(Float)
    location_geometry: Mapped[Any] = mapped_column(
        "location", Geometry("POINT", srid=4490, spatial_index=False), nullable=False
    )
    axis_geometry: Mapped[Any | None] = mapped_column(
        "axis", Geometry("LINESTRING", srid=4490, spatial_index=False)
    )
    left_bank: Mapped[Any | None] = mapped_column(Geometry("POINT", srid=4490, spatial_index=False))
    right_bank: Mapped[Any | None] = mapped_column(Geometry("POINT", srid=4490, spatial_index=False))
    orientation_status: Mapped[str] = mapped_column(String(16), nullable=False, server_default="pending")
    manual_override_reason: Mapped[str | None] = mapped_column(Text)
    manual_override_actor: Mapped[str | None] = mapped_column(String(128))
    manual_override_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, server_default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class HydraulicCrossSectionProfile(Base):
    """Represent one Topography ID or survey revision at a cross-section location."""

    __tablename__ = "cross_section_profile"
    __table_args__ = (
        CheckConstraint("default_manning_n > 0", name="ck_hydraulic_profile_manning"),
        ForeignKeyConstraint(
            ["cross_section_id", "dataset_version_id"],
            ["hydraulic.cross_section.id", "hydraulic.cross_section.dataset_version_id"],
            name="fk_hydraulic_profile_section_version", ondelete="CASCADE",
        ),
        UniqueConstraint("id", "dataset_version_id", name="uq_hydraulic_profile_id_version"),
        UniqueConstraint("cross_section_id", "topography_id", name="uq_hydraulic_profile_section_topography"),
        Index("ix_hydraulic_profile_version_active", "dataset_version_id", "is_active"),
        Index(
            "uq_hydraulic_profile_one_active",
            "cross_section_id",
            unique=True,
            postgresql_where=text("is_active"),
        ),
        {"schema": "hydraulic"},
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    dataset_version_id: Mapped[int] = mapped_column(nullable=False)
    cross_section_id: Mapped[int] = mapped_column(nullable=False)
    topography_id: Mapped[str] = mapped_column(String(64), nullable=False)
    survey_date: Mapped[date | None] = mapped_column(Date)
    survey_method: Mapped[str | None] = mapped_column(String(64))
    vertical_datum: Mapped[str] = mapped_column(String(64), nullable=False, server_default="unknown")
    vertical_unit: Mapped[str] = mapped_column(String(16), nullable=False, server_default="m")
    default_manning_n: Mapped[float] = mapped_column(Float, nullable=False)
    source_revision: Mapped[str | None] = mapped_column(String(64))
    profile_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, server_default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class HydraulicCrossSectionPoint(Base):
    """Store one ordered profile point with markers and optional surveyed XYZ."""

    __tablename__ = "cross_section_point"
    __table_args__ = (
        CheckConstraint("point_order >= 0", name="ck_hydraulic_cross_section_point_order"),
        CheckConstraint("offset_m >= 0", name="ck_hydraulic_cross_section_point_offset"),
        CheckConstraint(
            "marker_type IN ('none','left_bank','right_bank','left_levee','right_levee',"
            "'low_flow_left','low_flow_right','thalweg')",
            name="ck_hydraulic_cross_section_point_marker",
        ),
        ForeignKeyConstraint(
            ["profile_id", "dataset_version_id"],
            ["hydraulic.cross_section_profile.id", "hydraulic.cross_section_profile.dataset_version_id"],
            name="fk_hydraulic_cross_section_point_profile_version", ondelete="CASCADE",
        ),
        UniqueConstraint("id", "dataset_version_id", name="uq_hydraulic_point_id_version"),
        UniqueConstraint("profile_id", "point_order", name="uq_hydraulic_point_profile_order"),
        UniqueConstraint("profile_id", "offset_m", name="uq_hydraulic_point_profile_offset"),
        Index("ix_hydraulic_cross_section_point_geometry_gist", "geometry", postgresql_using="gist"),
        Index("ix_hydraulic_cross_section_point_profile", "profile_id", "point_order"),
        {"schema": "hydraulic"},
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    dataset_version_id: Mapped[int] = mapped_column(nullable=False)
    profile_id: Mapped[int] = mapped_column(nullable=False)
    sequence: Mapped[int] = mapped_column("point_order", Integer, nullable=False)
    distance: Mapped[float] = mapped_column("offset_m", Float, nullable=False)
    elevation: Mapped[float] = mapped_column("elevation_m", Float, nullable=False)
    marker_type: Mapped[str] = mapped_column(String(24), nullable=False, server_default="none")
    geometry: Mapped[Any | None] = mapped_column(Geometry("POINT", srid=4490, spatial_index=False))
    source_x: Mapped[float | None] = mapped_column(Float)
    source_y: Mapped[float | None] = mapped_column(Float)
    source_z: Mapped[float | None] = mapped_column(Float)
    source_crs: Mapped[str | None] = mapped_column(String(64))
    source_axis_mapping: Mapped[str | None] = mapped_column(String(32))
    point_code: Mapped[str | None] = mapped_column(String(64))
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, server_default="{}")


class HydraulicRoughnessZone(Base):
    """Define a non-overlapping Manning roughness interval on one profile."""

    __tablename__ = "cross_section_roughness_zone"
    __table_args__ = (
        CheckConstraint("zone_order >= 0", name="ck_hydraulic_roughness_zone_order"),
        CheckConstraint("offset_end_m > offset_start_m", name="ck_hydraulic_roughness_zone_range"),
        CheckConstraint("manning_n > 0", name="ck_hydraulic_roughness_zone_manning"),
        ForeignKeyConstraint(
            ["profile_id", "dataset_version_id"],
            ["hydraulic.cross_section_profile.id", "hydraulic.cross_section_profile.dataset_version_id"],
            name="fk_hydraulic_roughness_zone_profile_version", ondelete="CASCADE",
        ),
        UniqueConstraint("id", "dataset_version_id", name="uq_hydraulic_roughness_id_version"),
        UniqueConstraint("profile_id", "zone_order", name="uq_hydraulic_roughness_profile_order"),
        Index("ix_hydraulic_roughness_profile", "profile_id", "zone_order"),
        {"schema": "hydraulic"},
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    dataset_version_id: Mapped[int] = mapped_column(nullable=False)
    profile_id: Mapped[int] = mapped_column(nullable=False)
    zone_order: Mapped[int] = mapped_column(Integer, nullable=False)
    offset_start_m: Mapped[float] = mapped_column(Float, nullable=False)
    offset_end_m: Mapped[float] = mapped_column(Float, nullable=False)
    manning_n: Mapped[float] = mapped_column(Float, nullable=False)
    zone_type: Mapped[str] = mapped_column(String(32), nullable=False, server_default="channel")


class HydraulicCrossSectionProcessing(Base):
    """Cache one deterministic hydraulic table generated from a profile hash."""

    __tablename__ = "cross_section_processing"
    __table_args__ = (
        CheckConstraint("vertical_step_m > 0", name="ck_hydraulic_processing_step"),
        CheckConstraint("status IN ('pending','ready','failed')", name="ck_hydraulic_processing_status"),
        ForeignKeyConstraint(
            ["profile_id", "dataset_version_id"],
            ["hydraulic.cross_section_profile.id", "hydraulic.cross_section_profile.dataset_version_id"],
            name="fk_hydraulic_processing_profile_version", ondelete="CASCADE",
        ),
        UniqueConstraint("id", "dataset_version_id", name="uq_hydraulic_processing_id_version"),
        UniqueConstraint(
            "profile_id", "profile_hash", "processor_version", "vertical_step_m",
            name="uq_hydraulic_processing_cache_key",
        ),
        Index("ix_hydraulic_processing_profile", "profile_id"),
        {"schema": "hydraulic"},
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    dataset_version_id: Mapped[int] = mapped_column(nullable=False)
    profile_id: Mapped[int] = mapped_column(nullable=False)
    profile_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    processor_version: Mapped[str] = mapped_column(String(64), nullable=False)
    vertical_step_m: Mapped[float] = mapped_column(Float, nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    minimum_stage_m: Mapped[float | None] = mapped_column(Float)
    maximum_stage_m: Mapped[float | None] = mapped_column(Float)
    generated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    diagnostics_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, server_default="{}")


class HydraulicCrossSectionHydraulicRow(Base):
    """Store one finite stage/property row belonging to a processed profile."""

    __tablename__ = "cross_section_hydraulic_row"
    __table_args__ = (
        ForeignKeyConstraint(
            ["processing_id", "dataset_version_id"],
            ["hydraulic.cross_section_processing.id", "hydraulic.cross_section_processing.dataset_version_id"],
            name="fk_hydraulic_row_processing_version", ondelete="CASCADE",
        ),
        UniqueConstraint("processing_id", "stage_m", name="uq_hydraulic_row_processing_stage"),
        Index("ix_hydraulic_row_processing", "processing_id", "stage_m"),
        {"schema": "hydraulic"},
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    dataset_version_id: Mapped[int] = mapped_column(nullable=False)
    processing_id: Mapped[int] = mapped_column(nullable=False)
    stage_m: Mapped[float] = mapped_column(Float, nullable=False)
    area_m2: Mapped[float] = mapped_column(Float, nullable=False)
    top_width_m: Mapped[float] = mapped_column(Float, nullable=False)
    wetted_perimeter_m: Mapped[float] = mapped_column(Float, nullable=False)
    hydraulic_radius_m: Mapped[float] = mapped_column(Float, nullable=False)
    conveyance: Mapped[float] = mapped_column(Float, nullable=False)


class HydraulicValidationRun(Base):
    """Persist one deterministic network, import, or profile validation execution."""

    __tablename__ = "validation_run"
    __table_args__ = (
        CheckConstraint("status IN ('running','passed','failed')", name="ck_hydraulic_validation_run_status"),
        ForeignKeyConstraint(
            ["network_id", "dataset_version_id"],
            ["hydraulic.network.id", "hydraulic.network.dataset_version_id"],
            name="fk_hydraulic_validation_run_network_version", ondelete="CASCADE",
        ),
        UniqueConstraint("run_code", name="uq_hydraulic_validation_run_code"),
        {"schema": "hydraulic"},
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    run_code: Mapped[str] = mapped_column(String(32), nullable=False)
    dataset_version_id: Mapped[int] = mapped_column(ForeignKey("dataset_version.id", ondelete="CASCADE"), nullable=False)
    import_job_id: Mapped[int | None] = mapped_column(ForeignKey("hydraulic.import_job.id", ondelete="SET NULL"))
    network_id: Mapped[int | None] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    summary: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, server_default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class HydraulicValidationResult(Base):
    """Store one machine-readable validation finding with optional GIS issue linkage."""

    __tablename__ = "validation_result"
    __table_args__ = (
        CheckConstraint(
            "severity IN ('error','warning','info','passed')",
            name="ck_hydraulic_validation_result_severity",
        ),
        Index("ix_hydraulic_validation_result_run", "run_id"),
        {"schema": "hydraulic"},
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("hydraulic.validation_run.id", ondelete="CASCADE"), nullable=False)
    gis_validation_issue_id: Mapped[int | None] = mapped_column(ForeignKey("gis_validation_issue.id", ondelete="SET NULL"))
    severity: Mapped[str] = mapped_column(String(16), nullable=False)
    rule_code: Mapped[str] = mapped_column(String(64), nullable=False)
    entity_type: Mapped[str] = mapped_column(String(32), nullable=False)
    entity_id: Mapped[int | None] = mapped_column(Integer)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    context: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, server_default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
