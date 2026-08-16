"""Create the authoritative GIS layer and basemap registries.

Revision ID: 20260815_0013
Revises: 20260814_0012
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "20260815_0013"
down_revision: str | None = "20260814_0012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add fail-closed, URL-free registries for Catalog construction."""

    op.create_table(
        "gis_layer_registry",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("layer_key", sa.String(63), nullable=False),
        sa.Column("title", sa.String(128), nullable=False),
        sa.Column("group_key", sa.String(63), nullable=False),
        sa.Column("source_schema", sa.String(16), nullable=False),
        sa.Column("source_relation", sa.String(63), nullable=False),
        sa.Column("geometry_type", sa.String(24), nullable=False),
        sa.Column("native_crs", sa.String(16), nullable=False),
        sa.Column("qgis_short_name", sa.String(63)),
        sa.Column("service_mode", sa.String(32), nullable=False),
        sa.Column("render_mode", sa.String(32), nullable=False),
        sa.Column("dataset_filter_field", sa.String(63)),
        sa.Column("identify_enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("legend_enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("search_enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("capabilities", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("feature_info_fields", postgresql.JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("cache_mode", sa.String(24), nullable=False, server_default="NONE"),
        sa.Column("identify_mode", sa.String(24), nullable=False, server_default="NONE"),
        sa.Column("detail_route_key", sa.String(63)),
        sa.Column("model_entity_type", sa.String(63)),
        sa.Column("display_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("default_visible", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("default_opacity", sa.Float(), nullable=False, server_default="1"),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("revision", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("created_by", sa.String(64), nullable=False, server_default="migration"),
        sa.Column("updated_by", sa.String(64), nullable=False, server_default="migration"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("layer_key ~ '^[a-z][a-z0-9_]{1,62}$'", name="ck_gis_layer_registry_layer_key"),
        sa.CheckConstraint("source_schema IN ('publish','tiles')", name="ck_gis_layer_registry_source_schema"),
        sa.CheckConstraint("source_relation ~ '^[a-z][a-z0-9_]{1,62}$'", name="ck_gis_layer_registry_source_relation"),
        sa.CheckConstraint("geometry_type IN ('POINT','LINESTRING','POLYGON','MULTIPOINT','MULTILINESTRING','MULTIPOLYGON','NONE')", name="ck_gis_layer_registry_geometry_type"),
        sa.CheckConstraint("native_crs ~ '^EPSG:[0-9]{4,6}$'", name="ck_gis_layer_registry_native_crs"),
        sa.CheckConstraint("service_mode IN ('QGIS_WMS','GEOSERVER_WMS_LEGACY','MARTIN_MVT','TITILER','FASTAPI','CESIUM_DYNAMIC','THREE_D_TILES')", name="ck_gis_layer_registry_service_mode"),
        sa.CheckConstraint("render_mode IN ('RASTER_WMS','VECTOR_TILE','RASTER_TILE','DYNAMIC_PRIMITIVE','THREE_D')", name="ck_gis_layer_registry_render_mode"),
        sa.CheckConstraint("(service_mode = 'QGIS_WMS' AND render_mode = 'RASTER_WMS') OR (service_mode = 'GEOSERVER_WMS_LEGACY' AND render_mode IN ('RASTER_WMS','RASTER_TILE')) OR (service_mode = 'MARTIN_MVT' AND render_mode = 'VECTOR_TILE') OR (service_mode = 'TITILER' AND render_mode = 'RASTER_TILE') OR (service_mode IN ('FASTAPI','CESIUM_DYNAMIC') AND render_mode = 'DYNAMIC_PRIMITIVE') OR (service_mode = 'THREE_D_TILES' AND render_mode = 'THREE_D')", name="ck_gis_layer_registry_service_render"),
        sa.CheckConstraint("service_mode <> 'QGIS_WMS' OR (qgis_short_name IS NOT NULL AND dataset_filter_field = 'dataset_version_id' AND source_schema = 'publish')", name="ck_gis_layer_registry_qgis_contract"),
        sa.CheckConstraint("dataset_filter_field IS NULL OR dataset_filter_field = 'dataset_version_id'", name="ck_gis_layer_registry_filter_field"),
        sa.CheckConstraint("cache_mode IN ('NONE','CLIENT_PRIVATE','VERSIONED_PUBLIC')", name="ck_gis_layer_registry_cache_mode"),
        sa.CheckConstraint("identify_mode IN ('NONE','FEATURE_INFO','DETAIL_API','CLIENT_PICK')", name="ck_gis_layer_registry_identify_mode"),
        sa.CheckConstraint("default_opacity >= 0 AND default_opacity <= 1", name="ck_gis_layer_registry_opacity"),
        sa.UniqueConstraint("layer_key", name="uq_gis_layer_registry_layer_key"),
    )
    op.create_index("uq_gis_layer_registry_qgis_short_name", "gis_layer_registry", ["qgis_short_name"], unique=True, postgresql_where=sa.text("qgis_short_name IS NOT NULL"))
    op.create_index("ix_gis_layer_registry_active_order", "gis_layer_registry", ["active", "display_order"])

    op.create_table(
        "basemap_registry",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("basemap_key", sa.String(63), nullable=False),
        sa.Column("title", sa.String(128), nullable=False),
        sa.Column("basemap_type", sa.String(24), nullable=False),
        sa.Column("endpoint_key", sa.String(63), nullable=False),
        sa.Column("native_crs", sa.String(16), nullable=False),
        sa.Column("credit", sa.String(256), nullable=False),
        sa.Column("display_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("default_visible", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("default_opacity", sa.Float(), nullable=False, server_default="1"),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("revision", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("created_by", sa.String(64), nullable=False, server_default="migration"),
        sa.Column("updated_by", sa.String(64), nullable=False, server_default="migration"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("basemap_key ~ '^[a-z][a-z0-9_]{1,62}$'", name="ck_basemap_registry_key"),
        sa.CheckConstraint("basemap_type IN ('XYZ','WMS','WMTS','COG','MVT','ARCGIS_REST')", name="ck_basemap_registry_type"),
        sa.CheckConstraint("endpoint_key ~ '^[a-z][a-z0-9_]{1,62}$'", name="ck_basemap_registry_endpoint_key"),
        sa.CheckConstraint("native_crs ~ '^EPSG:[0-9]{4,6}$'", name="ck_basemap_registry_native_crs"),
        sa.CheckConstraint("default_opacity >= 0 AND default_opacity <= 1", name="ck_basemap_registry_opacity"),
        sa.UniqueConstraint("basemap_key", name="uq_basemap_registry_key"),
        sa.UniqueConstraint("endpoint_key", name="uq_basemap_registry_endpoint_key"),
    )
    op.create_index("ix_basemap_registry_active_order", "basemap_registry", ["active", "display_order"])


def downgrade() -> None:
    """Remove only the registries introduced by this revision."""

    op.drop_index("ix_basemap_registry_active_order", table_name="basemap_registry")
    op.drop_table("basemap_registry")
    op.drop_index("ix_gis_layer_registry_active_order", table_name="gis_layer_registry")
    op.drop_index("uq_gis_layer_registry_qgis_short_name", table_name="gis_layer_registry")
    op.drop_table("gis_layer_registry")
