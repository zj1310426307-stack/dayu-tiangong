# Cross Section Marker and Processing Workflow

## Architecture

The authoritative flow is:

`Raw Survey → Marker → Active Extent → Processed Geometry → Hydraulic Data Core → Solver Adapter`.

Raw `Station/Offset + Elevation` is sufficient for one-dimensional hydraulic
calculation. Surveyed CGCS2000 XYZ is optional spatial evidence. When surveyed XY
is absent, the GIS line is derived from the branch centreline and chainage as
documented in [Derived Cross Section Spatial Geometry](cross-section-spatial-geometry.md).
Missing surveyed XY is not a hydraulic readiness error.

Raw points, source XYZ, survey codes and elevations are never rewritten by Marker
selection or overbank treatment. Marker state and disposable processed points are
stored on the active profile and can be rebuilt from the raw profile.

## Marker semantics and source precedence

- `M1 / LEFT_LEVEE`: downstream-looking left hydraulic control point.
- `M2 / CHANNEL_LOW_POINT`: deterministic main-channel low point.
- `M3 / RIGHT_LEVEE`: downstream-looking right hydraulic control point.
- Valid order is `M1.sequence < M2.sequence < M3.sequence`.

The precedence is `MANUAL > GIS_LEVEE > SURVEY_CODE >
AUTO_MIKE11_COMPATIBLE > IMPORT_DEFAULT`. A locked Marker is not replaced by
normal single-section or batch detection. The explicit “重新自动识别” operation
uses `force=true`, warns the operator, and may replace locked values.

Each Marker records its role, source point sequence, offset, elevation, optional
XY, source, confidence, review status, lock state, algorithm version and notes.
The JSON representation intentionally does not require a Marker to remain tied to
a raw point forever, so future interpolated Marker positions remain possible.

## Detection modes

- `FULL_EXTENT`: first point, deterministic minimum point, last point. M1/M3 are
  import defaults, not asserted engineering crest locations.
- `MIKE11_COMPATIBLE`: deterministic lowest point for M2, highest candidates on
  each side for M1/M3. A flat minimum uses its centre; a wide crest uses the point
  nearest the channel.
- `MANUAL`: resource update made by an operator; default review status is
  `REVIEWED`, and each Marker can be locked or unlocked independently.
- `GIS_ASSISTED`: reserved in the persistent model and source-priority contract.
  The current release does not claim an automatic levee-layer spatial matcher.

The pure detector does not inspect global CGCS2000 X/Y values. Left and right are
defined only by the imported downstream-looking point order. Risk flags include
insufficient points, missing side candidates, multiple lows or crests, boundary
crests, low prominence, spikes, unknown orientation, invalid order and implausible
active width. Risky candidates are `NEEDS_REVIEW`; they are never presented as an
unqualified engineering crest.

## Active extent and Vertical Extension

`FULL_EXTENT` uses every raw point. `MARKER_EXTENT` copies only the ordered raw
M1–M3 interval into the processed layer and retains all outside raw points.

`REAL_GEOMETRY` adds no virtual boundary. `VERTICAL_EXTENSION` creates a virtual
point above M1 at the same offset and another above M3 at the same offset. The
intervening profile is the unmodified real M1–M3 geometry. The extension top must
exceed both crest elevations. If it is below `designMaxWaterLevel +
safetyFreeboard`, processing records an explicit warning. Hydraulic area, top
width and wetted perimeter are integrated from this full geometry, including the
zero-width vertical walls, so unequal crest elevations are not reduced to a
fixed-width rectangle.

Processed state records the raw profile hash, Marker/config algorithm version,
virtual-point flags and warnings. The 1-D model builder consumes processed points
when present and falls back to raw points only for backward compatibility.

## API and UI

- `PUT /api/v1/hydraulic/cross-sections/{id}/markers`: manual Marker selection,
  lock/unlock and audit notes.
- `POST /api/v1/hydraulic/cross-sections/{id}/marker-detection`: automatic or
  explicit forced detection.
- `PUT /api/v1/hydraulic/profiles/{id}/marker-workflow`: Active Extent and
  overbank configuration plus processed-geometry rebuild.
- `POST /api/v1/hydraulic/marker-detection/batch`: bounded detection for up to
  1000 active profiles, skipping fully locked profiles by default.

The section editor displays raw, processed and virtual geometry separately,
Marker provenance/confidence/review/lock state, review-only filtering, manual
selection and lock controls, forced redetection, import-default restoration, and
the Vertical Extension warning. Dataset workflow status is independent from the
operator-controlled read-only switch. Any non-read-only version can be deleted
after confirmation; calculation, publication, derived-version and production-audit
references remain protected by database relationship gates.

## Migration and compatibility

Migration `20260908_0031` adds non-destructive workflow/config JSON and mode fields
to `hydraulic.cross_section_profile`. Historical profiles default to
`FULL_EXTENT`, `REAL_GEOMETRY`, zero freeboard and empty JSON. Existing import and
read APIs remain available. No historical raw section row is deleted and no
existing profile is automatically switched to Vertical Extension.

## Known limitations

This is a MIKE11-like engineering Marker workflow, not a claim of complete MIKE11
reimplementation. GIS-assisted levee matching and configurable survey-code
mapping are extension points, not production features in this release. Automatic
crest candidates still require survey, levee, DEM/GIS and field review on complex
reaches. Vertical Extension is a hydraulic boundary assumption and does not prove
that overtopping or floodplain inundation cannot occur.
