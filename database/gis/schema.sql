-- GIS-RESET-01 reference schema. Alembic remains the deployment authority.
-- The existing dayu_tiangong database is the only PostGIS data center.

CREATE EXTENSION IF NOT EXISTS postgis;

-- Authoritative business objects remain in public and are versioned by
-- dataset_version_id. QGIS writes only staging_qgis; GeoServer reads only the
-- version-filtered publish views created by Alembic revision 20260814_0012.

-- Active rows in the compatibility-named table form the PostGIS GIS Catalog.
-- GIS-RESET-01 revision 20260817_0015 guarantees active rows are publish views
-- rendered only through GeoServer WMS.
SELECT layer_key, title, group_key, source_schema, source_relation,
       geometry_type, native_crs, dataset_filter_field, display_order,
       default_visible, default_opacity
  FROM public.gis_layer_registry
 WHERE active IS TRUE
 ORDER BY display_order, layer_key;
