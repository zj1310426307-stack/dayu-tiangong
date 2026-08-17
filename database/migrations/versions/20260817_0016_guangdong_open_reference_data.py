"""Add Guangdong open reference data tables and NASA imagery basemaps.

Revision ID: 20260817_0016
Revises: 20260817_0015
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from geoalchemy2 import Geometry
from sqlalchemy.dialects import postgresql


revision: str = "20260817_0016"
down_revision: str | None = "20260817_0015"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


CORE_KEYS = ("river", "cross_section", "gate", "pump", "river_segment", "river_node")
LEGACY_REFERENCE_KEYS = ("map_annotation", "place_name", "water_name", "poi")


def _quoted(values: tuple[str, ...]) -> str:
    """Render migration-owned identifiers as one SQL string list."""

    return ",".join(f"'{value}'" for value in values)


def _reference_columns(geometry_type: str, table_name: str) -> list[sa.Column]:
    """Return the common provenance columns for one open reference table."""

    return [
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("source", sa.String(length=64), nullable=False),
        sa.Column("source_id", sa.String(length=160), nullable=False),
        sa.Column("source_snapshot", sa.String(length=80), nullable=False),
        sa.Column("name", sa.String(length=256), nullable=False),
        sa.Column("address", sa.String(length=256), nullable=True),
        sa.Column("metadata_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("geometry", Geometry(geometry_type=geometry_type, srid=4490, spatial_index=False), nullable=False),
        sa.Column("imported_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("source", "source_id", name=f"uq_reference_{table_name}_source_id"),
    ]


def upgrade() -> None:
    """Create version-independent reference tables and activate truthful map layers."""

    op.execute("CREATE SCHEMA IF NOT EXISTS reference_data")
    op.create_table(
        "administrative_area",
        *_reference_columns("MULTIPOLYGON", "administrative_area"),
        sa.Column("administrative_level", sa.String(length=32), nullable=False),
        schema="reference_data",
    )
    op.create_index(
        "ix_reference_administrative_area_geometry_gist",
        "administrative_area",
        ["geometry"],
        unique=False,
        schema="reference_data",
        postgresql_using="gist",
    )
    op.create_table(
        "road",
        *_reference_columns("MULTILINESTRING", "road"),
        sa.Column("road_type", sa.String(length=32), nullable=False),
        schema="reference_data",
    )
    op.create_index(
        "ix_reference_road_geometry_gist",
        "road",
        ["geometry"],
        unique=False,
        schema="reference_data",
        postgresql_using="gist",
    )
    op.create_table(
        "waterway",
        *_reference_columns("MULTILINESTRING", "waterway"),
        sa.Column("waterway_type", sa.String(length=32), nullable=False),
        schema="reference_data",
    )
    op.create_index(
        "ix_reference_waterway_geometry_gist",
        "waterway",
        ["geometry"],
        unique=False,
        schema="reference_data",
        postgresql_using="gist",
    )

    op.execute(
        """
        CREATE VIEW publish.administrative_area_open AS
        SELECT id, source, source_id, source_snapshot, name, address,
               administrative_level, metadata_json, geometry, imported_at
          FROM reference_data.administrative_area
        """
    )
    op.execute(
        """
        CREATE VIEW publish.road_open AS
        SELECT id, source, source_id, source_snapshot, name, address,
               road_type, metadata_json, geometry, imported_at
          FROM reference_data.road
        """
    )
    op.execute(
        """
        CREATE VIEW publish.waterway_open AS
        SELECT id, source, source_id, source_snapshot, name, address,
               waterway_type, metadata_json, geometry, imported_at
          FROM reference_data.waterway
        """
    )

    op.drop_constraint(
        "ck_gis_catalog_active_version_filter", "gis_layer_registry", type_="check"
    )
    op.execute("UPDATE gis_layer_registry SET active = FALSE")
    op.execute(
        "UPDATE gis_layer_registry SET active = TRUE, source_schema = 'publish', "
        "source_relation = layer_key, dataset_filter_field = 'dataset_version_id', "
        "service_mode = 'GEOSERVER_WMS', render_mode = 'RASTER_WMS', "
        "updated_by = 'gis-open-data-guangdong', revision = revision + 1 "
        f"WHERE layer_key IN ({_quoted(CORE_KEYS)})"
    )
    op.execute(
        """
        UPDATE gis_layer_registry
           SET title = '广东行政区（开放数据）', source_relation = 'administrative_area_open',
               geometry_type = 'MULTIPOLYGON', dataset_filter_field = NULL,
               default_visible = TRUE, default_opacity = 0.28, search_enabled = FALSE,
               active = TRUE, updated_by = 'gis-open-data-guangdong', revision = revision + 1
         WHERE layer_key = 'administrative_area'
        """
    )
    op.execute(
        """
        UPDATE gis_layer_registry
           SET title = '广东主要道路（OpenStreetMap）', source_relation = 'road_open',
               geometry_type = 'MULTILINESTRING', dataset_filter_field = NULL,
               default_visible = TRUE, default_opacity = 0.80, search_enabled = FALSE,
               active = TRUE, updated_by = 'gis-open-data-guangdong', revision = revision + 1
         WHERE layer_key = 'road'
        """
    )
    op.execute(
        """
        INSERT INTO gis_layer_registry
            (layer_key, title, group_key, source_schema, source_relation, geometry_type,
             native_crs, qgis_short_name, service_mode, render_mode, dataset_filter_field,
             identify_enabled, legend_enabled, search_enabled, capabilities,
             feature_info_fields, cache_mode, identify_mode, detail_route_key,
             model_entity_type, display_order, default_visible, default_opacity,
             active, revision, created_by, updated_by)
        VALUES
            ('waterway', '广东主要水系（OpenStreetMap）', '90_REFERENCE', 'publish',
             'waterway_open', 'MULTILINESTRING', 'EPSG:4490', NULL, 'GEOSERVER_WMS',
             'RASTER_WMS', NULL, TRUE, TRUE, FALSE,
             jsonb_build_object('render',TRUE,'identify',TRUE,'legend',TRUE,'print',FALSE),
             jsonb_build_array('id','source','source_id','name','waterway_type'),
             'CLIENT_PRIVATE', 'FEATURE_INFO', NULL, NULL, 100, TRUE, 0.90,
             TRUE, 1, 'gis-open-data-guangdong', 'gis-open-data-guangdong')
        ON CONFLICT (layer_key) DO UPDATE SET
             title = EXCLUDED.title, source_schema = EXCLUDED.source_schema,
             source_relation = EXCLUDED.source_relation, geometry_type = EXCLUDED.geometry_type,
             dataset_filter_field = NULL, identify_enabled = TRUE, legend_enabled = TRUE,
             search_enabled = FALSE, display_order = EXCLUDED.display_order,
             default_visible = TRUE, default_opacity = EXCLUDED.default_opacity,
             active = TRUE, updated_by = 'gis-open-data-guangdong',
             revision = gis_layer_registry.revision + 1
        """
    )

    op.execute("UPDATE basemap_registry SET active = FALSE")
    op.execute(
        """
        INSERT INTO basemap_registry
            (basemap_key, title, basemap_type, endpoint_key, native_crs, credit,
             display_order, default_visible, default_opacity, active, revision,
             created_by, updated_by)
        VALUES
            ('nasa_blue_marble', 'NASA Blue Marble 真彩色影像', 'XYZ',
             'nasa_gibs_blue_marble', 'EPSG:3857',
             'NASA Earth Observatory / GIBS', 0, TRUE, 1.0, TRUE, 1,
             'gis-open-data-guangdong', 'gis-open-data-guangdong'),
            ('nasa_viirs_true_color', 'NASA VIIRS 真彩色影像 2026-08-16', 'XYZ',
             'nasa_gibs_viirs_20260816', 'EPSG:3857',
             'NASA EOSDIS GIBS / VIIRS NOAA-21', 1, TRUE, 1.0, TRUE, 1,
             'gis-open-data-guangdong', 'gis-open-data-guangdong')
        ON CONFLICT (basemap_key) DO UPDATE SET
             title = EXCLUDED.title, basemap_type = EXCLUDED.basemap_type,
             endpoint_key = EXCLUDED.endpoint_key, native_crs = EXCLUDED.native_crs,
             credit = EXCLUDED.credit, display_order = EXCLUDED.display_order,
             default_visible = EXCLUDED.default_visible,
             default_opacity = EXCLUDED.default_opacity, active = TRUE,
             updated_by = 'gis-open-data-guangdong',
             revision = basemap_registry.revision + 1
        """
    )


def downgrade() -> None:
    """Restore the version-scoped GIS-RESET-01 catalog and remove new data."""

    op.execute(
        "DELETE FROM basemap_registry WHERE basemap_key IN "
        "('nasa_blue_marble','nasa_viirs_true_color')"
    )
    op.execute("UPDATE basemap_registry SET active = TRUE WHERE basemap_key = 'world_imagery'")
    op.execute("DELETE FROM gis_layer_registry WHERE layer_key = 'waterway'")
    op.execute(
        "UPDATE gis_layer_registry SET active = TRUE, source_schema = 'publish', "
        "source_relation = layer_key, dataset_filter_field = 'dataset_version_id', "
        "service_mode = 'GEOSERVER_WMS', render_mode = 'RASTER_WMS', "
        "updated_by = 'gis-reset-01', revision = revision + 1 "
        f"WHERE layer_key IN ({_quoted(CORE_KEYS + LEGACY_REFERENCE_KEYS + ('administrative_area', 'road'))})"
    )
    op.execute(
        "UPDATE gis_layer_registry SET title = '行政区', geometry_type = 'POLYGON', "
        "default_visible = FALSE, default_opacity = 1 WHERE layer_key = 'administrative_area'"
    )
    op.execute(
        "UPDATE gis_layer_registry SET title = '道路', geometry_type = 'LINESTRING', "
        "default_visible = FALSE, default_opacity = 1 WHERE layer_key = 'road'"
    )
    op.create_check_constraint(
        "ck_gis_catalog_active_version_filter",
        "gis_layer_registry",
        "active IS NOT TRUE OR dataset_filter_field = 'dataset_version_id'",
    )

    op.execute("DROP VIEW publish.waterway_open")
    op.execute("DROP VIEW publish.road_open")
    op.execute("DROP VIEW publish.administrative_area_open")
    op.drop_index(
        "ix_reference_waterway_geometry_gist",
        table_name="waterway",
        schema="reference_data",
    )
    op.drop_table("waterway", schema="reference_data")
    op.drop_index(
        "ix_reference_road_geometry_gist", table_name="road", schema="reference_data"
    )
    op.drop_table("road", schema="reference_data")
    op.drop_index(
        "ix_reference_administrative_area_geometry_gist",
        table_name="administrative_area",
        schema="reference_data",
    )
    op.drop_table("administrative_area", schema="reference_data")
    op.execute("DROP SCHEMA reference_data")
