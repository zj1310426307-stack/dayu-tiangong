"""Deterministic MIKE11-style marker detection and processed-section geometry.

This module deliberately has no ORM or UI dependency.  Raw offset/elevation
points are immutable inputs; markers and virtual walls are derived outputs.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
import math
from typing import Any, Literal


ALGORITHM_VERSION = "dayu-marker-v1"
MarkerMode = Literal["FULL_EXTENT", "MIKE11_COMPATIBLE"]
SOURCE_PRIORITY = {
    "IMPORT_DEFAULT": 0,
    "AUTO_MIKE11_COMPATIBLE": 1,
    "SURVEY_CODE": 2,
    "GIS_LEVEE": 3,
    "MANUAL": 4,
}


@dataclass(frozen=True)
class SectionPoint:
    """Represent one immutable raw hydraulic profile point."""

    sequence: int
    offset: float
    elevation: float
    x: float | None = None
    y: float | None = None
    point_code: str | None = None


@dataclass(frozen=True)
class Marker:
    """Describe one auditable control marker without modifying its raw point."""

    type: Literal["M1", "M2", "M3"]
    role: Literal["LEFT_LEVEE", "CHANNEL_LOW_POINT", "RIGHT_LEVEE"]
    sequence: int
    offset: float
    elevation: float
    x: float | None
    y: float | None
    source: str
    confidence: float
    locked: bool
    review_status: str
    algorithm_version: str
    notes: str | None = None


@dataclass(frozen=True)
class DetectionResult:
    """Return deterministic markers together with review warnings."""

    markers: tuple[Marker, Marker, Marker] | tuple[()]
    warnings: tuple[str, ...]
    review_status: str


@dataclass(frozen=True)
class ProcessedPoint:
    """Represent one raw or virtual point used by a Solver Adapter."""

    offset: float
    elevation: float
    virtual: bool
    source_sequence: int | None


def _point_marker(point: SectionPoint, marker_type: str, role: str, source: str) -> Marker:
    """Create one marker from a raw point with traceable source metadata."""

    return Marker(
        type=marker_type,  # type: ignore[arg-type]
        role=role,  # type: ignore[arg-type]
        sequence=point.sequence,
        offset=point.offset,
        elevation=point.elevation,
        x=point.x,
        y=point.y,
        source=source,
        confidence=1.0 if source == "MANUAL" else 0.9,
        locked=False,
        review_status="REVIEWED" if source == "MANUAL" else "AUTO_ACCEPTED",
        algorithm_version=ALGORITHM_VERSION,
    )


def _middle_index(indices: list[int]) -> int:
    """Choose the deterministic centre of an equal-elevation candidate set."""

    return indices[(len(indices) - 1) // 2]


def _existing_marker(value: dict[str, Any]) -> Marker:
    """Validate a persisted marker dictionary through the dataclass contract."""

    return Marker(**{key: value.get(key) for key in Marker.__dataclass_fields__})


def detect_markers(
    points: list[SectionPoint],
    mode: MarkerMode,
    existing: dict[str, dict[str, Any]] | None = None,
    *,
    force: bool = False,
) -> DetectionResult:
    """Detect M1/M2/M3 without using global X/Y or changing raw points.

    Locked persisted markers win unless ``force`` explicitly requests a fresh
    run.  Equal minima/maxima use stable index rules so repeated processing is
    byte-for-byte deterministic.
    """

    ordered = sorted(points, key=lambda point: point.sequence)
    if len(ordered) < 3:
        return DetectionResult((), ("INSUFFICIENT_POINTS",), "NEEDS_REVIEW")
    minimum = min(point.elevation for point in ordered)
    low_indices = [
        index for index, point in enumerate(ordered)
        if math.isclose(point.elevation, minimum, abs_tol=1.0e-9)
    ]
    low_index = _middle_index(low_indices)
    left, right = ordered[:low_index], ordered[low_index + 1 :]
    warnings: list[str] = []
    if len(low_indices) > 1:
        warnings.append("MULTIPLE_LOW_POINTS")
    if not left:
        warnings.append("NO_LEFT_CANDIDATE")
    if not right:
        warnings.append("NO_RIGHT_CANDIDATE")
    if warnings and (not left or not right):
        return DetectionResult((), tuple(warnings), "NEEDS_REVIEW")

    if mode == "FULL_EXTENT":
        selected = (ordered[0], ordered[low_index], ordered[-1])
        source = "IMPORT_DEFAULT"
    else:
        left_max = max(point.elevation for point in left)
        right_max = max(point.elevation for point in right)
        left_candidates = [point for point in left if math.isclose(point.elevation, left_max)]
        right_candidates = [point for point in right if math.isclose(point.elevation, right_max)]
        # On a wide crest choose the point nearest the channel; this is stable
        # and keeps the active extent conservative.
        selected = (left_candidates[-1], ordered[low_index], right_candidates[0])
        source = "AUTO_MIKE11_COMPATIBLE"
        if len(left_candidates) > 1:
            warnings.append("MULTIPLE_LEFT_CRESTS")
        if len(right_candidates) > 1:
            warnings.append("MULTIPLE_RIGHT_CRESTS")
        if selected[0].sequence == ordered[0].sequence or selected[2].sequence == ordered[-1].sequence:
            warnings.append("CREST_AT_SECTION_BOUNDARY")
        if min(selected[0].elevation, selected[2].elevation) - minimum < 0.5:
            warnings.append("LOW_CREST_PROMINENCE")
        for candidate in (selected[0], selected[2]):
            index = ordered.index(candidate)
            neighbours = ordered[max(0, index - 1) : index] + ordered[index + 1 : index + 2]
            if neighbours and candidate.elevation - max(value.elevation for value in neighbours) > 2.0:
                warnings.append("SUSPICIOUS_SPIKE")

    roles = ("LEFT_LEVEE", "CHANNEL_LOW_POINT", "RIGHT_LEVEE")
    generated = {
        marker_type: _point_marker(point, marker_type, role, source)
        for marker_type, role, point in zip(("M1", "M2", "M3"), roles, selected)
    }
    for marker_type, value in (existing or {}).items():
        if marker_type not in generated or force:
            continue
        generated_priority = SOURCE_PRIORITY.get(generated[marker_type].source, -1)
        existing_priority = SOURCE_PRIORITY.get(str(value.get("source")), -1)
        if value.get("locked") or existing_priority > generated_priority:
            generated[marker_type] = _existing_marker(value)
    markers = (generated["M1"], generated["M2"], generated["M3"])
    if not (markers[0].sequence < markers[1].sequence < markers[2].sequence):
        warnings.append("INVALID_MARKER_ORDER")
    full_width = abs(ordered[-1].offset - ordered[0].offset)
    active_width = markers[2].offset - markers[0].offset
    if active_width <= 0 or (full_width > 0 and active_width < 0.05 * full_width):
        warnings.append("VERY_NARROW_ACTIVE_SECTION")
    if active_width > 5000.0:
        warnings.append("VERY_WIDE_ACTIVE_SECTION")
    risk_warnings = {
        "MULTIPLE_LOW_POINTS", "MULTIPLE_LEFT_CRESTS", "MULTIPLE_RIGHT_CRESTS",
        "CREST_AT_SECTION_BOUNDARY", "LOW_CREST_PROMINENCE", "SUSPICIOUS_SPIKE",
        "INVALID_MARKER_ORDER", "VERY_NARROW_ACTIVE_SECTION", "VERY_WIDE_ACTIVE_SECTION",
    }
    review = "NEEDS_REVIEW" if risk_warnings.intersection(warnings) else "AUTO_ACCEPTED"
    confidence = max(0.2, 0.9 - 0.12 * len(set(warnings)))
    markers = tuple(
        Marker(
            **{
                **asdict(marker),
                "confidence": marker.confidence if marker.locked else confidence,
                "review_status": marker.review_status if marker.locked else review,
            }
        )
        for marker in markers
    )
    return DetectionResult(markers, tuple(dict.fromkeys(warnings)), review)  # type: ignore[arg-type]


def validate_marker_order(markers: dict[str, dict[str, Any]]) -> None:
    """Reject incomplete or non-increasing control markers."""

    if not all(key in markers for key in ("M1", "M2", "M3")):
        raise ValueError("M1, M2 and M3 are all required for MARKER_EXTENT")
    if not (
        int(markers["M1"]["sequence"])
        < int(markers["M2"]["sequence"])
        < int(markers["M3"]["sequence"])
    ):
        raise ValueError("INVALID_MARKER_ORDER")


def build_processed_geometry(
    points: list[SectionPoint],
    markers: dict[str, dict[str, Any]],
    active_extent_mode: str,
    overbank_treatment: str,
    extension_top_elevation: float | None,
    design_max_water_level: float | None = None,
    safety_freeboard: float = 0.0,
) -> tuple[list[ProcessedPoint], list[str]]:
    """Build a disposable active profile and optional vertical virtual walls."""

    ordered = sorted(points, key=lambda point: point.sequence)
    if active_extent_mode == "MARKER_EXTENT":
        validate_marker_order(markers)
        first = int(markers["M1"]["sequence"])
        last = int(markers["M3"]["sequence"])
        ordered = [point for point in ordered if first <= point.sequence <= last]
    processed = [ProcessedPoint(p.offset, p.elevation, False, p.sequence) for p in ordered]
    warnings: list[str] = []
    if overbank_treatment == "VERTICAL_EXTENSION":
        validate_marker_order(markers)
        m1, m3 = markers["M1"], markers["M3"]
        if extension_top_elevation is None:
            raise ValueError("extension_top_elevation is required for VERTICAL_EXTENSION")
        if extension_top_elevation <= max(float(m1["elevation"]), float(m3["elevation"])):
            raise ValueError("extension_top_elevation must exceed both Marker crest elevations")
        if design_max_water_level is not None and extension_top_elevation < design_max_water_level + safety_freeboard:
            warnings.append("EXTENSION_BELOW_DESIGN_LEVEL_PLUS_FREEBOARD")
        # Vertical Extension is defined on M1..M3 even when the stored active
        # mode remains FULL_EXTENT; no outside raw point is deleted.
        first = int(m1["sequence"])
        last = int(m3["sequence"])
        active = [point for point in points if first <= point.sequence <= last]
        processed = [
            ProcessedPoint(float(m1["offset"]), extension_top_elevation, True, None),
            *[ProcessedPoint(p.offset, p.elevation, False, p.sequence) for p in active],
            ProcessedPoint(float(m3["offset"]), extension_top_elevation, True, None),
        ]
    return processed, warnings


def marker_dict(result: DetectionResult) -> dict[str, dict[str, Any]]:
    """Convert a detection result to JSON-safe storage form."""

    return {marker.type: asdict(marker) for marker in result.markers}
