"""Shared XY-to-Branch-to-Chainage mapping for hydraulic domain entities."""

from __future__ import annotations

from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.hydraulic.models import HydraulicBranch, HydraulicNetwork


def locate_geometry_on_branch(
    session: Session,
    branch: HydraulicBranch,
    network: HydraulicNetwork,
    geometry: Any,
) -> tuple[float, float]:
    """Return increasing branch chainage and metric snap distance in engineering CRS."""

    if network.engineering_crs is None:
        raise ValueError("Hydraulic network engineering CRS is unavailable")
    srid = int(network.engineering_crs.split(":", 1)[1])
    branch_geometry = func.ST_Transform(branch.geometry, srid)
    entity_geometry = func.ST_Transform(geometry, srid)
    fraction, distance_m = session.execute(
        select(
            func.ST_LineLocatePoint(
                branch_geometry,
                func.ST_ClosestPoint(branch_geometry, entity_geometry),
            ),
            func.ST_Distance(branch_geometry, entity_geometry),
        )
    ).one()
    computed = branch.start_chainage + (branch.end_chainage - branch.start_chainage) * float(
        fraction
    )
    return computed, float(distance_m)
