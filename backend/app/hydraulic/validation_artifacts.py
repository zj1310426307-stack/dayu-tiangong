"""Pure HYDRO-DATA-02 artifact packaging and water-surface projection.

The functions in this module deliberately accept already-frozen JSON values.  They
do not own a database session, perform another query, write files, or infer missing
engineering facts.  Callers can therefore persist the returned byte set with one
atomic directory swap without risking a mixed-version export.
"""

from __future__ import annotations

import hashlib
import json
import math
from collections import defaultdict
from collections.abc import Mapping, Sequence
from typing import Any, Literal

from model.provenance import canonical_json, snapshot_hash


MODEL_INPUT_V3 = "dayu.model-input.v3"
MANIFEST_SCHEMA = "dayu.hydro-validation.manifest.v1"
WATER_SURFACE_SCHEMA = "dayu.water-surface.geojson.v1"

_PARTITIONS: tuple[tuple[str, tuple[str, ...]], ...] = (
    (
        "network.json",
        (
            "coordinate_reference",
            "coordinate_system",
            "networks",
            "nodes",
            "reaches",
        ),
    ),
    ("branches.json", ("branches",)),
    ("cross_sections.json", ("cross_sections",)),
    (
        "profiles.json",
        ("cross_section_profiles", "roughness_zones", "hydraulic_tables"),
    ),
    (
        "boundary.json",
        (
            "boundary_conditions",
            "parameters",
            "gates",
            "pumps",
            "controls",
            "dispatch_plan",
        ),
    ),
    (
        "provenance.json",
        (
            "dataset_version",
            "simulation_case",
            "provenance",
            "units",
            "distance_basis",
            "engine_version",
            "source_refs",
            "config_refs",
            "validation_refs",
        ),
    ),
)


class ValidationArtifactError(ValueError):
    """Reject an incomplete or internally inconsistent validation artifact."""


def _json_bytes(value: Mapping[str, Any]) -> bytes:
    """Return deterministic UTF-8 bytes whose digest describes the exact file."""

    return canonical_json(value).encode("utf-8") + b"\n"


def _sha256(content: bytes) -> str:
    """Return a lowercase SHA-256 digest for exact artifact bytes."""

    return hashlib.sha256(content).hexdigest()


def _frozen_copy(snapshot: Mapping[str, Any]) -> dict[str, Any]:
    """Normalise and detach a JSON snapshot without mutating the supplied mapping."""

    if not isinstance(snapshot, Mapping):
        raise TypeError("snapshot must be a mapping")
    try:
        copied = json.loads(canonical_json(snapshot))
    except (TypeError, ValueError) as exc:
        raise ValidationArtifactError(f"snapshot is not finite JSON: {exc}") from exc
    if not isinstance(copied, dict):
        raise ValidationArtifactError("snapshot must normalise to a JSON object")
    return copied


def _required_object(snapshot: Mapping[str, Any], key: str) -> dict[str, Any]:
    value = snapshot.get(key)
    if not isinstance(value, dict):
        raise ValidationArtifactError(f"model-input.v3 requires object field {key}")
    return value


def _required_array(snapshot: Mapping[str, Any], key: str) -> list[Any]:
    value = snapshot.get(key)
    if not isinstance(value, list):
        raise ValidationArtifactError(f"model-input.v3 requires array field {key}")
    return value


def _required_ref(value: Mapping[str, Any], key: str, label: str) -> Any:
    ref = value.get(key)
    if ref is None or isinstance(ref, (dict, list)) or str(ref).strip() == "":
        raise ValidationArtifactError(f"{label} requires a concrete {key} reference")
    return ref


def _present_fields(value: Mapping[str, Any], fields: Sequence[str]) -> dict[str, Any]:
    """Copy only facts present in the snapshot; never fill an unknown placeholder."""

    return {field: value[field] for field in fields if value.get(field) is not None}


def _reference_sort_key(value: Any) -> tuple[int, float, str]:
    """Sort numeric engineering identifiers numerically and text refs lexically."""

    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return (0, float(value), "")
    return (1, 0.0, str(value))


def _value_ref(value: Any) -> dict[str, Any]:
    """Describe one configuration value by content hash without inventing an ID."""

    encoded = canonical_json({"value": value}).encode("utf-8")
    return {"sha256": _sha256(encoded)}


def _profile_refs(snapshot: Mapping[str, Any]) -> list[dict[str, Any]]:
    refs: list[dict[str, Any]] = []
    seen_ids: set[Any] = set()
    seen_sections: set[Any] = set()
    for profile in _required_array(snapshot, "cross_section_profiles"):
        if not isinstance(profile, dict):
            raise ValidationArtifactError("cross_section_profiles must contain objects")
        profile_id = _required_ref(profile, "id", "profile")
        section_id = _required_ref(profile, "cross_section_id", f"profile {profile_id}")
        profile_hash = _required_ref(profile, "profile_hash", f"profile {profile_id}")
        if profile_id in seen_ids:
            raise ValidationArtifactError(f"duplicate profile id {profile_id}")
        if section_id in seen_sections:
            raise ValidationArtifactError(
                f"multiple active profiles reference cross section {section_id}"
            )
        seen_ids.add(profile_id)
        seen_sections.add(section_id)
        refs.append(
            _present_fields(
                profile,
                (
                    "id",
                    "cross_section_id",
                    "branch_id",
                    "section_code",
                    "profile_hash",
                    "topography_id",
                ),
            )
        )
    return sorted(
        refs,
        key=lambda item: (
            _reference_sort_key(item.get("branch_id")),
            _reference_sort_key(item["id"]),
        ),
    )


def _source_refs(snapshot: Mapping[str, Any]) -> dict[str, Any]:
    branches = _required_array(snapshot, "branches")
    profiles = _required_array(snapshot, "cross_section_profiles")
    result: dict[str, Any] = {}
    declared = snapshot.get("source_refs")
    if declared is not None:
        result["declared"] = declared
    revisions = [
        _present_fields(branch, ("id", "branch_code", "source_revision"))
        for branch in branches
        if isinstance(branch, dict) and branch.get("source_revision") is not None
    ]
    if revisions:
        result["branch_revisions"] = revisions
    surveys = [
        _present_fields(
            profile,
            (
                "id",
                "cross_section_id",
                "topography_id",
                "survey_date",
                "survey_method",
                "vertical_datum",
            ),
        )
        for profile in profiles
        if isinstance(profile, dict)
        and any(
            profile.get(key) is not None
            for key in ("topography_id", "survey_date", "survey_method", "vertical_datum")
        )
    ]
    if surveys:
        result["profile_surveys"] = surveys
    coordinate_reference = snapshot.get("coordinate_reference")
    if coordinate_reference is not None:
        result["coordinate_reference"] = _value_ref(coordinate_reference)
    return result


def _config_refs(snapshot: Mapping[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    declared = snapshot.get("config_refs")
    if declared is not None:
        result["declared"] = declared
    if snapshot.get("engine_version") is not None:
        result["engine_version"] = snapshot["engine_version"]
    for key in ("controls", "parameters", "dispatch_plan", "boundary_conditions"):
        if key in snapshot:
            result[key] = _value_ref(snapshot[key])
    return result


def _validation_refs(snapshot: Mapping[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    declared = snapshot.get("validation_refs")
    if declared is not None:
        result["declared"] = declared
    branch_refs = [
        _present_fields(branch, ("id", "branch_code", "direction_status"))
        for branch in _required_array(snapshot, "branches")
        if isinstance(branch, dict)
    ]
    section_refs = [
        _present_fields(
            section,
            (
                "id",
                "section_code",
                "branch_id",
                "chainage_source",
                "snap_distance_m",
                "orientation_status",
                "active_profile_id",
            ),
        )
        for section in _required_array(snapshot, "cross_sections")
        if isinstance(section, dict)
    ]
    profile_processing = []
    for profile in _required_array(snapshot, "cross_section_profiles"):
        if not isinstance(profile, dict):
            continue
        item = _present_fields(profile, ("id", "profile_hash"))
        processing = profile.get("processing")
        if isinstance(processing, dict):
            item["processing"] = _present_fields(
                processing,
                ("id", "processor_version", "vertical_step_m"),
            )
        profile_processing.append(item)
    result["branches"] = branch_refs
    result["cross_sections"] = section_refs
    result["profiles"] = profile_processing
    return result


def _manifest_refs(snapshot: Mapping[str, Any]) -> dict[str, Any]:
    dataset = _required_object(snapshot, "dataset_version")
    case = _required_object(snapshot, "simulation_case")
    dataset_id = _required_ref(dataset, "id", "dataset_version")
    case_id = _required_ref(case, "id", "simulation_case")
    case_dataset_id = case.get("dataset_version_id")
    if case_dataset_id is not None and case_dataset_id != dataset_id:
        raise ValidationArtifactError(
            "simulation_case.dataset_version_id does not match dataset_version.id"
        )
    return {
        "schema": {"schema_version": snapshot["schema_version"]},
        "dataset": _present_fields(
            dataset,
            ("id", "version", "version_code", "name", "source_batch_id"),
        ),
        "case": _present_fields(
            case,
            ("id", "case_code", "name", "dataset_version_id"),
        ),
        "profiles": _profile_refs(snapshot),
        "source": _source_refs(snapshot),
        "config": _config_refs(snapshot),
        "validation": _validation_refs(snapshot),
    }


def build_model_input_v3_artifact_bundle(
    snapshot: Mapping[str, Any],
) -> dict[str, Any]:
    """Build all HYDRO-DATA-02 JSON bytes and their manifest from one snapshot.

    The return value is all-or-nothing: ``files`` is populated only after the
    snapshot, cross references, JSON serialisation, and every digest succeed.
    ``manifest.json`` does not recursively hash itself; its detached digest is
    returned as ``manifest_sha256``.
    """

    frozen = _frozen_copy(snapshot)
    if frozen.get("schema_version") != MODEL_INPUT_V3:
        raise ValidationArtifactError(
            f"artifact bundle requires schema_version {MODEL_INPUT_V3}"
        )
    for key in (
        "networks",
        "nodes",
        "branches",
        "reaches",
        "cross_sections",
        "cross_section_profiles",
        "roughness_zones",
        "hydraulic_tables",
        "boundary_conditions",
        "parameters",
        "gates",
        "pumps",
    ):
        _required_array(frozen, key)
    for key in (
        "dataset_version",
        "simulation_case",
        "coordinate_reference",
        "controls",
        "units",
        "provenance",
    ):
        _required_object(frozen, key)
    _required_ref(frozen, "engine_version", "model-input.v3")
    _required_ref(frozen, "distance_basis", "model-input.v3")
    if len(frozen["networks"]) != 1:
        raise ValidationArtifactError("model-input.v3 artifact requires exactly one network")

    assigned_keys = {"schema_version"}
    component_payloads: list[tuple[str, dict[str, Any], tuple[str, ...]]] = []
    for filename, keys in _PARTITIONS:
        data = {key: frozen[key] for key in keys if key in frozen}
        assigned_keys.update(data)
        component_payloads.append(
            (
                filename,
                {
                    "source_schema_version": MODEL_INPUT_V3,
                    "artifact_kind": filename.removesuffix(".json"),
                    **data,
                },
                tuple(data),
            )
        )

    extra_keys = tuple(sorted(set(frozen) - assigned_keys))
    if extra_keys:
        for index, (filename, payload, keys) in enumerate(component_payloads):
            if filename == "provenance.json":
                payload["unassigned_snapshot_fields"] = {
                    key: frozen[key] for key in extra_keys
                }
                component_payloads[index] = (
                    filename,
                    payload,
                    (*keys, *extra_keys),
                )
                break

    payload_files: dict[str, bytes] = {}
    file_rows: list[dict[str, Any]] = []
    for filename, payload, keys in component_payloads:
        content = _json_bytes(payload)
        payload_files[filename] = content
        file_rows.append(
            {
                "name": filename,
                "media_type": "application/json",
                "bytes": len(content),
                "sha256": _sha256(content),
                "snapshot_fields": list(keys),
            }
        )

    manifest = {
        "schema_version": MANIFEST_SCHEMA,
        "source_schema_version": MODEL_INPUT_V3,
        "snapshot_sha256": snapshot_hash(frozen),
        "files": file_rows,
        "refs": _manifest_refs(frozen),
    }
    manifest_content = _json_bytes(manifest)
    files = {**payload_files, "manifest.json": manifest_content}
    return {
        "files": files,
        "manifest": manifest,
        "manifest_sha256": _sha256(manifest_content),
    }


def _finite_number(value: Any, label: str) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ValidationArtifactError(f"{label} must be numeric") from exc
    if not math.isfinite(number):
        raise ValidationArtifactError(f"{label} must be finite")
    return number


def _select_series_value(
    row: Mapping[str, Any], time_seconds: float
) -> dict[str, Any] | None:
    times = row.get("time")
    if not isinstance(times, list):
        raise ValidationArtifactError("section result series requires a time array")
    matches = [
        index
        for index, value in enumerate(times)
        if math.isclose(
            _finite_number(value, "result time"),
            time_seconds,
            rel_tol=0.0,
            abs_tol=1.0e-6,
        )
    ]
    if not matches:
        return None
    if len(matches) != 1:
        raise ValidationArtifactError("section result contains duplicate requested times")
    index = matches[0]
    selected = dict(row)
    selected["time_seconds"] = time_seconds
    for key in ("water_level", "flow", "velocity"):
        values = row.get(key)
        if not isinstance(values, list) or len(values) != len(times):
            raise ValidationArtifactError(f"section result {key} must align with time")
        selected[key] = _finite_number(values[index], f"result {key}")
    return selected


def _normalise_result_rows(
    results: Mapping[str, Any] | Sequence[Mapping[str, Any]],
    time_seconds: float,
) -> list[dict[str, Any]]:
    if isinstance(results, Mapping):
        rows = results.get("section_series", results.get("series"))
        if not isinstance(rows, list):
            raise ValidationArtifactError(
                "result object requires section_series or series array"
            )
        selected = []
        for row in rows:
            if not isinstance(row, Mapping):
                raise ValidationArtifactError("section result series must contain objects")
            value = _select_series_value(row, time_seconds)
            if value is not None:
                selected.append(value)
    elif isinstance(results, Sequence) and not isinstance(
        results, (str, bytes, bytearray)
    ):
        selected = []
        for row in results:
            if not isinstance(row, Mapping):
                raise ValidationArtifactError("flat result rows must be objects")
            row_time = _finite_number(row.get("time_seconds"), "result time_seconds")
            if not math.isclose(row_time, time_seconds, rel_tol=0.0, abs_tol=1.0e-6):
                continue
            item = dict(row)
            for key in ("water_level", "flow", "velocity"):
                item[key] = _finite_number(item.get(key), f"result {key}")
            selected.append(item)
    else:
        raise TypeError("results must be a result mapping or a sequence of flat rows")
    if not selected:
        raise ValidationArtifactError(
            f"result has no section values at time_seconds={time_seconds:g}"
        )
    return selected


def _point_coordinates(value: Any) -> list[float] | None:
    if value is None:
        return None
    if not isinstance(value, Mapping) or value.get("type") != "Point":
        return None
    coordinates = value.get("coordinates")
    if not isinstance(coordinates, list) or len(coordinates) < 2:
        return None
    try:
        return [
            _finite_number(coordinates[0], "location x"),
            _finite_number(coordinates[1], "location y"),
        ]
    except ValidationArtifactError:
        return None


def build_water_surface_geojson(
    snapshot: Mapping[str, Any],
    task: Mapping[str, Any],
    results: Mapping[str, Any] | Sequence[Mapping[str, Any]],
    *,
    time_seconds: float,
    missing_location: Literal["exclude", "error"] = "exclude",
) -> dict[str, Any]:
    """Project one successful task time slice to section points and adjacent lines.

    No polygon or buffer is generated.  Missing/invalid section locations either
    fail the whole projection or remain visible in the top-level ``excluded`` list.
    A gap is never bridged by connecting the sections on opposite sides of it.
    """

    frozen = _frozen_copy(snapshot)
    if frozen.get("schema_version") != MODEL_INPUT_V3:
        raise ValidationArtifactError(
            f"water surface requires schema_version {MODEL_INPUT_V3}"
        )
    if not isinstance(task, Mapping):
        raise TypeError("task must be a mapping")
    if task.get("status") != "success":
        raise ValidationArtifactError("water surface requires a successful task")
    task_id = _required_ref(task, "id", "task")
    if task.get("input_schema_version") not in {None, MODEL_INPUT_V3}:
        raise ValidationArtifactError("task input_schema_version is not dayu.model-input.v3")
    if missing_location not in {"exclude", "error"}:
        raise ValidationArtifactError("missing_location must be exclude or error")
    requested_time = _finite_number(time_seconds, "time_seconds")

    dataset = _required_object(frozen, "dataset_version")
    dataset_id = _required_ref(dataset, "id", "dataset_version")
    case = _required_object(frozen, "simulation_case")
    case_id = _required_ref(case, "id", "simulation_case")
    if task.get("case_id") is not None and task["case_id"] != case_id:
        raise ValidationArtifactError("task case_id does not match snapshot")
    task_snapshot_hash = task.get("input_snapshot_hash")
    actual_snapshot_hash = snapshot_hash(frozen)
    if task_snapshot_hash is not None and task_snapshot_hash != actual_snapshot_hash:
        raise ValidationArtifactError("task input_snapshot_hash does not match snapshot")

    branches_by_id: dict[Any, dict[str, Any]] = {}
    legacy_branch_ids: dict[Any, Any] = {}
    for branch in _required_array(frozen, "branches"):
        if not isinstance(branch, dict):
            raise ValidationArtifactError("branches must contain objects")
        branch_id = _required_ref(branch, "id", "branch")
        _required_ref(branch, "branch_code", f"branch {branch_id}")
        if branch_id in branches_by_id:
            raise ValidationArtifactError(f"duplicate branch id {branch_id}")
        branches_by_id[branch_id] = branch
        legacy_branch_ids[branch_id] = branch.get("legacy_river_id") or branch_id

    profiles_by_section: dict[Any, dict[str, Any]] = {}
    for profile in _required_array(frozen, "cross_section_profiles"):
        if not isinstance(profile, dict):
            raise ValidationArtifactError("cross_section_profiles must contain objects")
        section_id = _required_ref(profile, "cross_section_id", "profile")
        _required_ref(profile, "profile_hash", f"profile for section {section_id}")
        if section_id in profiles_by_section:
            raise ValidationArtifactError(
                f"multiple active profiles reference cross section {section_id}"
            )
        profiles_by_section[section_id] = profile

    sections_by_id: dict[Any, dict[str, Any]] = {}
    sections_by_code: dict[str, dict[str, Any]] = {}
    duplicate_codes: set[str] = set()
    for section in _required_array(frozen, "cross_sections"):
        if not isinstance(section, dict):
            raise ValidationArtifactError("cross_sections must contain objects")
        section_id = _required_ref(section, "id", "cross section")
        section_code = str(_required_ref(section, "section_code", f"section {section_id}"))
        if section_id in sections_by_id:
            raise ValidationArtifactError(f"duplicate cross section id {section_id}")
        sections_by_id[section_id] = section
        if section_code in sections_by_code:
            duplicate_codes.add(section_code)
        else:
            sections_by_code[section_code] = section

    selected_rows = _normalise_result_rows(results, requested_time)
    grouped: defaultdict[Any, list[dict[str, Any]]] = defaultdict(list)
    seen_sections: set[Any] = set()
    for row in selected_rows:
        if row.get("task_id") is not None and row["task_id"] != task_id:
            raise ValidationArtifactError("result task_id does not match task")
        section = None
        section_id = row.get("section_id")
        if section_id is not None:
            section = sections_by_id.get(section_id)
        if section is None and row.get("section_code") is not None:
            section_code = str(row["section_code"])
            if section_code in duplicate_codes:
                raise ValidationArtifactError(
                    f"result section_code {section_code} is not unique"
                )
            section = sections_by_code.get(section_code)
        if section is None:
            raise ValidationArtifactError("result references an unknown cross section")
        section_id = section["id"]
        if section_id in seen_sections:
            raise ValidationArtifactError(
                f"duplicate result for cross section {section_id} at requested time"
            )
        seen_sections.add(section_id)
        branch_id = _required_ref(section, "branch_id", f"section {section_id}")
        if branch_id not in branches_by_id:
            raise ValidationArtifactError(
                f"section {section_id} references unknown branch {branch_id}"
            )
        result_branch_id = row.get("river_id", row.get("branch_id"))
        if result_branch_id is not None and result_branch_id not in {
            branch_id,
            legacy_branch_ids[branch_id],
        }:
            raise ValidationArtifactError(
                f"result branch for section {section_id} does not match snapshot"
            )
        chainage = _finite_number(section.get("chainage_m"), f"section {section_id} chainage")
        result_chainage = row.get("station", row.get("chainage_m"))
        if result_chainage is not None and not math.isclose(
            _finite_number(result_chainage, "result chainage"),
            chainage,
            rel_tol=0.0,
            abs_tol=1.0e-6,
        ):
            raise ValidationArtifactError(
                f"result chainage for section {section_id} does not match snapshot"
            )
        profile = profiles_by_section.get(section_id)
        if profile is None:
            raise ValidationArtifactError(
                f"section {section_id} has no frozen active profile"
            )
        grouped[branch_id].append(
            {
                "section": section,
                "profile": profile,
                "row": row,
                "chainage_m": chainage,
                "coordinates": _point_coordinates(section.get("location")),
            }
        )

    point_features: list[dict[str, Any]] = []
    segment_features: list[dict[str, Any]] = []
    excluded: list[dict[str, Any]] = []
    profile_hashes: set[str] = set()
    for branch_id in sorted(grouped, key=_reference_sort_key):
        branch = branches_by_id[branch_id]
        ordered = sorted(
            grouped[branch_id],
            key=lambda item: (item["chainage_m"], str(item["section"]["id"])),
        )
        if any(
            math.isclose(left["chainage_m"], right["chainage_m"], abs_tol=1.0e-9)
            for left, right in zip(ordered, ordered[1:])
        ):
            raise ValidationArtifactError(
                f"branch {branch_id} contains duplicate result chainage"
            )
        for item in ordered:
            section = item["section"]
            row = item["row"]
            profile_hash = str(item["profile"]["profile_hash"])
            profile_hashes.add(profile_hash)
            common = {
                "task_id": task_id,
                "time_seconds": requested_time,
                "dataset_version_id": dataset_id,
                "profile_hash": profile_hash,
                "branch_id": branch_id,
                "branch_code": branch.get("branch_code"),
                "section_id": section["id"],
                "section_code": section["section_code"],
                "chainage_m": item["chainage_m"],
            }
            if item["coordinates"] is None:
                record = {**common, "reason": "missing_or_invalid_point_location"}
                if missing_location == "error":
                    raise ValidationArtifactError(
                        f"section {section['id']} has no valid Point location"
                    )
                excluded.append(record)
                continue
            point_features.append(
                {
                    "type": "Feature",
                    "id": f"section:{section['id']}",
                    "geometry": {"type": "Point", "coordinates": item["coordinates"]},
                    "properties": {
                        **common,
                        "feature_kind": "cross_section",
                        "water_level": row["water_level"],
                        "flow": row["flow"],
                        "velocity": row["velocity"],
                    },
                }
            )
        for upstream, downstream in zip(ordered, ordered[1:]):
            if upstream["coordinates"] is None or downstream["coordinates"] is None:
                continue
            upstream_section = upstream["section"]
            downstream_section = downstream["section"]
            upstream_row = upstream["row"]
            downstream_row = downstream["row"]
            upstream_hash = str(upstream["profile"]["profile_hash"])
            downstream_hash = str(downstream["profile"]["profile_hash"])
            segment_features.append(
                {
                    "type": "Feature",
                    "id": (
                        f"segment:{branch_id}:"
                        f"{upstream_section['id']}:{downstream_section['id']}"
                    ),
                    "geometry": {
                        "type": "LineString",
                        "coordinates": [
                            upstream["coordinates"],
                            downstream["coordinates"],
                        ],
                    },
                    "properties": {
                        "feature_kind": "adjacent_cross_section_segment",
                        "task_id": task_id,
                        "time_seconds": requested_time,
                        "dataset_version_id": dataset_id,
                        "branch_id": branch_id,
                        "branch_code": branch.get("branch_code"),
                        "start_section_id": upstream_section["id"],
                        "end_section_id": downstream_section["id"],
                        "start_chainage_m": upstream["chainage_m"],
                        "end_chainage_m": downstream["chainage_m"],
                        "start_profile_hash": upstream_hash,
                        "end_profile_hash": downstream_hash,
                        "profile_hashes": [upstream_hash, downstream_hash],
                        "start_water_level": upstream_row["water_level"],
                        "end_water_level": downstream_row["water_level"],
                        "start_flow": upstream_row["flow"],
                        "end_flow": downstream_row["flow"],
                        "start_velocity": upstream_row["velocity"],
                        "end_velocity": downstream_row["velocity"],
                    },
                }
            )

    return {
        "type": "FeatureCollection",
        "schema_version": WATER_SURFACE_SCHEMA,
        "metadata": {
            "task_id": task_id,
            "time_seconds": requested_time,
            "dataset_version_id": dataset_id,
            "input_snapshot_hash": actual_snapshot_hash,
            "profile_hashes": sorted(profile_hashes),
            "coordinate_reference": frozen.get("coordinate_reference"),
            "point_count": len(point_features),
            "segment_count": len(segment_features),
            "excluded_count": len(excluded),
            "risk_extent_generated": False,
        },
        "features": [*point_features, *segment_features],
        "excluded": excluded,
    }


__all__ = [
    "ValidationArtifactError",
    "build_model_input_v3_artifact_bundle",
    "build_water_surface_geojson",
]
