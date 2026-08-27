"""Phase 2 水利数据库的 SQLAlchemy/PostGIS 统一模型元数据。"""

from datetime import date, datetime
from typing import Any

from geoalchemy2 import Geometry
from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    Float,
    ForeignKey,
    ForeignKeyConstraint,
    Identity,
    Index,
    Integer,
    JSON,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    """集中保存全部数据库模型元数据，作为 Alembic 唯一发现入口。"""


class FeatureState(Base):
    """Store one versioned observed or simulated feature state in TimescaleDB."""

    __tablename__ = "feature_state"
    __table_args__ = (
        CheckConstraint(
            "feature_type IN ('water_level','flow','rainfall','gate','pump','flood_risk')",
            name="ck_feature_state_type",
        ),
        CheckConstraint(
            "source IN ('observation','simulation','dispatch','import')",
            name="ck_feature_state_source",
        ),
        UniqueConstraint(
            "dataset_version_id", "feature_type", "feature_id", "timestamp", "source",
            name="uq_feature_state_identity",
        ),
        Index(
            "ix_feature_state_feature_time", "dataset_version_id", "feature_type",
            "feature_id", "timestamp",
        ),
        Index("ix_feature_state_geometry_gist", "geometry", postgresql_using="gist"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), primary_key=True)
    dataset_version_id: Mapped[int] = mapped_column(
        ForeignKey("dataset_version.id", ondelete="CASCADE"), nullable=False
    )
    feature_type: Mapped[str] = mapped_column(String(32), nullable=False)
    feature_id: Mapped[int] = mapped_column(Integer, nullable=False)
    state_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    geometry: Mapped[Any] = mapped_column(
        Geometry(geometry_type="GEOMETRY", srid=4490, spatial_index=False), nullable=False
    )
    source: Mapped[str] = mapped_column(String(32), nullable=False)
    task_id: Mapped[int | None] = mapped_column(
        ForeignKey("simulation_task.id", ondelete="SET NULL")
    )


class SimulationLayer(Base):
    """Register one versioned MVT, COG, WMS, or 3D Tiles simulation asset."""

    __tablename__ = "simulation_layer"
    __table_args__ = (
        CheckConstraint(
            "layer_type IN ('water_level','velocity','flood_risk','terrain','facility_3d')",
            name="ck_simulation_layer_type",
        ),
        CheckConstraint(
            "service_type IN ('COG','TITILER','MVT','WMS','3D_TILES')",
            name="ck_simulation_layer_service_type",
        ),
        CheckConstraint(
            "time_end IS NULL OR time_start IS NULL OR time_end >= time_start",
            name="ck_simulation_layer_time_range",
        ),
        UniqueConstraint(
            "dataset_version_id", "name", "version", name="uq_simulation_layer_version_name"
        ),
        Index("ix_simulation_layer_lookup", "dataset_version_id", "layer_type", "task_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    dataset_version_id: Mapped[int] = mapped_column(
        ForeignKey("dataset_version.id", ondelete="CASCADE"), nullable=False
    )
    task_id: Mapped[int | None] = mapped_column(
        ForeignKey("simulation_task.id", ondelete="SET NULL")
    )
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    layer_type: Mapped[str] = mapped_column(String(32), nullable=False)
    time_start: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    time_end: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    service_type: Mapped[str] = mapped_column(String(24), nullable=False)
    service_url: Mapped[str] = mapped_column(Text, nullable=False)
    style: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    version: Mapped[str] = mapped_column(String(64), nullable=False)
    created_time: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class DatasetVersion(Base):
    """标识一组不可混用的河网、断面、建筑物和模型参数数据。"""

    __tablename__ = "dataset_version"
    __table_args__ = (
        CheckConstraint(
            "status IN ('draft','review','approved','published','retired','rejected')",
            name="ck_dataset_version_status",
        ),
        UniqueConstraint("version", name="uq_dataset_version_version"),
        UniqueConstraint("source_batch_id", name="uq_dataset_version_source_batch_id"),
        Index("ix_dataset_version_status", "status"),
        Index("ix_dataset_version_content_hash", "content_hash"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    version: Mapped[str] = mapped_column(String(32), nullable=False)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    creator: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, server_default="draft"
    )
    parent_version_id: Mapped[int | None] = mapped_column(
        ForeignKey("dataset_version.id", ondelete="RESTRICT")
    )
    source_batch_id: Mapped[int | None] = mapped_column(
        ForeignKey("gis_import_batch.id", ondelete="RESTRICT")
    )
    content_hash: Mapped[str | None] = mapped_column(String(64))
    change_summary: Mapped[str | None] = mapped_column(Text)
    reviewed_by: Mapped[str | None] = mapped_column(String(64))
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    approved_by: Mapped[str | None] = mapped_column(String(64))
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    retired_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_time: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    rivers: Mapped[list["River"]] = relationship(back_populates="dataset_version")
    parameters: Mapped[list["ModelParameter"]] = relationship(back_populates="dataset_version")
    boundary_conditions: Mapped[list["BoundaryCondition"]] = relationship(
        back_populates="dataset_version"
    )
    simulation_cases: Mapped[list["SimulationCase"]] = relationship(
        back_populates="dataset_version"
    )
    annotations: Mapped[list["MapAnnotation"]] = relationship(
        back_populates="dataset_version", cascade="all, delete-orphan"
    )


class GISCatalogLayer(Base):
    """Store the PostGIS-owned allow-list for GeoServer-published map layers.

    The physical table name is retained for a no-copy migration from GIS-OPT-2,
    but active rows now describe one renderer only: GeoServer WMS over the
    version-filtered ``publish`` schema.
    """

    __tablename__ = "gis_layer_registry"
    __table_args__ = (
        CheckConstraint(
            "layer_key ~ '^[a-z][a-z0-9_]{1,62}$'",
            name="ck_gis_layer_registry_layer_key",
        ),
        CheckConstraint(
            "active IS NOT TRUE OR source_schema = 'publish'",
            name="ck_gis_catalog_active_source",
        ),
        CheckConstraint(
            "source_relation ~ '^[a-z][a-z0-9_]{1,62}$'",
            name="ck_gis_layer_registry_source_relation",
        ),
        CheckConstraint(
            "geometry_type IN ('POINT','LINESTRING','POLYGON','MULTIPOINT',"
            "'MULTILINESTRING','MULTIPOLYGON','NONE')",
            name="ck_gis_layer_registry_geometry_type",
        ),
        CheckConstraint(
            "native_crs ~ '^EPSG:[0-9]{4,6}$'",
            name="ck_gis_layer_registry_native_crs",
        ),
        CheckConstraint(
            "active IS NOT TRUE OR service_mode = 'GEOSERVER_WMS'",
            name="ck_gis_catalog_active_service",
        ),
        CheckConstraint(
            "active IS NOT TRUE OR render_mode = 'RASTER_WMS'",
            name="ck_gis_catalog_active_render",
        ),
        CheckConstraint(
            "dataset_filter_field IS NULL OR dataset_filter_field = 'dataset_version_id'",
            name="ck_gis_layer_registry_filter_field",
        ),
        CheckConstraint(
            "cache_mode IN ('NONE','CLIENT_PRIVATE','VERSIONED_PUBLIC')",
            name="ck_gis_layer_registry_cache_mode",
        ),
        CheckConstraint(
            "identify_mode IN ('NONE','FEATURE_INFO','DETAIL_API','CLIENT_PICK')",
            name="ck_gis_layer_registry_identify_mode",
        ),
        CheckConstraint(
            "default_opacity >= 0 AND default_opacity <= 1",
            name="ck_gis_layer_registry_opacity",
        ),
        UniqueConstraint("layer_key", name="uq_gis_layer_registry_layer_key"),
        Index(
            "uq_gis_layer_registry_qgis_short_name",
            "qgis_short_name",
            unique=True,
            postgresql_where="qgis_short_name IS NOT NULL",
        ),
        Index("ix_gis_layer_registry_active_order", "active", "display_order"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    layer_key: Mapped[str] = mapped_column(String(63), nullable=False)
    title: Mapped[str] = mapped_column(String(128), nullable=False)
    group_key: Mapped[str] = mapped_column(String(63), nullable=False)
    source_schema: Mapped[str] = mapped_column(String(16), nullable=False)
    source_relation: Mapped[str] = mapped_column(String(63), nullable=False)
    geometry_type: Mapped[str] = mapped_column(String(24), nullable=False)
    native_crs: Mapped[str] = mapped_column(String(16), nullable=False)
    qgis_short_name: Mapped[str | None] = mapped_column(String(63))
    service_mode: Mapped[str] = mapped_column(String(32), nullable=False)
    render_mode: Mapped[str] = mapped_column(String(32), nullable=False)
    dataset_filter_field: Mapped[str | None] = mapped_column(String(63))
    identify_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    legend_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    search_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    capabilities: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, server_default="{}")
    feature_info_fields: Mapped[list[str]] = mapped_column(JSONB, nullable=False, server_default="[]")
    cache_mode: Mapped[str] = mapped_column(String(24), nullable=False, server_default="NONE")
    identify_mode: Mapped[str] = mapped_column(String(24), nullable=False, server_default="NONE")
    detail_route_key: Mapped[str | None] = mapped_column(String(63))
    model_entity_type: Mapped[str | None] = mapped_column(String(63))
    display_order: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    default_visible: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")
    default_opacity: Mapped[float] = mapped_column(Float, nullable=False, server_default="1")
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")
    revision: Mapped[int] = mapped_column(Integer, nullable=False, server_default="1")
    created_by: Mapped[str] = mapped_column(String(64), nullable=False, server_default="migration")
    updated_by: Mapped[str] = mapped_column(String(64), nullable=False, server_default="migration")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)


# Compatibility alias for migrations and older offline tooling. Runtime code
# imports ``GISCatalogLayer`` so the deprecated Registry concept cannot become
# a second browser-facing source of truth again.
GISLayerRegistry = GISCatalogLayer


class BasemapRegistry(Base):
    """Register deployment-owned basemap endpoint keys without storing arbitrary URLs."""

    __tablename__ = "basemap_registry"
    __table_args__ = (
        CheckConstraint(
            "basemap_key ~ '^[a-z][a-z0-9_]{1,62}$'",
            name="ck_basemap_registry_key",
        ),
        CheckConstraint(
            "basemap_type IN ('XYZ','WMS','WMTS','COG','MVT','ARCGIS_REST')",
            name="ck_basemap_registry_type",
        ),
        CheckConstraint(
            "endpoint_key ~ '^[a-z][a-z0-9_]{1,62}$'",
            name="ck_basemap_registry_endpoint_key",
        ),
        CheckConstraint(
            "native_crs ~ '^EPSG:[0-9]{4,6}$'",
            name="ck_basemap_registry_native_crs",
        ),
        CheckConstraint(
            "default_opacity >= 0 AND default_opacity <= 1",
            name="ck_basemap_registry_opacity",
        ),
        UniqueConstraint("basemap_key", name="uq_basemap_registry_key"),
        UniqueConstraint("endpoint_key", name="uq_basemap_registry_endpoint_key"),
        Index("ix_basemap_registry_active_order", "active", "display_order"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    basemap_key: Mapped[str] = mapped_column(String(63), nullable=False)
    title: Mapped[str] = mapped_column(String(128), nullable=False)
    basemap_type: Mapped[str] = mapped_column(String(24), nullable=False)
    endpoint_key: Mapped[str] = mapped_column(String(63), nullable=False)
    native_crs: Mapped[str] = mapped_column(String(16), nullable=False)
    credit: Mapped[str] = mapped_column(String(256), nullable=False)
    display_order: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    default_visible: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")
    default_opacity: Mapped[float] = mapped_column(Float, nullable=False, server_default="1")
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")
    revision: Mapped[int] = mapped_column(Integer, nullable=False, server_default="1")
    created_by: Mapped[str] = mapped_column(String(64), nullable=False, server_default="migration")
    updated_by: Mapped[str] = mapped_column(String(64), nullable=False, server_default="migration")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)


class OpenAdministrativeArea(Base):
    """Store globally reusable open administrative boundaries with provenance."""

    __tablename__ = "administrative_area"
    __table_args__ = (
        UniqueConstraint("source", "source_id", name="uq_reference_administrative_area_source_id"),
        Index("ix_reference_administrative_area_geometry_gist", "geometry", postgresql_using="gist"),
        {"schema": "reference_data"},
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    source: Mapped[str] = mapped_column(String(64), nullable=False)
    source_id: Mapped[str] = mapped_column(String(160), nullable=False)
    source_snapshot: Mapped[str] = mapped_column(String(80), nullable=False)
    name: Mapped[str] = mapped_column(String(256), nullable=False)
    name_zh: Mapped[str] = mapped_column(String(256), nullable=False)
    address: Mapped[str | None] = mapped_column(String(256))
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, server_default="{}")
    geometry: Mapped[Any] = mapped_column(
        Geometry(geometry_type="MULTIPOLYGON", srid=4490, spatial_index=False), nullable=False
    )
    imported_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    administrative_level: Mapped[str] = mapped_column(String(32), nullable=False)


class OpenRoad(Base):
    """Store version-independent OpenStreetMap road centerlines for reference rendering."""

    __tablename__ = "road"
    __table_args__ = (
        UniqueConstraint("source", "source_id", name="uq_reference_road_source_id"),
        Index("ix_reference_road_geometry_gist", "geometry", postgresql_using="gist"),
        {"schema": "reference_data"},
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    source: Mapped[str] = mapped_column(String(64), nullable=False)
    source_id: Mapped[str] = mapped_column(String(160), nullable=False)
    source_snapshot: Mapped[str] = mapped_column(String(80), nullable=False)
    name: Mapped[str] = mapped_column(String(256), nullable=False)
    name_zh: Mapped[str | None] = mapped_column(String(256))
    address: Mapped[str | None] = mapped_column(String(256))
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, server_default="{}")
    geometry: Mapped[Any] = mapped_column(
        Geometry(geometry_type="MULTILINESTRING", srid=4490, spatial_index=False), nullable=False
    )
    imported_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    road_type: Mapped[str] = mapped_column(String(32), nullable=False)


class OpenWaterway(Base):
    """Store version-independent OpenStreetMap waterway centerlines for reference rendering."""

    __tablename__ = "waterway"
    __table_args__ = (
        UniqueConstraint("source", "source_id", name="uq_reference_waterway_source_id"),
        Index("ix_reference_waterway_geometry_gist", "geometry", postgresql_using="gist"),
        {"schema": "reference_data"},
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    source: Mapped[str] = mapped_column(String(64), nullable=False)
    source_id: Mapped[str] = mapped_column(String(160), nullable=False)
    source_snapshot: Mapped[str] = mapped_column(String(80), nullable=False)
    name: Mapped[str] = mapped_column(String(256), nullable=False)
    name_zh: Mapped[str | None] = mapped_column(String(256))
    address: Mapped[str | None] = mapped_column(String(256))
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, server_default="{}")
    geometry: Mapped[Any] = mapped_column(
        Geometry(geometry_type="MULTILINESTRING", srid=4490, spatial_index=False), nullable=False
    )
    imported_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    waterway_type: Mapped[str] = mapped_column(String(32), nullable=False)


class GISImportBatch(Base):
    """Track one immutable source landing and its controlled governance lifecycle."""

    __tablename__ = "gis_import_batch"
    __table_args__ = (
        CheckConstraint(
            "entity_type IN ('river','cross_section','gate','pump')",
            name="ck_gis_import_batch_entity_type",
        ),
        CheckConstraint(
            "status IN ('created','staged','validating','validation_failed','validated',"
            "'in_review','changes_requested','rejected','approved','promoting','promoted',"
            "'published')",
            name="ck_gis_import_batch_status",
        ),
        CheckConstraint("source_size >= 0", name="ck_gis_import_batch_source_size"),
        CheckConstraint(
            "source_hash_sha256 ~ '^[0-9a-f]{64}$'",
            name="ck_gis_import_batch_source_hash",
        ),
        CheckConstraint("target_crs = 'EPSG:4490'", name="ck_gis_import_batch_target_crs"),
        CheckConstraint(
            "(parent_version_id IS NULL AND parent_content_hash IS NULL) OR "
            "(parent_version_id IS NOT NULL AND parent_content_hash IS NOT NULL)",
            name="ck_gis_import_batch_parent_hash_pair",
        ),
        UniqueConstraint("batch_code", name="uq_gis_import_batch_code"),
        UniqueConstraint("raw_table_name", name="uq_gis_import_batch_raw_table"),
        UniqueConstraint(
            "promoted_dataset_version_id",
            name="uq_gis_import_batch_promoted_version",
        ),
        Index("ix_gis_import_batch_status", "status"),
        Index("ix_gis_import_batch_parent_version_id", "parent_version_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    batch_code: Mapped[str] = mapped_column(String(36), nullable=False)
    entity_type: Mapped[str] = mapped_column(String(32), nullable=False)
    source_filename: Mapped[str] = mapped_column(String(255), nullable=False)
    source_format: Mapped[str] = mapped_column(String(64), nullable=False)
    source_size: Mapped[int] = mapped_column(BigInteger, nullable=False)
    source_hash_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    source_crs: Mapped[str] = mapped_column(String(64), nullable=False)
    target_crs: Mapped[str] = mapped_column(
        String(64), nullable=False, server_default="EPSG:4490"
    )
    mapping_version: Mapped[str] = mapped_column(String(32), nullable=False)
    operator: Mapped[str] = mapped_column(String(64), nullable=False)
    survey_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(
        String(24), nullable=False, server_default="created"
    )
    raw_location: Mapped[str | None] = mapped_column(Text)
    raw_table_name: Mapped[str | None] = mapped_column(String(63))
    metadata_json: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default="{}"
    )
    notes: Mapped[str | None] = mapped_column(Text)
    parent_version_id: Mapped[int | None] = mapped_column(
        ForeignKey("dataset_version.id", ondelete="RESTRICT")
    )
    parent_content_hash: Mapped[str | None] = mapped_column(String(64))
    staging_content_hash: Mapped[str | None] = mapped_column(String(64))
    staged_by: Mapped[str | None] = mapped_column(String(64))
    staged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    review_submitted_by: Mapped[str | None] = mapped_column(String(64))
    review_submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    promoted_dataset_version_id: Mapped[int | None] = mapped_column(
        ForeignKey(
            "dataset_version.id",
            name="fk_gis_import_batch_promoted_dataset_version_id",
            ondelete="RESTRICT",
        )
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class GISValidationRun(Base):
    """Persist one authoritative validation generation for a staging batch."""

    __tablename__ = "gis_validation_run"
    __table_args__ = (
        CheckConstraint(
            "status IN ('running','passed','failed')",
            name="ck_gis_validation_run_status",
        ),
        UniqueConstraint(
            "batch_id", "id", name="uq_gis_validation_run_batch_id_id"
        ),
        Index("ix_gis_validation_run_batch_id", "batch_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    batch_id: Mapped[int] = mapped_column(
        ForeignKey("gis_import_batch.id", ondelete="CASCADE"), nullable=False
    )
    ruleset_version: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    staging_content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    summary_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)


class GISValidationIssue(Base):
    """Store one queryable validation issue tied to a feature and rule."""

    __tablename__ = "gis_validation_issue"
    __table_args__ = (
        CheckConstraint(
            "entity_type IN ('river','cross_section','gate','pump')",
            name="ck_gis_validation_issue_entity_type",
        ),
        CheckConstraint(
            "severity IN ('error','warning','info')",
            name="ck_gis_validation_issue_severity",
        ),
        ForeignKeyConstraint(
            ["batch_id", "validation_run_id"],
            ["gis_validation_run.batch_id", "gis_validation_run.id"],
            name="fk_gis_validation_issue_batch_run",
            ondelete="CASCADE",
        ),
        Index("ix_gis_validation_issue_batch_severity", "batch_id", "severity"),
        Index("ix_gis_validation_issue_geometry_gist", "geometry", postgresql_using="gist"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    validation_run_id: Mapped[int] = mapped_column(nullable=False)
    batch_id: Mapped[int] = mapped_column(
        ForeignKey("gis_import_batch.id", ondelete="CASCADE"), nullable=False
    )
    entity_type: Mapped[str] = mapped_column(String(32), nullable=False)
    feature_ref: Mapped[str | None] = mapped_column(String(128))
    rule_code: Mapped[str] = mapped_column(String(64), nullable=False)
    severity: Mapped[str] = mapped_column(String(16), nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    geometry: Mapped[Any | None] = mapped_column(
        Geometry(geometry_type="GEOMETRY", srid=4490, spatial_index=False)
    )
    details_json: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default="{}"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    resolution_note: Mapped[str | None] = mapped_column(Text)


class GISReview(Base):
    """Append one immutable human review decision for a validated batch generation."""

    __tablename__ = "gis_review"
    __table_args__ = (
        CheckConstraint(
            "decision IN ('approve','reject','request_changes')",
            name="ck_gis_review_decision",
        ),
        ForeignKeyConstraint(
            ["batch_id", "validation_run_id"],
            ["gis_validation_run.batch_id", "gis_validation_run.id"],
            name="fk_gis_review_batch_run",
            ondelete="RESTRICT",
        ),
        Index("ix_gis_review_batch_id", "batch_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    batch_id: Mapped[int] = mapped_column(
        ForeignKey("gis_import_batch.id", ondelete="CASCADE"), nullable=False
    )
    validation_run_id: Mapped[int] = mapped_column(nullable=False)
    staging_content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    reviewer: Mapped[str] = mapped_column(String(64), nullable=False)
    decision: Mapped[str] = mapped_column(String(24), nullable=False)
    comment: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class GISPublication(Base):
    """Audit one publication manifest without changing the existing service contracts."""

    __tablename__ = "gis_publication"
    __table_args__ = (
        CheckConstraint(
            "publication_status IN ('pending','published','failed','retired')",
            name="ck_gis_publication_status",
        ),
        UniqueConstraint("dataset_version_id", name="uq_gis_publication_dataset_version_id"),
        Index("ix_gis_publication_status", "publication_status"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    dataset_version_id: Mapped[int] = mapped_column(
        ForeignKey("dataset_version.id", ondelete="RESTRICT"), nullable=False
    )
    publication_status: Mapped[str] = mapped_column(String(16), nullable=False)
    published_by: Mapped[str] = mapped_column(String(64), nullable=False)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    previous_publication_id: Mapped[int | None] = mapped_column(
        ForeignKey("gis_publication.id", ondelete="SET NULL")
    )
    manifest_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class _QGISStagingMixin:
    """Provide immutable provenance and editable-state metadata to every staging layer."""

    id: Mapped[int] = mapped_column(primary_key=True)
    batch_id: Mapped[int] = mapped_column(
        ForeignKey("gis_import_batch.id", ondelete="CASCADE"), nullable=False
    )
    source_feature_id: Mapped[str] = mapped_column(String(128), nullable=False)
    operation: Mapped[str] = mapped_column(String(12), nullable=False, server_default="upsert")
    quality_status: Mapped[str] = mapped_column(
        String(16), nullable=False, server_default="pending"
    )
    source_crs: Mapped[str] = mapped_column(String(64), nullable=False)
    target_crs: Mapped[str] = mapped_column(
        String(64), nullable=False, server_default="EPSG:4490"
    )
    source_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    operator: Mapped[str] = mapped_column(String(64), nullable=False)
    survey_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    source_payload: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default="{}"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class QGISStagingRiver(_QGISStagingMixin, Base):
    """Expose stable river fields for direct QGIS editing in the staging schema."""

    __tablename__ = "river"
    __table_args__ = (
        CheckConstraint("operation IN ('upsert','delete')", name="ck_qgis_river_operation"),
        CheckConstraint(
            "quality_status IN ('pending','passed','failed')",
            name="ck_qgis_river_quality_status",
        ),
        CheckConstraint("target_crs = 'EPSG:4490'", name="ck_qgis_river_target_crs"),
        UniqueConstraint("batch_id", "source_feature_id", name="uq_qgis_river_source"),
        UniqueConstraint("batch_id", "code", name="uq_qgis_river_code"),
        Index("ix_qgis_river_geometry_gist", "geometry", postgresql_using="gist"),
        {"schema": "staging_qgis"},
    )

    name: Mapped[str] = mapped_column(String(128), nullable=False)
    code: Mapped[str] = mapped_column(String(64), nullable=False)
    length: Mapped[float] = mapped_column(Float, nullable=False)
    level: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False, server_default="active")
    description: Mapped[str | None] = mapped_column(Text)
    geometry: Mapped[Any] = mapped_column(
        Geometry(geometry_type="LINESTRING", srid=4490, spatial_index=False), nullable=False
    )


class QGISStagingCrossSection(_QGISStagingMixin, Base):
    """Expose stable cross-section attributes and point geometry for QGIS editing."""

    __tablename__ = "cross_section"
    __table_args__ = (
        CheckConstraint("operation IN ('upsert','delete')", name="ck_qgis_section_operation"),
        CheckConstraint(
            "quality_status IN ('pending','passed','failed')",
            name="ck_qgis_section_quality_status",
        ),
        CheckConstraint("target_crs = 'EPSG:4490'", name="ck_qgis_section_target_crs"),
        UniqueConstraint("batch_id", "source_feature_id", name="uq_qgis_section_source"),
        UniqueConstraint("batch_id", "section_code", name="uq_qgis_section_code"),
        Index("ix_qgis_section_geometry_gist", "geometry", postgresql_using="gist"),
        {"schema": "staging_qgis"},
    )

    river_code: Mapped[str] = mapped_column(String(64), nullable=False)
    section_code: Mapped[str] = mapped_column(String(64), nullable=False)
    section_name: Mapped[str] = mapped_column(String(128), nullable=False)
    station: Mapped[float] = mapped_column(Float, nullable=False)
    points: Mapped[dict[str, list[list[float]]]] = mapped_column(JSONB, nullable=False)
    roughness: Mapped[float] = mapped_column(Float, nullable=False)
    elevation_min: Mapped[float] = mapped_column(Float, nullable=False)
    survey_date: Mapped[date | None] = mapped_column(Date)
    geometry: Mapped[Any] = mapped_column(
        Geometry(geometry_type="POINT", srid=4490, spatial_index=False), nullable=False
    )


class QGISStagingGate(_QGISStagingMixin, Base):
    """Expose gate design fields while deferring topology IDs to server promotion."""

    __tablename__ = "gate"
    __table_args__ = (
        CheckConstraint("operation IN ('upsert','delete')", name="ck_qgis_gate_operation"),
        CheckConstraint(
            "quality_status IN ('pending','passed','failed')",
            name="ck_qgis_gate_quality_status",
        ),
        CheckConstraint("target_crs = 'EPSG:4490'", name="ck_qgis_gate_target_crs"),
        UniqueConstraint("batch_id", "source_feature_id", name="uq_qgis_gate_source"),
        UniqueConstraint("batch_id", "gate_code", name="uq_qgis_gate_code"),
        Index("ix_qgis_gate_geometry_gist", "geometry", postgresql_using="gist"),
        {"schema": "staging_qgis"},
    )

    river_code: Mapped[str] = mapped_column(String(64), nullable=False)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    gate_code: Mapped[str] = mapped_column(String(64), nullable=False)
    gate_type: Mapped[str] = mapped_column(String(32), nullable=False)
    opening_direction: Mapped[str] = mapped_column(String(32), nullable=False)
    control_mode: Mapped[str] = mapped_column(String(32), nullable=False)
    width: Mapped[float] = mapped_column(Float, nullable=False)
    height: Mapped[float] = mapped_column(Float, nullable=False)
    max_flow: Mapped[float] = mapped_column(Float, nullable=False)
    bottom_elevation: Mapped[float] = mapped_column(Float, nullable=False)
    station: Mapped[float | None] = mapped_column(Float)
    crest_elevation: Mapped[float | None] = mapped_column(Float)
    discharge_coefficient: Mapped[float | None] = mapped_column(Float)
    minimum_opening: Mapped[float | None] = mapped_column(Float)
    maximum_opening: Mapped[float | None] = mapped_column(Float)
    opening_rate_limit: Mapped[float | None] = mapped_column(Float)
    minimum_hold_seconds: Mapped[float | None] = mapped_column(Float)
    allow_reverse_flow: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="false"
    )
    status: Mapped[str] = mapped_column(String(24), nullable=False, server_default="offline")
    geometry: Mapped[Any] = mapped_column(
        Geometry(geometry_type="POINT", srid=4490, spatial_index=False), nullable=False
    )


class QGISStagingPump(_QGISStagingMixin, Base):
    """Expose pump design fields while deferring topology IDs to server promotion."""

    __tablename__ = "pump"
    __table_args__ = (
        CheckConstraint("operation IN ('upsert','delete')", name="ck_qgis_pump_operation"),
        CheckConstraint(
            "quality_status IN ('pending','passed','failed')",
            name="ck_qgis_pump_quality_status",
        ),
        CheckConstraint("target_crs = 'EPSG:4490'", name="ck_qgis_pump_target_crs"),
        UniqueConstraint("batch_id", "source_feature_id", name="uq_qgis_pump_source"),
        UniqueConstraint("batch_id", "pump_code", name="uq_qgis_pump_code"),
        Index("ix_qgis_pump_geometry_gist", "geometry", postgresql_using="gist"),
        {"schema": "staging_qgis"},
    )

    river_code: Mapped[str] = mapped_column(String(64), nullable=False)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    pump_code: Mapped[str] = mapped_column(String(64), nullable=False)
    design_flow: Mapped[float] = mapped_column(Float, nullable=False)
    head: Mapped[float] = mapped_column(Float, nullable=False)
    power: Mapped[float] = mapped_column(Float, nullable=False)
    efficiency_curve: Mapped[dict[str, list[list[float]]]] = mapped_column(JSONB, nullable=False)
    head_curve: Mapped[dict[str, list[list[float]]] | None] = mapped_column(JSONB)
    transfer_type: Mapped[str | None] = mapped_column(String(24))
    unit_count: Mapped[int | None] = mapped_column(Integer)
    minimum_running_units: Mapped[int | None] = mapped_column(Integer)
    maximum_running_units: Mapped[int | None] = mapped_column(Integer)
    minimum_run_seconds: Mapped[float | None] = mapped_column(Float)
    minimum_stop_seconds: Mapped[float | None] = mapped_column(Float)
    maximum_starts_per_run: Mapped[int | None] = mapped_column(Integer)
    minimum_operating_head: Mapped[float | None] = mapped_column(Float)
    maximum_operating_head: Mapped[float | None] = mapped_column(Float)
    reverse_flow_protection: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="true"
    )
    control_mode: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False, server_default="offline")
    geometry: Mapped[Any] = mapped_column(
        Geometry(geometry_type="POINT", srid=4490, spatial_index=False), nullable=False
    )


class River(Base):
    """河道空间聚合根，几何为 CGCS2000 / EPSG:4490 LineString。"""

    __tablename__ = "river"
    __table_args__ = (
        CheckConstraint("length >= 0", name="ck_river_length_nonnegative"),
        CheckConstraint(
            "status IN ('active', 'inactive', 'planned')",
            name="ck_river_status",
        ),
        UniqueConstraint("dataset_version_id", "code", name="uq_river_version_code"),
        UniqueConstraint("id", "dataset_version_id", name="uq_river_id_version"),
        Index("ix_river_geometry_gist", "geometry", postgresql_using="gist"),
        Index("ix_river_dataset_version_id", "dataset_version_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    dataset_version_id: Mapped[int] = mapped_column(
        ForeignKey("dataset_version.id", ondelete="RESTRICT"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    code: Mapped[str] = mapped_column(String(64), nullable=False)
    length: Mapped[float] = mapped_column(Float, nullable=False)
    level: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False, server_default="active")
    description: Mapped[str | None] = mapped_column(Text)
    geometry: Mapped[Any] = mapped_column(
        Geometry(geometry_type="LINESTRING", srid=4490, spatial_index=False),
        nullable=False,
    )
    created_time: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    dataset_version: Mapped[DatasetVersion] = relationship(back_populates="rivers")
    segments: Mapped[list["RiverSegment"]] = relationship(back_populates="river")
    cross_sections: Mapped[list["CrossSection"]] = relationship(back_populates="river")
    gates: Mapped[list["Gate"]] = relationship(back_populates="river")
    pumps: Mapped[list["Pump"]] = relationship(back_populates="river")
    connections: Mapped[list["RiverConnection"]] = relationship(back_populates="river")


class RiverNode(Base):
    """保存河网端点和汇分流节点，并保留可直接审计的经纬度。"""

    __tablename__ = "river_node"
    __table_args__ = (
        CheckConstraint("longitude BETWEEN -180 AND 180", name="ck_river_node_longitude"),
        CheckConstraint("latitude BETWEEN -90 AND 90", name="ck_river_node_latitude"),
        CheckConstraint(
            "node_type IN ('start', 'end', 'confluence', 'bifurcation', 'gate_control')",
            name="ck_river_node_type",
        ),
        UniqueConstraint("dataset_version_id", "node_code", name="uq_river_node_version_code"),
        UniqueConstraint("id", "dataset_version_id", name="uq_river_node_id_version"),
        Index("ix_river_node_geometry_gist", "geometry", postgresql_using="gist"),
        Index("ix_river_node_dataset_version_id", "dataset_version_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    dataset_version_id: Mapped[int] = mapped_column(
        ForeignKey("dataset_version.id", ondelete="CASCADE"), nullable=False
    )
    node_code: Mapped[str] = mapped_column(String(64), nullable=False)
    node_type: Mapped[str] = mapped_column(String(24), nullable=False)
    longitude: Mapped[float] = mapped_column(Float, nullable=False)
    latitude: Mapped[float] = mapped_column(Float, nullable=False)
    geometry: Mapped[Any] = mapped_column(
        Geometry(geometry_type="POINT", srid=4490, spatial_index=False), nullable=False
    )


class RiverSegment(Base):
    """把复杂河道拆分为具有明确上下游节点的计算河段。"""

    __tablename__ = "river_segment"
    __table_args__ = (
        CheckConstraint("length >= 0", name="ck_river_segment_length_nonnegative"),
        ForeignKeyConstraint(
            ["river_id", "dataset_version_id"],
            ["river.id", "river.dataset_version_id"],
            name="fk_river_segment_river_version",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["upstream_node_id", "dataset_version_id"],
            ["river_node.id", "river_node.dataset_version_id"],
            name="fk_river_segment_upstream_version",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["downstream_node_id", "dataset_version_id"],
            ["river_node.id", "river_node.dataset_version_id"],
            name="fk_river_segment_downstream_version",
            ondelete="RESTRICT",
        ),
        UniqueConstraint("id", "dataset_version_id", name="uq_river_segment_id_version"),
        UniqueConstraint(
            "dataset_version_id", "segment_code", name="uq_river_segment_version_code"
        ),
        Index("ix_river_segment_geometry_gist", "geometry", postgresql_using="gist"),
        Index("ix_river_segment_river_id", "river_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    dataset_version_id: Mapped[int] = mapped_column(
        ForeignKey("dataset_version.id", ondelete="CASCADE"), nullable=False
    )
    river_id: Mapped[int] = mapped_column()
    segment_code: Mapped[str] = mapped_column(String(64), nullable=False)
    upstream_node_id: Mapped[int] = mapped_column(nullable=False)
    downstream_node_id: Mapped[int] = mapped_column(nullable=False)
    length: Mapped[float] = mapped_column(Float, nullable=False)
    geometry: Mapped[Any] = mapped_column(
        Geometry(geometry_type="LINESTRING", srid=4490, spatial_index=False), nullable=False
    )

    river: Mapped[River] = relationship(back_populates="segments")


class RiverConnection(Base):
    """以有向边表达节点之间的河网连接关系。"""

    __tablename__ = "river_connection"
    __table_args__ = (
        ForeignKeyConstraint(
            ["from_node_id", "dataset_version_id"],
            ["river_node.id", "river_node.dataset_version_id"],
            name="fk_river_connection_from_version",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["to_node_id", "dataset_version_id"],
            ["river_node.id", "river_node.dataset_version_id"],
            name="fk_river_connection_to_version",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["river_id", "dataset_version_id"],
            ["river.id", "river.dataset_version_id"],
            name="fk_river_connection_river_version",
            ondelete="CASCADE",
        ),
        UniqueConstraint(
            "dataset_version_id",
            "from_node_id",
            "to_node_id",
            "river_id",
            name="uq_river_connection_edge",
        ),
        Index("ix_river_connection_river_id", "river_id"),
        Index("ix_river_connection_from_node_id", "from_node_id"),
        Index("ix_river_connection_to_node_id", "to_node_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    dataset_version_id: Mapped[int] = mapped_column(
        ForeignKey("dataset_version.id", ondelete="CASCADE"), nullable=False
    )
    from_node_id: Mapped[int] = mapped_column(nullable=False)
    to_node_id: Mapped[int] = mapped_column(nullable=False)
    river_id: Mapped[int] = mapped_column()

    river: Mapped[River] = relationship(back_populates="connections")


class CrossSection(Base):
    """河道横断面，保存桩号、有序横向高程点和空间定位点。"""

    __tablename__ = "cross_section"
    __table_args__ = (
        CheckConstraint("station >= 0", name="ck_cross_section_station_nonnegative"),
        CheckConstraint("roughness > 0", name="ck_cross_section_roughness_positive"),
        ForeignKeyConstraint(
            ["river_id", "dataset_version_id"],
            ["river.id", "river.dataset_version_id"],
            name="fk_cross_section_river_version",
            ondelete="CASCADE",
        ),
        UniqueConstraint("id", "dataset_version_id", name="uq_cross_section_id_version"),
        UniqueConstraint(
            "dataset_version_id", "section_code", name="uq_cross_section_version_code"
        ),
        UniqueConstraint(
            "dataset_version_id",
            "river_id",
            "station",
            name="uq_cross_section_version_river_station",
        ),
        Index("ix_cross_section_geometry_gist", "geometry", postgresql_using="gist"),
        Index("ix_cross_section_river_id", "river_id"),
        Index("ix_cross_section_dataset_version_id", "dataset_version_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    dataset_version_id: Mapped[int] = mapped_column(
        ForeignKey("dataset_version.id", ondelete="CASCADE"), nullable=False
    )
    river_id: Mapped[int] = mapped_column()
    section_code: Mapped[str] = mapped_column(String(64), nullable=False)
    section_name: Mapped[str] = mapped_column(String(128), nullable=False)
    station: Mapped[float] = mapped_column(Float, nullable=False)
    points: Mapped[dict[str, list[list[float]]]] = mapped_column(JSON, nullable=False)
    roughness: Mapped[float] = mapped_column(Float, nullable=False)
    elevation_min: Mapped[float] = mapped_column(Float, nullable=False)
    survey_date: Mapped[date | None] = mapped_column(Date)
    geometry: Mapped[Any] = mapped_column(
        Geometry(geometry_type="POINT", srid=4490, spatial_index=False), nullable=False
    )
    created_time: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    river: Mapped[River] = relationship(back_populates="cross_sections")


class CrossSectionLocation(Base):
    """Additive surveyed location for a legacy cross-section point contract."""

    __tablename__ = "cross_section_location"
    __table_args__ = (
        UniqueConstraint("cross_section_id", name="uq_cross_section_location_section"),
        ForeignKeyConstraint(["cross_section_id", "dataset_version_id"], ["cross_section.id", "cross_section.dataset_version_id"], name="fk_cross_section_location_section_version", ondelete="CASCADE"),
        Index("ix_cross_section_location_geometry_gist", "geometry", postgresql_using="gist"),
        Index("ix_cross_section_location_version", "dataset_version_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    cross_section_id: Mapped[int] = mapped_column(nullable=False)
    dataset_version_id: Mapped[int] = mapped_column(nullable=False)
    geometry: Mapped[Any] = mapped_column(Geometry(geometry_type="POINT", srid=4490, spatial_index=False), nullable=False)
    survey_method: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class CrossSectionAxis(Base):
    """Optional mapped axis and bank positions; legacy geometry remains Point."""

    __tablename__ = "cross_section_axis"
    __table_args__ = (
        UniqueConstraint("cross_section_id", name="uq_cross_section_axis_section"),
        ForeignKeyConstraint(["cross_section_id", "dataset_version_id"], ["cross_section.id", "cross_section.dataset_version_id"], name="fk_cross_section_axis_section_version", ondelete="CASCADE"),
        Index("ix_cross_section_axis_geometry_gist", "geometry", postgresql_using="gist"),
        Index("ix_cross_section_axis_version", "dataset_version_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    cross_section_id: Mapped[int] = mapped_column(nullable=False)
    dataset_version_id: Mapped[int] = mapped_column(nullable=False)
    geometry: Mapped[Any] = mapped_column(Geometry(geometry_type="LINESTRING", srid=4490, spatial_index=False), nullable=False)
    left_bank: Mapped[Any | None] = mapped_column(Geometry(geometry_type="POINT", srid=4490, spatial_index=False))
    right_bank: Mapped[Any | None] = mapped_column(Geometry(geometry_type="POINT", srid=4490, spatial_index=False))
    vertical_datum: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class CrossSectionPoint(Base):
    """Optional normalized profile point preserving business-significant order."""

    __tablename__ = "cross_section_point"
    __table_args__ = (
        CheckConstraint("point_order >= 0", name="ck_cross_section_point_order"),
        UniqueConstraint("cross_section_id", "point_order", name="uq_cross_section_point_order"),
        ForeignKeyConstraint(["cross_section_id", "dataset_version_id"], ["cross_section.id", "cross_section.dataset_version_id"], name="fk_cross_section_point_section_version", ondelete="CASCADE"),
        Index("ix_cross_section_point_geometry_gist", "geometry", postgresql_using="gist"),
        Index("ix_cross_section_point_version", "dataset_version_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    cross_section_id: Mapped[int] = mapped_column(nullable=False)
    dataset_version_id: Mapped[int] = mapped_column(nullable=False)
    point_order: Mapped[int] = mapped_column(Integer, nullable=False)
    offset: Mapped[float] = mapped_column(Float, nullable=False)
    elevation: Mapped[float] = mapped_column(Float, nullable=False)
    geometry: Mapped[Any | None] = mapped_column(Geometry(geometry_type="POINT", srid=4490, spatial_index=False))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class CrossSectionProfile(Base):
    """Optional versioned profile metadata for GIS consumers and future adapters."""

    __tablename__ = "cross_section_profile"
    __table_args__ = (
        UniqueConstraint("cross_section_id", name="uq_cross_section_profile_section"),
        ForeignKeyConstraint(["cross_section_id", "dataset_version_id"], ["cross_section.id", "cross_section.dataset_version_id"], name="fk_cross_section_profile_section_version", ondelete="CASCADE"),
        Index("ix_cross_section_profile_version", "dataset_version_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    cross_section_id: Mapped[int] = mapped_column(nullable=False)
    dataset_version_id: Mapped[int] = mapped_column(nullable=False)
    profile: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    vertical_datum: Mapped[str | None] = mapped_column(String(64))
    source_revision: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class Gate(Base):
    """闸门静态设计参数和空间定位，不承载调度执行状态。"""

    __tablename__ = "gate"
    __table_args__ = (
        CheckConstraint("width > 0", name="ck_gate_width_positive"),
        CheckConstraint("height > 0", name="ck_gate_height_positive"),
        CheckConstraint("max_flow >= 0", name="ck_gate_max_flow_nonnegative"),
        CheckConstraint(
            "status IN ('online', 'offline', 'maintenance', 'fault')",
            name="ck_gate_status",
        ),
        UniqueConstraint("dataset_version_id", "gate_code", name="uq_gate_version_code"),
        ForeignKeyConstraint(
            ["hydraulic_upstream_section_id", "dataset_version_id"],
            ["hydraulic.cross_section.id", "hydraulic.cross_section.dataset_version_id"],
            name="fk_gate_d2_upstream_section_version",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["hydraulic_downstream_section_id", "dataset_version_id"],
            ["hydraulic.cross_section.id", "hydraulic.cross_section.dataset_version_id"],
            name="fk_gate_d2_downstream_section_version",
            ondelete="RESTRICT",
        ),
        Index("ix_gate_geometry_gist", "geometry", postgresql_using="gist"),
        Index("ix_gate_river_id", "river_id"),
        Index("ix_gate_dataset_version_id", "dataset_version_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    dataset_version_id: Mapped[int] = mapped_column(
        ForeignKey("dataset_version.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    gate_code: Mapped[str] = mapped_column(String(64), nullable=False)
    river_id: Mapped[int] = mapped_column(ForeignKey("river.id", ondelete="RESTRICT"))
    gate_type: Mapped[str] = mapped_column(String(32), nullable=False)
    opening_direction: Mapped[str] = mapped_column(String(32), nullable=False)
    control_mode: Mapped[str] = mapped_column(String(32), nullable=False)
    width: Mapped[float] = mapped_column(Float, nullable=False)
    height: Mapped[float] = mapped_column(Float, nullable=False)
    max_flow: Mapped[float] = mapped_column(Float, nullable=False)
    bottom_elevation: Mapped[float] = mapped_column(Float, nullable=False)
    river_segment_id: Mapped[int | None] = mapped_column(
        ForeignKey("river_segment.id", ondelete="SET NULL")
    )
    station: Mapped[float | None] = mapped_column(Float)
    hydraulic_upstream_section_id: Mapped[int | None] = mapped_column(Integer)
    hydraulic_downstream_section_id: Mapped[int | None] = mapped_column(Integer)
    upstream_node_id: Mapped[int | None] = mapped_column(
        ForeignKey("river_node.id", ondelete="SET NULL")
    )
    downstream_node_id: Mapped[int | None] = mapped_column(
        ForeignKey("river_node.id", ondelete="SET NULL")
    )
    crest_elevation: Mapped[float | None] = mapped_column(Float)
    discharge_coefficient: Mapped[float | None] = mapped_column(Float)
    minimum_opening: Mapped[float | None] = mapped_column(Float)
    maximum_opening: Mapped[float | None] = mapped_column(Float)
    opening_rate_limit: Mapped[float | None] = mapped_column(Float)
    minimum_hold_seconds: Mapped[float | None] = mapped_column(Float)
    allow_reverse_flow: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="false"
    )
    status: Mapped[str] = mapped_column(String(24), nullable=False, server_default="offline")
    geometry: Mapped[Any] = mapped_column(
        Geometry(geometry_type="POINT", srid=4490, spatial_index=False), nullable=False
    )
    created_time: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    river: Mapped[River] = relationship(back_populates="gates")


class Pump(Base):
    """泵站设计流量、扬程、功率、效率曲线和空间定位。"""

    __tablename__ = "pump"
    __table_args__ = (
        CheckConstraint("design_flow >= 0", name="ck_pump_design_flow_nonnegative"),
        CheckConstraint("head >= 0", name="ck_pump_head_nonnegative"),
        CheckConstraint("power >= 0", name="ck_pump_power_nonnegative"),
        CheckConstraint(
            "status IN ('online', 'offline', 'maintenance', 'fault')",
            name="ck_pump_status",
        ),
        UniqueConstraint("dataset_version_id", "pump_code", name="uq_pump_version_code"),
        ForeignKeyConstraint(
            ["hydraulic_section_id", "dataset_version_id"],
            ["hydraulic.cross_section.id", "hydraulic.cross_section.dataset_version_id"],
            name="fk_pump_d2_section_version",
            ondelete="RESTRICT",
        ),
        Index("ix_pump_geometry_gist", "geometry", postgresql_using="gist"),
        Index("ix_pump_river_id", "river_id"),
        Index("ix_pump_dataset_version_id", "dataset_version_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    dataset_version_id: Mapped[int] = mapped_column(
        ForeignKey("dataset_version.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    pump_code: Mapped[str] = mapped_column(String(64), nullable=False)
    river_id: Mapped[int] = mapped_column(ForeignKey("river.id", ondelete="RESTRICT"))
    design_flow: Mapped[float] = mapped_column(Float, nullable=False)
    head: Mapped[float] = mapped_column(Float, nullable=False)
    power: Mapped[float] = mapped_column(Float, nullable=False)
    efficiency_curve: Mapped[dict[str, list[list[float]]]] = mapped_column(JSON, nullable=False)
    head_curve: Mapped[dict[str, list[list[float]]] | None] = mapped_column(JSON)
    hydraulic_section_id: Mapped[int | None] = mapped_column(Integer)
    curve_policy_id: Mapped[str | None] = mapped_column(String(64))
    curve_unit: Mapped[str | None] = mapped_column(String(32))
    curve_source_revision: Mapped[str | None] = mapped_column(String(64))
    curve_hash: Mapped[str | None] = mapped_column(String(64))
    system_loss: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    outlet_stage: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    intake_node_id: Mapped[int | None] = mapped_column(
        ForeignKey("river_node.id", ondelete="SET NULL")
    )
    outlet_node_id: Mapped[int | None] = mapped_column(
        ForeignKey("river_node.id", ondelete="SET NULL")
    )
    transfer_type: Mapped[str | None] = mapped_column(String(24))
    unit_count: Mapped[int | None] = mapped_column(Integer)
    minimum_running_units: Mapped[int | None] = mapped_column(Integer)
    maximum_running_units: Mapped[int | None] = mapped_column(Integer)
    minimum_run_seconds: Mapped[float | None] = mapped_column(Float)
    minimum_stop_seconds: Mapped[float | None] = mapped_column(Float)
    maximum_starts_per_run: Mapped[int | None] = mapped_column(Integer)
    minimum_operating_head: Mapped[float | None] = mapped_column(Float)
    maximum_operating_head: Mapped[float | None] = mapped_column(Float)
    reverse_flow_protection: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="true"
    )
    control_mode: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False, server_default="offline")
    geometry: Mapped[Any] = mapped_column(
        Geometry(geometry_type="POINT", srid=4490, spatial_index=False), nullable=False
    )
    created_time: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    river: Mapped[River] = relationship(back_populates="pumps")


class MapAnnotation(Base):
    """Store one versioned professional map label without mixing runtime state into GIS data."""

    __tablename__ = "map_annotation"
    __table_args__ = (
        CheckConstraint("longitude BETWEEN -180 AND 180", name="ck_map_annotation_longitude"),
        CheckConstraint("latitude BETWEEN -90 AND 90", name="ck_map_annotation_latitude"),
        CheckConstraint("rotation >= 0 AND rotation < 360", name="ck_map_annotation_rotation"),
        CheckConstraint("font_size BETWEEN 8 AND 72", name="ck_map_annotation_font_size"),
        CheckConstraint(
            "ST_Equals(geometry, ST_SetSRID(ST_MakePoint(longitude, latitude), 4490))",
            name="ck_map_annotation_coordinate_geometry",
        ),
        CheckConstraint(
            "visible_scale_min >= 0 AND visible_scale_max >= visible_scale_min",
            name="ck_map_annotation_visible_scale",
        ),
        CheckConstraint(
            "annotation_type IN ('river', 'gate', 'pump', 'cross_section', "
            "'hydrology_station', 'dispatch_event', 'parameter', 'place')",
            name="ck_map_annotation_type",
        ),
        CheckConstraint(
            "related_type IS NULL OR related_type IN "
            "('river', 'gate', 'pump', 'cross_section', 'hydrology_station', 'dispatch_event')",
            name="ck_map_annotation_related_type",
        ),
        UniqueConstraint(
            "dataset_version_id", "annotation_type", "name", "related_type", "related_id",
            name="uq_map_annotation_version_related_name",
        ),
        Index("ix_map_annotation_geometry_gist", "geometry", postgresql_using="gist"),
        Index("ix_map_annotation_dataset_type", "dataset_version_id", "annotation_type"),
        Index("ix_map_annotation_related", "related_type", "related_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    dataset_version_id: Mapped[int] = mapped_column(
        ForeignKey("dataset_version.id", ondelete="CASCADE"), nullable=False
    )
    annotation_type: Mapped[str] = mapped_column(String(32), nullable=False)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    text: Mapped[str] = mapped_column(String(256), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    longitude: Mapped[float] = mapped_column(Float, nullable=False)
    latitude: Mapped[float] = mapped_column(Float, nullable=False)
    rotation: Mapped[float] = mapped_column(Float, nullable=False, server_default="0")
    font_size: Mapped[int] = mapped_column(Integer, nullable=False, server_default="14")
    color: Mapped[str] = mapped_column(String(16), nullable=False, server_default="#E8F7FF")
    visible_scale_min: Mapped[float] = mapped_column(Float, nullable=False, server_default="0")
    visible_scale_max: Mapped[float] = mapped_column(
        Float, nullable=False, server_default="500000"
    )
    related_type: Mapped[str | None] = mapped_column(String(32))
    related_id: Mapped[int | None] = mapped_column(Integer)
    geometry: Mapped[Any] = mapped_column(
        Geometry(geometry_type="POINT", srid=4490, spatial_index=False), nullable=False
    )
    created_time: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    dataset_version: Mapped[DatasetVersion] = relationship(back_populates="annotations")


class AdministrativeArea(Base):
    """Store one searchable administrative boundary in the authoritative data version."""

    __tablename__ = "administrative_area"
    __table_args__ = (
        UniqueConstraint("dataset_version_id", "code", name="uq_administrative_area_version_code"),
        Index("ix_administrative_area_geometry_gist", "geometry", postgresql_using="gist"),
        Index("ix_administrative_area_version_name", "dataset_version_id", "name"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    dataset_version_id: Mapped[int] = mapped_column(
        ForeignKey("dataset_version.id", ondelete="CASCADE"), nullable=False
    )
    code: Mapped[str] = mapped_column(String(64), nullable=False)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    administrative_level: Mapped[str] = mapped_column(String(32), nullable=False)
    address: Mapped[str | None] = mapped_column(String(256))
    geometry: Mapped[Any] = mapped_column(
        Geometry(geometry_type="POLYGON", srid=4490, spatial_index=False), nullable=False
    )


class Road(Base):
    """Store one versioned road centerline used by WMS, WMTS, and local search."""

    __tablename__ = "road"
    __table_args__ = (
        UniqueConstraint("dataset_version_id", "code", name="uq_road_version_code"),
        Index("ix_road_geometry_gist", "geometry", postgresql_using="gist"),
        Index("ix_road_version_name", "dataset_version_id", "name"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    dataset_version_id: Mapped[int] = mapped_column(
        ForeignKey("dataset_version.id", ondelete="CASCADE"), nullable=False
    )
    code: Mapped[str] = mapped_column(String(64), nullable=False)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    road_type: Mapped[str] = mapped_column(String(32), nullable=False)
    address: Mapped[str | None] = mapped_column(String(256))
    geometry: Mapped[Any] = mapped_column(
        Geometry(geometry_type="LINESTRING", srid=4490, spatial_index=False), nullable=False
    )


class PlaceName(Base):
    """Store a scale-styled settlement or district label with a stable search point."""

    __tablename__ = "place_name"
    __table_args__ = (
        UniqueConstraint("dataset_version_id", "code", name="uq_place_name_version_code"),
        Index("ix_place_name_geometry_gist", "geometry", postgresql_using="gist"),
        Index("ix_place_name_version_name", "dataset_version_id", "name"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    dataset_version_id: Mapped[int] = mapped_column(
        ForeignKey("dataset_version.id", ondelete="CASCADE"), nullable=False
    )
    code: Mapped[str] = mapped_column(String(64), nullable=False)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    place_type: Mapped[str] = mapped_column(String(32), nullable=False)
    address: Mapped[str | None] = mapped_column(String(256))
    importance: Mapped[int] = mapped_column(Integer, nullable=False, server_default="50")
    geometry: Mapped[Any] = mapped_column(
        Geometry(geometry_type="POINT", srid=4490, spatial_index=False), nullable=False
    )


class WaterName(Base):
    """Store a searchable cartographic water-body name independently from hydraulic assets."""

    __tablename__ = "water_name"
    __table_args__ = (
        UniqueConstraint("dataset_version_id", "code", name="uq_water_name_version_code"),
        Index("ix_water_name_geometry_gist", "geometry", postgresql_using="gist"),
        Index("ix_water_name_version_name", "dataset_version_id", "name"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    dataset_version_id: Mapped[int] = mapped_column(
        ForeignKey("dataset_version.id", ondelete="CASCADE"), nullable=False
    )
    code: Mapped[str] = mapped_column(String(64), nullable=False)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    water_type: Mapped[str] = mapped_column(String(32), nullable=False)
    address: Mapped[str | None] = mapped_column(String(256))
    geometry: Mapped[Any] = mapped_column(
        Geometry(geometry_type="POINT", srid=4490, spatial_index=False), nullable=False
    )


class PointOfInterest(Base):
    """Store a versioned local POI for deterministic offline engineering-map search."""

    __tablename__ = "poi"
    __table_args__ = (
        UniqueConstraint("dataset_version_id", "code", name="uq_poi_version_code"),
        Index("ix_poi_geometry_gist", "geometry", postgresql_using="gist"),
        Index("ix_poi_version_name", "dataset_version_id", "name"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    dataset_version_id: Mapped[int] = mapped_column(
        ForeignKey("dataset_version.id", ondelete="CASCADE"), nullable=False
    )
    code: Mapped[str] = mapped_column(String(64), nullable=False)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    category: Mapped[str] = mapped_column(String(64), nullable=False)
    address: Mapped[str | None] = mapped_column(String(256))
    geometry: Mapped[Any] = mapped_column(
        Geometry(geometry_type="POINT", srid=4490, spatial_index=False), nullable=False
    )


class ModelParameter(Base):
    """保存可按数据版本追溯的 Phase 3 模型参数。"""

    __tablename__ = "model_parameter"
    __table_args__ = (
        UniqueConstraint(
            "dataset_version_id",
            "parameter_type",
            "parameter_name",
            name="uq_model_parameter_version_name",
        ),
        Index("ix_model_parameter_dataset_version_id", "dataset_version_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    dataset_version_id: Mapped[int] = mapped_column(
        ForeignKey("dataset_version.id", ondelete="CASCADE"), nullable=False
    )
    parameter_type: Mapped[str] = mapped_column(String(64), nullable=False)
    parameter_name: Mapped[str] = mapped_column(String(128), nullable=False)
    value: Mapped[float] = mapped_column(Float, nullable=False)
    unit: Mapped[str] = mapped_column(String(32), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)

    dataset_version: Mapped[DatasetVersion] = relationship(back_populates="parameters")


class BoundaryCondition(Base):
    """保存上游流量、下游水位等边界时间序列或定值。"""

    __tablename__ = "boundary_condition"
    __table_args__ = (
        UniqueConstraint(
            "dataset_version_id", "name", name="uq_boundary_condition_version_name"
        ),
        ForeignKeyConstraint(
            ["hydraulic_node_id", "dataset_version_id"],
            ["hydraulic.node.id", "hydraulic.node.dataset_version_id"],
            name="fk_boundary_d2_hydraulic_node_version",
            ondelete="RESTRICT",
        ),
        Index("ix_boundary_condition_dataset_version_id", "dataset_version_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    dataset_version_id: Mapped[int] = mapped_column(
        ForeignKey("dataset_version.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    boundary_type: Mapped[str] = mapped_column(String(64), nullable=False)
    target_node_id: Mapped[int | None] = mapped_column(
        ForeignKey("river_node.id", ondelete="SET NULL")
    )
    hydraulic_node_id: Mapped[int | None] = mapped_column(Integer)
    values: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    unit: Mapped[str] = mapped_column(String(32), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)

    dataset_version: Mapped[DatasetVersion] = relationship(back_populates="boundary_conditions")


class SimulationCase(Base):
    """引用版本化河网和边界条件，定义可交给 Phase 3 的计算方案。"""

    __tablename__ = "simulation_case"
    __table_args__ = (
        UniqueConstraint("name", name="uq_simulation_case_name"),
        Index("ix_simulation_case_dataset_version_id", "dataset_version_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    dataset_version_id: Mapped[int] = mapped_column(
        ForeignKey("dataset_version.id", ondelete="RESTRICT"), nullable=False
    )
    boundary_condition_id: Mapped[int] = mapped_column(
        ForeignKey("boundary_condition.id", ondelete="RESTRICT"), nullable=False
    )
    v4_configuration: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    created_time: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    dataset_version: Mapped[DatasetVersion] = relationship(back_populates="simulation_cases")
    tasks: Mapped[list["SimulationTask"]] = relationship(back_populates="simulation_case")
    boundary_links: Mapped[list["SimulationCaseBoundary"]] = relationship(
        back_populates="simulation_case", cascade="all, delete-orphan"
    )


class SimulationCaseBoundary(Base):
    """明确关联一个计算方案使用的边界条件及其角色。"""

    __tablename__ = "simulation_case_boundary"
    __table_args__ = (
        UniqueConstraint(
            "case_id", "boundary_condition_id", name="uq_case_boundary_link"
        ),
        Index("ix_simulation_case_boundary_case_id", "case_id"),
    )

    case_id: Mapped[int] = mapped_column(
        ForeignKey("simulation_case.id", ondelete="CASCADE"), primary_key=True
    )
    boundary_condition_id: Mapped[int] = mapped_column(
        ForeignKey("boundary_condition.id", ondelete="RESTRICT"), primary_key=True
    )
    role: Mapped[str] = mapped_column(String(32), nullable=False)
    created_time: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    simulation_case: Mapped[SimulationCase] = relationship(back_populates="boundary_links")


class SimulationTaskGroup(Base):
    """Group independent tasks for a diagnostic v3/v4 shadow comparison."""

    __tablename__ = "simulation_task_group"
    __table_args__ = (
        CheckConstraint("group_type IN ('shadow')", name="ck_simulation_task_group_type"),
        Index("ix_simulation_task_group_case_id", "case_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    case_id: Mapped[int] = mapped_column(
        ForeignKey("simulation_case.id", ondelete="RESTRICT"), nullable=False
    )
    group_type: Mapped[str] = mapped_column(String(16), nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False, server_default="pending")
    created_time: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class SimulationTask(Base):
    """Persist one reproducible hydraulic execution and its lifecycle state."""

    __tablename__ = "simulation_task"
    __table_args__ = (
        CheckConstraint(
            "status IN ('pending', 'queued', 'running', 'cancel_requested', "
            "'cancelled', 'success', 'failed')",
            name="ck_simulation_task_status",
        ),
        CheckConstraint(
            "progress BETWEEN 0 AND 100", name="ck_simulation_task_progress"
        ),
        CheckConstraint(
            "execution_mode IS NULL OR execution_mode IN ('validation','shadow')",
            name="ck_simulation_task_execution_mode",
        ),
        CheckConstraint(
            "group_role IS NULL OR group_role IN ('legacy-v3','native-v4')",
            name="ck_simulation_task_group_role",
        ),
        CheckConstraint(
            "artifact_status IS NULL OR artifact_status IN "
            "('none','preparing','prepared','published','failed')",
            name="ck_simulation_task_artifact_status",
        ),
        Index("ix_simulation_task_case_id", "case_id"),
        Index("ix_simulation_task_status", "status"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    case_id: Mapped[int] = mapped_column(
        ForeignKey("simulation_case.id", ondelete="RESTRICT"), nullable=False
    )
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, server_default="pending"
    )
    progress: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    config: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    input_schema_version: Mapped[str | None] = mapped_column(String(48))
    input_snapshot: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    input_snapshot_hash: Mapped[str | None] = mapped_column(String(64))
    engine_version: Mapped[str | None] = mapped_column(String(64))
    engine_commit: Mapped[str | None] = mapped_column(String(64))
    solver_id: Mapped[str | None] = mapped_column(String(96))
    capability_id: Mapped[str | None] = mapped_column(String(96))
    runtime_adapter_id: Mapped[str | None] = mapped_column(String(96))
    result_schema_version: Mapped[str | None] = mapped_column(String(48))
    execution_mode: Mapped[str | None] = mapped_column(String(16))
    execution_phase: Mapped[str | None] = mapped_column(String(32))
    runtime_projection_hash: Mapped[str | None] = mapped_column(String(64))
    mesh_hash: Mapped[str | None] = mapped_column(String(64))
    solver_policy_hash: Mapped[str | None] = mapped_column(String(64))
    validation_policy_hash: Mapped[str | None] = mapped_column(String(64))
    registry_hash: Mapped[str | None] = mapped_column(String(64))
    artifact_status: Mapped[str | None] = mapped_column(String(16))
    comparison_group_id: Mapped[int | None] = mapped_column(
        ForeignKey("simulation_task_group.id", ondelete="SET NULL")
    )
    group_role: Mapped[str | None] = mapped_column(String(16))
    queue_job_id: Mapped[str | None] = mapped_column(String(128))
    worker_id: Mapped[str | None] = mapped_column(String(128))
    queued_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    heartbeat_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cancel_requested: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="false"
    )
    retry_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    accepted_step_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    cfl_reduction_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    positivity_retry_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    event_refinement_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    gate_solver_retry_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    pump_solver_retry_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    minimum_dt_failure_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    retry_reason: Mapped[str | None] = mapped_column(Text)
    current_simulation_time: Mapped[float | None] = mapped_column(Float)
    current_cfl: Mapped[float | None] = mapped_column(Float)
    diagnostics: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    last_event: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    result_path: Mapped[str | None] = mapped_column(Text)
    error_message: Mapped[str | None] = mapped_column(Text)
    created_time: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    start_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    end_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    simulation_case: Mapped[SimulationCase] = relationship(back_populates="tasks")
    results: Mapped[list["SimulationResult"]] = relationship(
        back_populates="task", cascade="all, delete-orphan"
    )


class HydraulicTaskSectionResult(Base):
    """Persist authoritative v4 Section output without public compatibility IDs."""

    __tablename__ = "hydraulic_task_section_result"
    __table_args__ = (
        ForeignKeyConstraint(
            ["hydraulic_cross_section_id", "dataset_version_id"],
            ["hydraulic.cross_section.id", "hydraulic.cross_section.dataset_version_id"],
            name="fk_d2_section_result_section_version",
            ondelete="RESTRICT",
        ),
        UniqueConstraint(
            "task_id", "hydraulic_cross_section_id", "time_seconds",
            name="uq_d2_section_result_task_section_time",
        ),
        Index("ix_d2_section_result_task_time", "task_id", "time_seconds"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    task_id: Mapped[int] = mapped_column(
        ForeignKey("simulation_task.id", ondelete="CASCADE"), nullable=False
    )
    dataset_version_id: Mapped[int] = mapped_column(
        ForeignKey("dataset_version.id", ondelete="RESTRICT"), nullable=False
    )
    hydraulic_cross_section_id: Mapped[int] = mapped_column(Integer, nullable=False)
    section_code: Mapped[str] = mapped_column(String(64), nullable=False)
    branch_id: Mapped[int] = mapped_column(Integer, nullable=False)
    chainage_m: Mapped[float] = mapped_column(Float, nullable=False)
    time_seconds: Mapped[float] = mapped_column(Float, nullable=False)
    water_level_m: Mapped[float] = mapped_column(Float, nullable=False)
    flow_m3s: Mapped[float] = mapped_column(Float, nullable=False)
    velocity_m_s: Mapped[float] = mapped_column(Float, nullable=False)
    control_volume_m3: Mapped[float] = mapped_column(Float, nullable=False)


class HydraulicTaskGateResult(Base):
    """Persist D1 Gate series with authoritative asset and evidence fields."""

    __tablename__ = "hydraulic_task_gate_result"
    __table_args__ = (
        UniqueConstraint(
            "task_id", "canonical_gate_id", "time_seconds",
            name="uq_d2_gate_result_task_gate_time",
        ),
        Index("ix_d2_gate_result_task_time", "task_id", "time_seconds"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    task_id: Mapped[int] = mapped_column(
        ForeignKey("simulation_task.id", ondelete="CASCADE"), nullable=False
    )
    dataset_version_id: Mapped[int] = mapped_column(
        ForeignKey("dataset_version.id", ondelete="RESTRICT"), nullable=False
    )
    canonical_gate_id: Mapped[int] = mapped_column(
        ForeignKey("gate.id", ondelete="RESTRICT"), nullable=False
    )
    time_seconds: Mapped[float] = mapped_column(Float, nullable=False)
    opening_m: Mapped[float] = mapped_column(Float, nullable=False)
    flow_m3s: Mapped[float] = mapped_column(Float, nullable=False)
    upstream_stage_m: Mapped[float] = mapped_column(Float, nullable=False)
    downstream_stage_m: Mapped[float] = mapped_column(Float, nullable=False)
    head_loss_m: Mapped[float | None] = mapped_column(Float)
    reaction_force_per_density: Mapped[float | None] = mapped_column(Float)
    regime: Mapped[str | None] = mapped_column(String(48))


class HydraulicTaskPumpResult(Base):
    """Persist D1 hydraulic Pump operating-point and energy series."""

    __tablename__ = "hydraulic_task_pump_result"
    __table_args__ = (
        UniqueConstraint(
            "task_id", "canonical_pump_id", "time_seconds",
            name="uq_d2_pump_result_task_pump_time",
        ),
        Index("ix_d2_pump_result_task_time", "task_id", "time_seconds"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    task_id: Mapped[int] = mapped_column(
        ForeignKey("simulation_task.id", ondelete="CASCADE"), nullable=False
    )
    dataset_version_id: Mapped[int] = mapped_column(
        ForeignKey("dataset_version.id", ondelete="RESTRICT"), nullable=False
    )
    canonical_pump_id: Mapped[int] = mapped_column(
        ForeignKey("pump.id", ondelete="RESTRICT"), nullable=False
    )
    time_seconds: Mapped[float] = mapped_column(Float, nullable=False)
    control_state: Mapped[str] = mapped_column(String(16), nullable=False)
    running_units: Mapped[int] = mapped_column(Integer, nullable=False)
    flow_m3s: Mapped[float] = mapped_column(Float, nullable=False)
    source_stage_m: Mapped[float] = mapped_column(Float, nullable=False)
    outlet_stage_m: Mapped[float] = mapped_column(Float, nullable=False)
    pump_head_m: Mapped[float] = mapped_column(Float, nullable=False)
    system_head_m: Mapped[float] = mapped_column(Float, nullable=False)
    efficiency: Mapped[float] = mapped_column(Float, nullable=False)
    input_power_kw: Mapped[float] = mapped_column(Float, nullable=False)
    cumulative_energy_kwh: Mapped[float] = mapped_column(Float, nullable=False)
    iterations: Mapped[int] = mapped_column(Integer, nullable=False)
    regime: Mapped[str | None] = mapped_column(String(48))


class HydraulicTaskControlEvent(Base):
    """Persist accepted v4 control events without a legacy DispatchRun dependency."""

    __tablename__ = "hydraulic_task_control_event"
    __table_args__ = (
        UniqueConstraint(
            "task_id", "time_seconds", "structure_type", "canonical_structure_id", "event_type",
            name="uq_d2_control_event_identity",
        ),
        Index("ix_d2_control_event_task_time", "task_id", "time_seconds"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    task_id: Mapped[int] = mapped_column(
        ForeignKey("simulation_task.id", ondelete="CASCADE"), nullable=False
    )
    time_seconds: Mapped[float] = mapped_column(Float, nullable=False)
    structure_type: Mapped[str] = mapped_column(String(16), nullable=False)
    canonical_structure_id: Mapped[int] = mapped_column(Integer, nullable=False)
    event_type: Mapped[str] = mapped_column(String(32), nullable=False)
    reason: Mapped[str | None] = mapped_column(Text)
    pre_state_json: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    post_command_json: Mapped[dict[str, Any] | None] = mapped_column(JSON)


class HydraulicTaskArtifact(Base):
    """Register deterministic evidence files before controlled publication/download."""

    __tablename__ = "hydraulic_task_artifact"
    __table_args__ = (
        CheckConstraint(
            "status IN ('prepared','published','failed')",
            name="ck_d2_artifact_status",
        ),
        CheckConstraint("length(sha256) = 64", name="ck_d2_artifact_sha256"),
        CheckConstraint("size_bytes >= 0", name="ck_d2_artifact_size"),
        CheckConstraint("record_count >= 0", name="ck_d2_artifact_record_count"),
        UniqueConstraint(
            "task_id", "artifact_type", "schema_version",
            name="uq_d2_artifact_task_type_schema",
        ),
        Index("ix_d2_artifact_task_status", "task_id", "status"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    task_id: Mapped[int] = mapped_column(
        ForeignKey("simulation_task.id", ondelete="CASCADE"), nullable=False
    )
    artifact_type: Mapped[str] = mapped_column(String(48), nullable=False)
    storage_key: Mapped[str] = mapped_column(Text, nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    record_count: Mapped[int] = mapped_column(Integer, nullable=False)
    media_type: Mapped[str] = mapped_column(String(96), nullable=False)
    schema_version: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    created_time: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    published_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class SimulationResult(Base):
    """Persist one section/time row from a successful hydraulic task."""

    __tablename__ = "simulation_result"
    __table_args__ = (
        UniqueConstraint(
            "task_id",
            "section_code",
            "time_seconds",
            name="uq_simulation_result_task_section_time",
        ),
        Index("ix_simulation_result_task_id", "task_id"),
        Index("ix_simulation_result_section_id", "section_id"),
        Index("ix_simulation_result_river_id", "river_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    task_id: Mapped[int] = mapped_column(
        ForeignKey("simulation_task.id", ondelete="CASCADE"), nullable=False
    )
    section_id: Mapped[int | None] = mapped_column(
        ForeignKey("cross_section.id", ondelete="SET NULL")
    )
    river_id: Mapped[int | None] = mapped_column(
        ForeignKey("river.id", ondelete="SET NULL")
    )
    section_code: Mapped[str] = mapped_column(String(64), nullable=False)
    station: Mapped[float] = mapped_column(Float, nullable=False)
    time_seconds: Mapped[float] = mapped_column(Float, nullable=False)
    water_level: Mapped[float] = mapped_column(Float, nullable=False)
    flow: Mapped[float] = mapped_column(Float, nullable=False)
    velocity: Mapped[float] = mapped_column(Float, nullable=False)

    task: Mapped[SimulationTask] = relationship(back_populates="results")


class DispatchPlan(Base):
    """保存可校验、冻结、克隆和归档的仿真调度计划版本。"""

    __tablename__ = "dispatch_plan"
    __table_args__ = (
        CheckConstraint(
            "status IN ('draft', 'validated', 'frozen', 'archived')",
            name="ck_dispatch_plan_status",
        ),
        UniqueConstraint("name", "version", name="uq_dispatch_plan_name_version"),
        Index("ix_dispatch_plan_dataset_version_id", "dataset_version_id"),
        Index("ix_dispatch_plan_status", "status"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    dataset_version_id: Mapped[int] = mapped_column(
        ForeignKey("dataset_version.id", ondelete="RESTRICT"), nullable=False
    )
    simulation_case_id: Mapped[int] = mapped_column(
        ForeignKey("simulation_case.id", ondelete="RESTRICT"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False, server_default="1")
    status: Mapped[str] = mapped_column(String(16), nullable=False, server_default="draft")
    description: Mapped[str | None] = mapped_column(Text)
    duration_seconds: Mapped[float] = mapped_column(Float, nullable=False)
    evaluation_config: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    storage_level: Mapped[str] = mapped_column(
        String(16), nullable=False, server_default="key_sections"
    )
    created_by: Mapped[str] = mapped_column(String(64), nullable=False)
    created_time: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_time: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
    frozen_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    frozen_snapshot: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    frozen_snapshot_hash: Mapped[str | None] = mapped_column(String(64))


class DispatchAction(Base):
    """保存指定时刻的闸门或泵站人工调度命令。"""

    __tablename__ = "dispatch_action"
    __table_args__ = (
        CheckConstraint("structure_type IN ('gate', 'pump')", name="ck_dispatch_action_type"),
        CheckConstraint(
            "(gate_id IS NOT NULL AND pump_id IS NULL) OR "
            "(gate_id IS NULL AND pump_id IS NOT NULL)",
            name="ck_dispatch_action_single_asset",
        ),
        UniqueConstraint(
            "plan_id", "time_seconds", "structure_type", "gate_id", "pump_id",
            name="uq_dispatch_action_asset_time",
        ),
        Index("ix_dispatch_action_plan_time", "plan_id", "time_seconds"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    plan_id: Mapped[int] = mapped_column(
        ForeignKey("dispatch_plan.id", ondelete="CASCADE"), nullable=False
    )
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    time_seconds: Mapped[float] = mapped_column(Float, nullable=False)
    structure_type: Mapped[str] = mapped_column(String(16), nullable=False)
    gate_id: Mapped[int | None] = mapped_column(ForeignKey("gate.id", ondelete="RESTRICT"))
    pump_id: Mapped[int | None] = mapped_column(ForeignKey("pump.id", ondelete="RESTRICT"))
    command_type: Mapped[str] = mapped_column(String(32), nullable=False)
    target_value: Mapped[float] = mapped_column(Float, nullable=False)
    interpolation: Mapped[str] = mapped_column(String(16), nullable=False, server_default="step")
    priority: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    note: Mapped[str | None] = mapped_column(Text)


class DispatchRule(Base):
    """保存白名单观测和操作符组成的受控阈值规则。"""

    __tablename__ = "dispatch_rule"
    __table_args__ = (Index("ix_dispatch_rule_plan_id", "plan_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    plan_id: Mapped[int] = mapped_column(
        ForeignKey("dispatch_plan.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")
    observation_type: Mapped[str] = mapped_column(String(32), nullable=False)
    observation_object_id: Mapped[int | None] = mapped_column(Integer)
    operator: Mapped[str] = mapped_column(String(4), nullable=False)
    threshold: Mapped[float] = mapped_column(Float, nullable=False)
    hysteresis: Mapped[float] = mapped_column(Float, nullable=False, server_default="0")
    minimum_hold_seconds: Mapped[float] = mapped_column(Float, nullable=False, server_default="0")
    cooldown_seconds: Mapped[float] = mapped_column(Float, nullable=False, server_default="0")
    action_template: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    priority: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")


class DispatchRun(Base):
    """关联基准与受控任务并保存一次调度仿真的指标和生命周期。"""

    __tablename__ = "dispatch_run"
    __table_args__ = (
        Index("ix_dispatch_run_plan_id", "plan_id"),
        Index("ix_dispatch_run_status", "status"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    plan_id: Mapped[int] = mapped_column(
        ForeignKey("dispatch_plan.id", ondelete="RESTRICT"), nullable=False
    )
    baseline_task_id: Mapped[int | None] = mapped_column(
        ForeignKey("simulation_task.id", ondelete="SET NULL")
    )
    controlled_task_id: Mapped[int | None] = mapped_column(
        ForeignKey("simulation_task.id", ondelete="SET NULL")
    )
    status: Mapped[str] = mapped_column(String(24), nullable=False, server_default="pending")
    progress: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    metrics: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    queue_job_id: Mapped[str | None] = mapped_column(String(128))
    error_message: Mapped[str | None] = mapped_column(Text)
    created_time: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    start_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    end_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class DispatchEvent(Base):
    """记录规则/人工命令的请求值、实际值、结果和原因。"""

    __tablename__ = "dispatch_event"
    __table_args__ = (Index("ix_dispatch_event_run_time", "run_id", "time_seconds"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("dispatch_run.id", ondelete="CASCADE"))
    time_seconds: Mapped[float] = mapped_column(Float, nullable=False)
    source_type: Mapped[str] = mapped_column(String(16), nullable=False)
    source_id: Mapped[int | None] = mapped_column(Integer)
    structure_type: Mapped[str] = mapped_column(String(16), nullable=False)
    structure_id: Mapped[int] = mapped_column(Integer, nullable=False)
    requested_command: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    applied_command: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    outcome: Mapped[str] = mapped_column(String(16), nullable=False)
    reason: Mapped[str | None] = mapped_column(Text)
    created_time: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class StructureResult(Base):
    """保存闸泵各时刻的请求/实际状态、流量、能耗和约束。"""

    __tablename__ = "structure_result"
    __table_args__ = (
        UniqueConstraint(
            "task_id", "time_seconds", "structure_type", "structure_id",
            name="uq_structure_result_task_time_asset",
        ),
        Index("ix_structure_result_run_time", "dispatch_run_id", "time_seconds"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    task_id: Mapped[int] = mapped_column(ForeignKey("simulation_task.id", ondelete="CASCADE"))
    dispatch_run_id: Mapped[int | None] = mapped_column(
        ForeignKey("dispatch_run.id", ondelete="CASCADE")
    )
    time_seconds: Mapped[float] = mapped_column(Float, nullable=False)
    structure_type: Mapped[str] = mapped_column(String(16), nullable=False)
    structure_id: Mapped[int] = mapped_column(Integer, nullable=False)
    requested_value: Mapped[float | None] = mapped_column(Float)
    actual_value: Mapped[float | None] = mapped_column(Float)
    flow: Mapped[float] = mapped_column(Float, nullable=False)
    upstream_level: Mapped[float | None] = mapped_column(Float)
    downstream_level: Mapped[float | None] = mapped_column(Float)
    head_difference: Mapped[float | None] = mapped_column(Float)
    transfer_type: Mapped[str | None] = mapped_column(String(24))
    power_kw: Mapped[float | None] = mapped_column(Float)
    energy_kwh: Mapped[float | None] = mapped_column(Float)
    regime: Mapped[str | None] = mapped_column(String(32))
    constraint_flags: Mapped[list[str]] = mapped_column(JSON, nullable=False)


class JunctionResult(Base):
    """保存河网共同水位、节点收支和连续性残差。"""

    __tablename__ = "junction_result"
    __table_args__ = (
        UniqueConstraint("task_id", "node_id", "time_seconds", name="uq_junction_task_node_time"),
        Index("ix_junction_result_task_time", "task_id", "time_seconds"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    task_id: Mapped[int] = mapped_column(ForeignKey("simulation_task.id", ondelete="CASCADE"))
    node_id: Mapped[int] = mapped_column(ForeignKey("river_node.id", ondelete="RESTRICT"))
    time_seconds: Mapped[float] = mapped_column(Float, nullable=False)
    water_level: Mapped[float] = mapped_column(Float, nullable=False)
    inflow: Mapped[float] = mapped_column(Float, nullable=False)
    outflow: Mapped[float] = mapped_column(Float, nullable=False)
    source_sink: Mapped[float] = mapped_column(Float, nullable=False)
    balance_residual: Mapped[float] = mapped_column(Float, nullable=False)


class OptimizationTask(Base):
    """Persist a versioned, reproducible multi-objective optimization lifecycle."""

    __tablename__ = "optimization_task"
    __table_args__ = (
        CheckConstraint(
            "status IN ('pending', 'running', 'success', 'failed', 'cancelled')",
            name="ck_optimization_task_status",
        ),
        CheckConstraint("progress BETWEEN 0 AND 100", name="ck_optimization_task_progress"),
        Index("ix_optimization_task_status", "status"),
        Index("ix_optimization_task_dataset_version_id", "dataset_version_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    algorithm: Mapped[str] = mapped_column(String(32), nullable=False, server_default="pso")
    status: Mapped[str] = mapped_column(String(16), nullable=False, server_default="pending")
    dataset_version_id: Mapped[int] = mapped_column(
        ForeignKey("dataset_version.id", ondelete="RESTRICT"), nullable=False
    )
    simulation_case_id: Mapped[int] = mapped_column(
        ForeignKey("simulation_case.id", ondelete="RESTRICT"), nullable=False
    )
    objective_config: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    algorithm_config: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    input_snapshot: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    input_snapshot_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    algorithm_version: Mapped[str] = mapped_column(String(64), nullable=False)
    progress: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    current_generation: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    best_score: Mapped[float | None] = mapped_column(Float)
    queue_job_id: Mapped[str | None] = mapped_column(String(128))
    worker_id: Mapped[str | None] = mapped_column(String(128))
    cancel_requested: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    converged: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    error_message: Mapped[str | None] = mapped_column(Text)
    created_time: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    start_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    end_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class OptimizationCandidate(Base):
    """Link one generated plan to its score, metrics and Phase 4 simulation task."""

    __tablename__ = "optimization_candidate"
    __table_args__ = (
        UniqueConstraint(
            "task_id", "generation", "candidate_index", name="uq_optimization_candidate_slot"
        ),
        Index("ix_optimization_candidate_task_id", "task_id"),
        Index("ix_optimization_candidate_simulation_task_id", "simulation_task_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    task_id: Mapped[int] = mapped_column(
        ForeignKey("optimization_task.id", ondelete="CASCADE"), nullable=False
    )
    generation: Mapped[int] = mapped_column(Integer, nullable=False)
    candidate_index: Mapped[int] = mapped_column(Integer, nullable=False)
    dispatch_plan: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    score: Mapped[float | None] = mapped_column(Float)
    objective_values: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    metrics: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    valid: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")
    constraint_reasons: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    simulation_task_id: Mapped[int | None] = mapped_column(
        ForeignKey("simulation_task.id", ondelete="SET NULL")
    )
    created_time: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class OptimizationResult(Base):
    """Persist Pareto level, rank and human-facing recommendation state."""

    __tablename__ = "optimization_result"
    __table_args__ = (
        CheckConstraint(
            "recommendation_status IN ('recommended', 'pareto', 'alternative', 'rejected')",
            name="ck_optimization_result_recommendation_status",
        ),
        Index("ix_optimization_result_task_level", "task_id", "pareto_level"),
    )

    candidate_id: Mapped[int] = mapped_column(
        ForeignKey("optimization_candidate.id", ondelete="CASCADE"), primary_key=True
    )
    task_id: Mapped[int] = mapped_column(
        ForeignKey("optimization_task.id", ondelete="CASCADE"), nullable=False
    )
    pareto_level: Mapped[int] = mapped_column(Integer, nullable=False)
    rank: Mapped[int] = mapped_column(Integer, nullable=False)
    recommendation_status: Mapped[str] = mapped_column(String(16), nullable=False)
    explanation: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
