# Derived Cross Section Spatial Geometry

## Current contract

The hydraulic profile remains authoritative as ordered `Station/Offset + Elevation`.
`sequence=0` is the downstream-looking left side and station increases to the
right side. Raw station, elevation, source XY and marker station values are never
rewritten by spatial derivation.

Branch geometry is stored in the display CRS (EPSG:4490), while the branch's
network `engineering_crs` is used for all metric calculations. Ordered branch
vertices and their adopted chainages are transformed to that projected CRS before
linear reference, so X/Y field names cannot silently change the axis semantics.

## Algorithm

1. Locate `branch_intersection_point = pointAtChainage(branch, section.chainage)`
   using the branch's persisted vertex order and chainage axis. Exact vertex hits
   are returned without a numerical offset.
2. Sample `s-delta` and `s+delta` (one-sided at endpoints) and normalize
   `t = P_after - P_before`. This is a local downstream tangent and is not a
   permanently cached segment direction.
3. Use `leftNormal=(-ty, tx)` and `rightNormal=(ty, -tx)` in projected XY.
4. Select `branch_intersection_station` from an explicit `main_channel` Marker 2;
   legacy `thalweg` is accepted as the backward-compatible Marker 2 form. If no
   Marker 2 exists, use the profile midpoint and set
   `anchor_source=MIDPOINT_FALLBACK`, `review_status=NEEDS_REVIEW`.
5. For every raw profile station, emit `intersection + rightNormal * (station-anchor)`.
   The derived line length is exactly `stationMax - stationMin`. Derived points,
   line and intersection are stored separately and can be regenerated or cleared.

## Source precedence and state

`SURVEY_XY` always wins over `DERIVED_FROM_BRANCH`; derived geometry never replaces
survey axis or point geometry. `UNAVAILABLE` is used only when branch geometry,
branch vertices, engineering CRS or chainage cannot support the calculation.
`hydraulic_ready` is independent from `spatial_geometry_status`, so missing GIS
geometry cannot block 1-D hydraulic calculation.

The API exposes:

- `POST /api/v1/hydraulic/cross-sections/{id}/derive-spatial-geometry`
- `DELETE /api/v1/hydraulic/cross-sections/{id}/derived-spatial-geometry` (clear only disposable derived XY)
- `POST /api/v1/hydraulic/datasets/{dataset_version_id}/derive-spatial-geometry`
- `GET /api/v1/gis/hydraulic-cross-sections`

The GIS response is survey-first/derived-second and contains the effective
cross-section line, branch intersection, and Marker 1/2/3 point geometries.
