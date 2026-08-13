"""Add the Phase DGIS-Foundation spatiotemporal catalog.

Revision ID: 20260813_0010
Revises: 20260813_0009
"""

from collections.abc import Sequence

from alembic import op
import geoalchemy2
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "20260813_0010"
down_revision: str | None = "20260813_0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _create_tile_function(
    function_name: str,
    table_name: str,
    geometry_expression: str,
    properties: str,
) -> None:
    """Publish one version-filtered MVT function for Martin auto-discovery."""

    op.execute(f"""
        CREATE OR REPLACE FUNCTION tiles.{function_name}(
            z integer, x integer, y integer, query json DEFAULT '{{}}'::json
        ) RETURNS bytea AS $$
        DECLARE
            mvt bytea;
            selected_version integer := COALESCE(
                NULLIF(query ->> 'dataset_version_id', '')::integer, 1
            );
        BEGIN
            SELECT INTO mvt ST_AsMVT(tile, '{function_name}', 4096, 'geom', 'id')
            FROM (
                SELECT id, {properties},
                    ST_AsMVTGeom(
                        ST_Transform({geometry_expression}, 3857),
                        ST_TileEnvelope(z, x, y), 4096, 64, true
                    ) AS geom
                FROM {table_name}
                WHERE dataset_version_id = selected_version
                  AND {geometry_expression} && ST_Transform(ST_TileEnvelope(z, x, y), 4490)
            ) AS tile
            WHERE geom IS NOT NULL;
            RETURN COALESCE(mvt, ''::bytea);
        END
        $$ LANGUAGE plpgsql STABLE STRICT PARALLEL SAFE;
    """)


def upgrade() -> None:
    """Enable TimescaleDB and add state, service catalog, and Martin MVT functions."""

    op.execute("CREATE EXTENSION IF NOT EXISTS timescaledb CASCADE")
    op.execute("CREATE SCHEMA IF NOT EXISTS imports AUTHORIZATION CURRENT_USER")

    op.create_table(
        "feature_state",
        sa.Column("id", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column("dataset_version_id", sa.Integer(), nullable=False),
        sa.Column("feature_type", sa.String(length=32), nullable=False),
        sa.Column("feature_id", sa.Integer(), nullable=False),
        sa.Column("timestamp", sa.DateTime(timezone=True), nullable=False),
        sa.Column("state_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "geometry",
            geoalchemy2.Geometry("GEOMETRY", srid=4490, spatial_index=False),
            nullable=False,
        ),
        sa.Column("source", sa.String(length=32), nullable=False),
        sa.Column("task_id", sa.Integer()),
        sa.CheckConstraint(
            "feature_type IN ('water_level','flow','rainfall','gate','pump','flood_risk')",
            name="ck_feature_state_type",
        ),
        sa.CheckConstraint(
            "source IN ('observation','simulation','dispatch','import')",
            name="ck_feature_state_source",
        ),
        sa.ForeignKeyConstraint(
            ["dataset_version_id"], ["dataset_version.id"],
            name="fk_feature_state_dataset_version_id", ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["task_id"], ["simulation_task.id"],
            name="fk_feature_state_task_id", ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", "timestamp", name="pk_feature_state"),
        sa.UniqueConstraint(
            "dataset_version_id", "feature_type", "feature_id", "timestamp", "source",
            name="uq_feature_state_identity",
        ),
    )
    op.create_index(
        "ix_feature_state_feature_time", "feature_state",
        ["dataset_version_id", "feature_type", "feature_id", sa.text("timestamp DESC")],
    )
    op.create_index(
        "ix_feature_state_geometry_gist", "feature_state", ["geometry"],
        postgresql_using="gist",
    )
    op.get_bind().exec_driver_sql("""
        SELECT create_hypertable(
            'feature_state', by_range('timestamp', INTERVAL '1 day'),
            if_not_exists => TRUE, migrate_data => TRUE
        )
    """)

    op.create_table(
        "simulation_layer",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("dataset_version_id", sa.Integer(), nullable=False),
        sa.Column("task_id", sa.Integer()),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("layer_type", sa.String(length=32), nullable=False),
        sa.Column("time_start", sa.DateTime(timezone=True)),
        sa.Column("time_end", sa.DateTime(timezone=True)),
        sa.Column("service_type", sa.String(length=24), nullable=False),
        sa.Column("service_url", sa.Text(), nullable=False),
        sa.Column("style", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("version", sa.String(length=64), nullable=False),
        sa.Column("created_time", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint(
            "layer_type IN ('water_level','velocity','flood_risk','terrain','facility_3d')",
            name="ck_simulation_layer_type",
        ),
        sa.CheckConstraint(
            "service_type IN ('COG','TITILER','MVT','WMS','3D_TILES')",
            name="ck_simulation_layer_service_type",
        ),
        sa.CheckConstraint(
            "time_end IS NULL OR time_start IS NULL OR time_end >= time_start",
            name="ck_simulation_layer_time_range",
        ),
        sa.ForeignKeyConstraint(
            ["dataset_version_id"], ["dataset_version.id"],
            name="fk_simulation_layer_dataset_version_id", ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["task_id"], ["simulation_task.id"],
            name="fk_simulation_layer_task_id", ondelete="SET NULL",
        ),
        sa.UniqueConstraint(
            "dataset_version_id", "name", "version", name="uq_simulation_layer_version_name"
        ),
    )
    op.create_index(
        "ix_simulation_layer_lookup", "simulation_layer",
        ["dataset_version_id", "layer_type", "task_id"],
    )

    op.execute("CREATE SCHEMA IF NOT EXISTS tiles")
    _create_tile_function("river", "river", "geometry", "name, code, level, status")
    _create_tile_function("road", "road", "geometry", "name, code, road_type")
    _create_tile_function(
        "administrative_area", "administrative_area", "geometry",
        "name, code, administrative_level",
    )
    _create_tile_function(
        "place_name", "place_name", "geometry", "name, code, place_type, importance"
    )
    op.get_bind().exec_driver_sql("""
        CREATE OR REPLACE FUNCTION tiles.engineering_facility(
            z integer, x integer, y integer, query json DEFAULT '{}'::json
        ) RETURNS bytea AS $$
        DECLARE
            mvt bytea;
            selected_version integer := COALESCE(
                NULLIF(query ->> 'dataset_version_id', '')::integer, 1
            );
        BEGIN
            SELECT INTO mvt ST_AsMVT(tile, 'engineering_facility', 4096, 'geom', 'id')
            FROM (
                SELECT id, name, gate_code AS code, 'gate'::text AS feature_type,
                    ST_AsMVTGeom(ST_Transform(geometry, 3857), ST_TileEnvelope(z,x,y), 4096,64,true) AS geom
                FROM gate WHERE dataset_version_id = selected_version
                  AND geometry && ST_Transform(ST_TileEnvelope(z,x,y),4490)
                UNION ALL
                SELECT id, name, pump_code AS code, 'pump'::text AS feature_type,
                    ST_AsMVTGeom(ST_Transform(geometry, 3857), ST_TileEnvelope(z,x,y), 4096,64,true) AS geom
                FROM pump WHERE dataset_version_id = selected_version
                  AND geometry && ST_Transform(ST_TileEnvelope(z,x,y),4490)
            ) AS tile WHERE geom IS NOT NULL;
            RETURN COALESCE(mvt, ''::bytea);
        END
        $$ LANGUAGE plpgsql STABLE STRICT PARALLEL SAFE;
    """)

    # JSON literals contain ``:<value>`` sequences. Execute seed statements
    # through the DBAPI driver so SQLAlchemy does not reinterpret JSON members
    # as bind parameters.
    op.get_bind().exec_driver_sql("""
        INSERT INTO simulation_layer (
            dataset_version_id, name, layer_type, service_type, service_url, style, version
        )
        SELECT id, 'DEMO 水深 COG', 'water_level', 'TITILER',
               '/api/v1/dgis/raster/{layer_id}/{z}/{x}/{y}.png',
               '{"asset_path":"/data/water-depth-demo.tif","colormap_name":"blues","rescale":"0,5","unit":"m","demo_data":true}'::jsonb,
               'dgis-demo-v1'
        FROM dataset_version
        UNION ALL
        SELECT id, 'DEMO 流速 COG', 'velocity', 'TITILER',
               '/api/v1/dgis/raster/{layer_id}/{z}/{x}/{y}.png',
               '{"asset_path":"/data/velocity-demo.tif","colormap_name":"viridis","rescale":"0,3","unit":"m/s","demo_data":true}'::jsonb,
               'dgis-demo-v1'
        FROM dataset_version
        UNION ALL
        SELECT id, 'DEMO 洪水风险 COG', 'flood_risk', 'TITILER',
               '/api/v1/dgis/raster/{layer_id}/{z}/{x}/{y}.png',
               '{"asset_path":"/data/flood-risk-demo.tif","colormap_name":"reds","rescale":"0,1","demo_data":true}'::jsonb,
               'dgis-demo-v1'
        FROM dataset_version
        UNION ALL
        SELECT id, 'DEMO 闸站 3D Tiles', 'facility_3d', '3D_TILES',
               '/3d/demo-tileset.json',
               '{"maximum_screen_space_error":16,"demo_data":true}'::jsonb,
               'dgis-demo-v1'
        FROM dataset_version
        ON CONFLICT (dataset_version_id, name, version) DO NOTHING
    """)

    op.get_bind().exec_driver_sql("""
        INSERT INTO feature_state (
            dataset_version_id, feature_type, feature_id, timestamp,
            state_json, geometry, source
        )
        SELECT version.id, sample.feature_type, sample.feature_id, sample.timestamp,
               sample.state_json, sample.geometry, sample.source
        FROM dataset_version AS version
        CROSS JOIN (VALUES
            ('gate', 1, TIMESTAMPTZ '2026-08-13 08:00:00+08',
             '{"opening":0.20,"status":"open","demo_data":true}'::jsonb,
             ST_SetSRID(ST_MakePoint(113.31,23.13),4490), 'dispatch'),
            ('gate', 1, TIMESTAMPTZ '2026-08-13 09:00:00+08',
             '{"opening":0.65,"status":"open","demo_data":true}'::jsonb,
             ST_SetSRID(ST_MakePoint(113.31,23.13),4490), 'dispatch'),
            ('pump', 1, TIMESTAMPTZ '2026-08-13 08:00:00+08',
             '{"flow":8.5,"power":420,"status":"running","demo_data":true}'::jsonb,
             ST_SetSRID(ST_MakePoint(113.35,23.12),4490), 'dispatch'),
            ('pump', 1, TIMESTAMPTZ '2026-08-13 09:00:00+08',
             '{"flow":12.0,"power":610,"status":"running","demo_data":true}'::jsonb,
             ST_SetSRID(ST_MakePoint(113.35,23.12),4490), 'dispatch'),
            ('water_level', 1, TIMESTAMPTZ '2026-08-13 09:00:00+08',
             '{"water_level":3.42,"unit":"m","demo_data":true}'::jsonb,
             ST_SetSRID(ST_MakePoint(113.30,23.14),4490), 'observation')
        ) AS sample(feature_type, feature_id, timestamp, state_json, geometry, source)
        ON CONFLICT (
            dataset_version_id, feature_type, feature_id, timestamp, source
        ) DO NOTHING
    """)


def downgrade() -> None:
    """Remove Phase DGIS catalog objects while preserving the shared extension."""

    for function_name in (
        "engineering_facility", "place_name", "administrative_area", "road", "river"
    ):
        op.execute(
            f"DROP FUNCTION IF EXISTS tiles.{function_name}(integer, integer, integer, json)"
        )
    op.execute("DROP SCHEMA IF EXISTS tiles")
    op.drop_index("ix_simulation_layer_lookup", table_name="simulation_layer")
    op.drop_table("simulation_layer")
    op.drop_index("ix_feature_state_geometry_gist", table_name="feature_state")
    op.drop_index("ix_feature_state_feature_time", table_name="feature_state")
    op.drop_table("feature_state")
    op.execute("DROP SCHEMA IF EXISTS imports")
