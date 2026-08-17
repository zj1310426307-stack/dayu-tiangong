"""Register one building-scale online imagery basemap for Guangdong.

Revision ID: 20260817_0017
Revises: 20260817_0016
"""

from collections.abc import Sequence

from alembic import op


revision: str = "20260817_0017"
down_revision: str | None = "20260817_0016"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Make high-resolution Esri imagery primary while retaining NASA fallbacks."""

    op.execute(
        "UPDATE basemap_registry SET default_visible = FALSE, "
        "updated_by = 'high-resolution-imagery', revision = revision + 1 "
        "WHERE basemap_key IN ('nasa_blue_marble','nasa_viirs_true_color')"
    )
    op.execute(
        """
        INSERT INTO basemap_registry
            (basemap_key, title, basemap_type, endpoint_key, native_crs, credit,
             display_order, default_visible, default_opacity, active, revision,
             created_by, updated_by)
        VALUES
            ('esri_world_imagery', 'Esri World Imagery 高分辨率影像', 'XYZ',
             'esri_world_imagery', 'EPSG:3857',
             'Source: Esri, Vantor, Earthstar Geographics, and the GIS User Community',
             2, TRUE, 1.0, TRUE, 1,
             'high-resolution-imagery', 'high-resolution-imagery')
        ON CONFLICT (basemap_key) DO UPDATE SET
             title = EXCLUDED.title, basemap_type = EXCLUDED.basemap_type,
             endpoint_key = EXCLUDED.endpoint_key, native_crs = EXCLUDED.native_crs,
             credit = EXCLUDED.credit, display_order = EXCLUDED.display_order,
             default_visible = TRUE, default_opacity = 1.0, active = TRUE,
             updated_by = 'high-resolution-imagery',
             revision = basemap_registry.revision + 1
        """
    )


def downgrade() -> None:
    """Restore the two NASA basemaps as the visible 0016 configuration."""

    op.execute("DELETE FROM basemap_registry WHERE basemap_key = 'esri_world_imagery'")
    op.execute(
        "UPDATE basemap_registry SET default_visible = TRUE, "
        "updated_by = 'gis-open-data-guangdong', revision = revision + 1 "
        "WHERE basemap_key IN ('nasa_blue_marble','nasa_viirs_true_color')"
    )
