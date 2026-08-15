"""Expose the complete GeoServer catalog through the published-version boundary.

Revision ID: 20260814_0012
Revises: 20260814_0011
"""

from collections.abc import Sequence

from alembic import op


revision: str = "20260814_0012"
down_revision: str | None = "20260814_0011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


PUBLISH_VIEWS = (
    "river",
    "river_segment",
    "river_node",
    "cross_section",
    "gate",
    "pump",
    "map_annotation",
    "administrative_area",
    "road",
    "place_name",
    "water_name",
    "poi",
)


def _drop_publish_views() -> None:
    """Drop only the version-filtered views owned by this migration chain."""

    for view_name in reversed(PUBLISH_VIEWS):
        op.execute(f"DROP VIEW IF EXISTS publish.{view_name}")


def _create_complete_publish_views() -> None:
    """Mirror all twelve GeoServer feature types while filtering published versions."""

    op.execute("""
        CREATE VIEW publish.river AS
        SELECT r.id, r.dataset_version_id, r.name, r.code, r.length, r.level,
               r.status, r.description, r.geometry, r.created_time,
               dv.version AS dataset_version, dv.content_hash, dv.published_at
          FROM public.river AS r
          JOIN public.dataset_version AS dv ON dv.id = r.dataset_version_id
         WHERE dv.status = 'published'
    """)
    op.execute("""
        CREATE VIEW publish.river_segment AS
        SELECT s.id, s.dataset_version_id, s.river_id, s.segment_code,
               s.upstream_node_id, s.downstream_node_id, s.length, s.geometry,
               dv.version AS dataset_version, dv.content_hash, dv.published_at
          FROM public.river_segment AS s
          JOIN public.dataset_version AS dv ON dv.id = s.dataset_version_id
         WHERE dv.status = 'published'
    """)
    op.execute("""
        CREATE VIEW publish.river_node AS
        SELECT n.id, n.dataset_version_id, n.node_code, n.node_type,
               n.longitude, n.latitude, n.geometry,
               dv.version AS dataset_version, dv.content_hash, dv.published_at
          FROM public.river_node AS n
          JOIN public.dataset_version AS dv ON dv.id = n.dataset_version_id
         WHERE dv.status = 'published'
    """)
    op.execute("""
        CREATE VIEW publish.cross_section AS
        SELECT cs.id, cs.dataset_version_id, cs.river_id, cs.section_code,
               cs.section_name, cs.station, cs.points, cs.roughness,
               cs.elevation_min, cs.survey_date, cs.geometry, cs.created_time,
               r.code AS river_code, dv.version AS dataset_version,
               dv.content_hash, dv.published_at
          FROM public.cross_section AS cs
          JOIN public.dataset_version AS dv ON dv.id = cs.dataset_version_id
          JOIN public.river AS r ON r.id = cs.river_id
         WHERE dv.status = 'published'
    """)
    op.execute("""
        CREATE VIEW publish.gate AS
        SELECT g.id, g.dataset_version_id, g.name, g.gate_code, g.river_id,
               g.gate_type, g.opening_direction, g.control_mode, g.width,
               g.height, g.max_flow, g.bottom_elevation, g.river_segment_id,
               g.station, g.upstream_node_id, g.downstream_node_id,
               g.crest_elevation, g.discharge_coefficient, g.minimum_opening,
               g.maximum_opening, g.opening_rate_limit, g.minimum_hold_seconds,
               g.allow_reverse_flow, g.status, g.geometry, g.created_time,
               r.code AS river_code, dv.version AS dataset_version,
               dv.content_hash, dv.published_at
          FROM public.gate AS g
          JOIN public.dataset_version AS dv ON dv.id = g.dataset_version_id
          JOIN public.river AS r ON r.id = g.river_id
         WHERE dv.status = 'published'
    """)
    op.execute("""
        CREATE VIEW publish.pump AS
        SELECT p.id, p.dataset_version_id, p.name, p.pump_code, p.river_id,
               p.design_flow, p.head, p.power, p.efficiency_curve, p.head_curve,
               p.intake_node_id, p.outlet_node_id, p.transfer_type, p.unit_count,
               p.minimum_running_units, p.maximum_running_units,
               p.minimum_run_seconds, p.minimum_stop_seconds,
               p.maximum_starts_per_run, p.minimum_operating_head,
               p.maximum_operating_head, p.reverse_flow_protection,
               p.control_mode, p.status, p.geometry, p.created_time,
               r.code AS river_code, dv.version AS dataset_version,
               dv.content_hash, dv.published_at
          FROM public.pump AS p
          JOIN public.dataset_version AS dv ON dv.id = p.dataset_version_id
          JOIN public.river AS r ON r.id = p.river_id
         WHERE dv.status = 'published'
    """)
    op.execute("""
        CREATE VIEW publish.map_annotation AS
        SELECT a.id, a.dataset_version_id, a.annotation_type, a.name, a.text,
               a.description, a.longitude, a.latitude, a.rotation, a.font_size,
               a.color, a.visible_scale_min, a.visible_scale_max, a.related_type,
               a.related_id, a.geometry, a.created_time,
               dv.version AS dataset_version, dv.content_hash, dv.published_at
          FROM public.map_annotation AS a
          JOIN public.dataset_version AS dv ON dv.id = a.dataset_version_id
         WHERE dv.status = 'published'
    """)
    op.execute("""
        CREATE VIEW publish.administrative_area AS
        SELECT a.id, a.dataset_version_id, a.code, a.name,
               a.administrative_level, a.address, a.geometry,
               dv.version AS dataset_version, dv.content_hash, dv.published_at
          FROM public.administrative_area AS a
          JOIN public.dataset_version AS dv ON dv.id = a.dataset_version_id
         WHERE dv.status = 'published'
    """)
    op.execute("""
        CREATE VIEW publish.road AS
        SELECT r.id, r.dataset_version_id, r.code, r.name, r.road_type,
               r.address, r.geometry, dv.version AS dataset_version,
               dv.content_hash, dv.published_at
          FROM public.road AS r
          JOIN public.dataset_version AS dv ON dv.id = r.dataset_version_id
         WHERE dv.status = 'published'
    """)
    op.execute("""
        CREATE VIEW publish.place_name AS
        SELECT p.id, p.dataset_version_id, p.code, p.name, p.place_type,
               p.address, p.importance, p.geometry,
               dv.version AS dataset_version, dv.content_hash, dv.published_at
          FROM public.place_name AS p
          JOIN public.dataset_version AS dv ON dv.id = p.dataset_version_id
         WHERE dv.status = 'published'
    """)
    op.execute("""
        CREATE VIEW publish.water_name AS
        SELECT w.id, w.dataset_version_id, w.code, w.name, w.water_type,
               w.address, w.geometry, dv.version AS dataset_version,
               dv.content_hash, dv.published_at
          FROM public.water_name AS w
          JOIN public.dataset_version AS dv ON dv.id = w.dataset_version_id
         WHERE dv.status = 'published'
    """)
    op.execute("""
        CREATE VIEW publish.poi AS
        SELECT p.id, p.dataset_version_id, p.code, p.name, p.category,
               p.address, p.geometry, dv.version AS dataset_version,
               dv.content_hash, dv.published_at
          FROM public.poi AS p
          JOIN public.dataset_version AS dv ON dv.id = p.dataset_version_id
         WHERE dv.status = 'published'
    """)


def _restore_opt1_views() -> None:
    """Restore the four GIS-OPT-1 views when rolling back this compatibility step."""

    op.execute("""
        CREATE VIEW publish.river AS
        SELECT r.id, r.dataset_version_id, dv.version AS dataset_version,
               r.name, r.code, r.length, r.level, r.status, r.description,
               r.geometry, dv.content_hash, dv.published_at
          FROM public.river AS r
          JOIN public.dataset_version AS dv ON dv.id = r.dataset_version_id
         WHERE dv.status = 'published'
    """)
    op.execute("""
        CREATE VIEW publish.cross_section AS
        SELECT cs.id, cs.dataset_version_id, dv.version AS dataset_version,
               cs.river_id, r.code AS river_code, cs.section_code, cs.section_name,
               cs.station, cs.points, cs.roughness, cs.elevation_min, cs.survey_date,
               cs.geometry, dv.content_hash, dv.published_at
          FROM public.cross_section AS cs
          JOIN public.dataset_version AS dv ON dv.id = cs.dataset_version_id
          JOIN public.river AS r ON r.id = cs.river_id
         WHERE dv.status = 'published'
    """)
    op.execute("""
        CREATE VIEW publish.gate AS
        SELECT g.id, g.dataset_version_id, dv.version AS dataset_version,
               g.river_id, r.code AS river_code, g.name, g.gate_code, g.gate_type,
               g.opening_direction, g.control_mode, g.width, g.height, g.max_flow,
               g.bottom_elevation, g.station, g.crest_elevation,
               g.discharge_coefficient, g.minimum_opening, g.maximum_opening,
               g.opening_rate_limit, g.minimum_hold_seconds, g.allow_reverse_flow,
               g.status, g.geometry, dv.content_hash, dv.published_at
          FROM public.gate AS g
          JOIN public.dataset_version AS dv ON dv.id = g.dataset_version_id
          JOIN public.river AS r ON r.id = g.river_id
         WHERE dv.status = 'published'
    """)
    op.execute("""
        CREATE VIEW publish.pump AS
        SELECT p.id, p.dataset_version_id, dv.version AS dataset_version,
               p.river_id, r.code AS river_code, p.name, p.pump_code,
               p.design_flow, p.head, p.power, p.efficiency_curve, p.head_curve,
               p.transfer_type, p.unit_count, p.minimum_running_units,
               p.maximum_running_units, p.minimum_run_seconds, p.minimum_stop_seconds,
               p.maximum_starts_per_run, p.minimum_operating_head,
               p.maximum_operating_head, p.reverse_flow_protection,
               p.control_mode, p.status, p.geometry, dv.content_hash, dv.published_at
          FROM public.pump AS p
          JOIN public.dataset_version AS dv ON dv.id = p.dataset_version_id
          JOIN public.river AS r ON r.id = p.river_id
         WHERE dv.status = 'published'
    """)


def upgrade() -> None:
    """Publish all twelve GeoServer feature types from the controlled boundary."""

    _drop_publish_views()
    _create_complete_publish_views()


def downgrade() -> None:
    """Return to the four-view GIS-OPT-1 publication boundary."""

    _drop_publish_views()
    _restore_opt1_views()
