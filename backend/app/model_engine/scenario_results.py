"""Read locally published scenario-result bundles from governed runtime storage."""

from __future__ import annotations

from hashlib import sha256
from json import JSONDecodeError, loads
from pathlib import Path
from re import fullmatch

from pydantic import ValidationError

from app.files import resolve_within, storage_directory
from app.model_engine.schemas import PublishedScenarioBundle


SCENARIO_RESULT_ROOT = storage_directory("scenario-results")
MAX_MANIFEST_BYTES = 5 * 1024 * 1024


class ScenarioResultBundleError(ValueError):
    """Report an invalid local result bundle without exposing arbitrary files."""


def _validate_section_axes(bundle: PublishedScenarioBundle) -> None:
    """Require every scenario to share one strictly downstream Section axis."""

    scenario_ids = [item.scenario_id for item in bundle.scenarios]
    if len(scenario_ids) != len(set(scenario_ids)):
        raise ScenarioResultBundleError("scenario ids must be unique")
    reference = [
        (item.cross_section_id, float(item.chainage_m))
        for item in bundle.scenarios[0].section_summary
    ]
    for scenario in bundle.scenarios:
        axis = [
            (item.cross_section_id, float(item.chainage_m))
            for item in scenario.section_summary
        ]
        if any(right[1] <= left[1] for left, right in zip(axis, axis[1:])):
            raise ScenarioResultBundleError(
                f"{scenario.scenario_id} Section chainage must increase downstream"
            )
        if axis != reference:
            raise ScenarioResultBundleError("all scenarios must share one Section axis")


def _load_manifest(manifest: Path, root: Path) -> PublishedScenarioBundle:
    """Load one bounded UTF-8 manifest and attach its content digest."""

    safe_manifest = resolve_within(root, manifest.parent.name, "manifest.json")
    if safe_manifest != manifest.resolve() or safe_manifest.is_symlink():
        raise ScenarioResultBundleError("scenario result manifest path is unsafe")
    size = safe_manifest.stat().st_size
    if size <= 0 or size > MAX_MANIFEST_BYTES:
        raise ScenarioResultBundleError("scenario result manifest size is invalid")
    content = safe_manifest.read_bytes()
    try:
        payload = loads(content.decode("utf-8"))
        bundle = PublishedScenarioBundle.model_validate(payload)
    except (UnicodeDecodeError, JSONDecodeError, ValidationError) as exc:
        raise ScenarioResultBundleError(f"invalid scenario result manifest: {safe_manifest}") from exc
    if bundle.bundle_id != manifest.parent.name:
        raise ScenarioResultBundleError("bundle_id must match its storage directory")
    if bundle.classification != "UNCALIBRATED_SCENARIO_CALCULATION":
        raise ScenarioResultBundleError("only explicitly uncalibrated scenario bundles are supported")
    if not all(item.quality_gate.passed for item in bundle.scenarios):
        raise ScenarioResultBundleError("published scenario bundle contains a failed quality gate")
    _validate_section_axes(bundle)
    return bundle.model_copy(update={"source_digest": sha256(content).hexdigest()})


def list_published_scenario_results(
    root: Path | None = None,
) -> list[PublishedScenarioBundle]:
    """Return all valid result manifests in newest-first order."""

    result_root = (root or SCENARIO_RESULT_ROOT).resolve()
    if not result_root.exists():
        return []
    if not result_root.is_dir():
        raise ScenarioResultBundleError("scenario result root must be a directory")
    manifests = sorted(result_root.glob("*/manifest.json"), reverse=True)
    return sorted(
        (_load_manifest(item.resolve(), result_root) for item in manifests),
        key=lambda item: item.generated_at,
        reverse=True,
    )


def published_scenario_geojson(
    bundle_id: str,
    scenario_id: str | None = None,
    root: Path | None = None,
) -> dict[str, object]:
    """Return the governed engineering CRS overlay for the selected scenario."""

    result_root = (root or SCENARIO_RESULT_ROOT).resolve()
    bundle_root = resolve_within(result_root, bundle_id)
    manifest = resolve_within(bundle_root, "manifest.json")
    bundle = _load_manifest(manifest, result_root)
    selected = bundle.scenarios[0] if scenario_id is None else next(
        (item for item in bundle.scenarios if item.scenario_id == scenario_id), None
    )
    if selected is None:
        raise ScenarioResultBundleError("requested scenario does not exist")
    spatial_path = resolve_within(bundle_root, "spatial.geojson")
    if not spatial_path.is_file() or spatial_path.stat().st_size > MAX_MANIFEST_BYTES:
        raise ScenarioResultBundleError("scenario spatial overlay is missing or too large")
    try:
        overlay = loads(spatial_path.read_text(encoding="utf-8"))
    except (UnicodeDecodeError, JSONDecodeError) as exc:
        raise ScenarioResultBundleError("scenario spatial overlay is invalid") from exc
    if overlay.get("type") != "FeatureCollection" or not isinstance(overlay.get("features"), list):
        raise ScenarioResultBundleError("scenario spatial overlay must be a FeatureCollection")
    by_section = {item.cross_section_id: item for item in selected.section_summary}
    features: list[dict[str, object]] = []
    for feature in overlay["features"]:
        if not isinstance(feature, dict):
            continue
        properties = dict(feature.get("properties") or {})
        section_id = properties.get("cross_section_id")
        if section_id in by_section:
            result = by_section[section_id]
            properties.update({
                "scenario_id": selected.scenario_id,
                "scenario_label": selected.label,
                "water_level_m": result.final_water_level_m,
                "depth_m": result.final_depth_m,
                "discharge_m3s": result.final_discharge_m3s,
                "velocity_m_s": result.final_velocity_ms,
                "bed_min_m": result.bed_min_m,
                "flow_area_m2": result.flow_area_m2,
            })
        features.append({**feature, "properties": properties})
    return {
        "type": "FeatureCollection",
        "name": bundle.bundle_id,
        "scenario_id": selected.scenario_id,
        "scenario_label": selected.label,
        "source_crs": "EPSG:4547",
        "display_crs": "EPSG:4490",
        "features": features,
    }


ALLOWED_CASE_ARTIFACTS = {
    "manifest.json",
    "case_manifest.json",
    "spatial.geojson",
    "01_river_database_import_gaominghe_EPSG4547.xlsx",
    "02_cross_section_database_import_gaominghe_1985_Marker1-3.xlsx",
    "03_normalized_payload.json",
    "04_network.nwk11",
    "05_cross_sections.xns11",
}


def _bundle_root(bundle_id: str, root: Path | None = None) -> Path:
    """Resolve one governed bundle directory after validating its manifest."""

    if fullmatch(r"[a-z0-9][a-z0-9-]{2,63}", bundle_id) is None:
        raise ScenarioResultBundleError("invalid scenario bundle id")
    result_root = (root or SCENARIO_RESULT_ROOT).resolve()
    bundle_root = resolve_within(result_root, bundle_id)
    _load_manifest(resolve_within(bundle_root, "manifest.json"), result_root)
    return bundle_root


def published_case_manifest(bundle_id: str, root: Path | None = None) -> dict[str, object]:
    """Return the auditable step index for the published engineering case."""

    case_path = resolve_within(_bundle_root(bundle_id, root), "case_manifest.json")
    if not case_path.is_file() or case_path.stat().st_size > MAX_MANIFEST_BYTES:
        raise ScenarioResultBundleError("case manifest is missing or too large")
    try:
        payload = loads(case_path.read_text(encoding="utf-8"))
    except (UnicodeDecodeError, JSONDecodeError) as exc:
        raise ScenarioResultBundleError("case manifest is invalid") from exc
    if not isinstance(payload, dict) or not isinstance(payload.get("steps"), list):
        raise ScenarioResultBundleError("case manifest has no step index")
    return payload


def published_case_artifact(bundle_id: str, filename: str, root: Path | None = None) -> Path:
    """Resolve one allow-listed case file for a browser download."""

    if filename not in ALLOWED_CASE_ARTIFACTS:
        raise ScenarioResultBundleError("case artifact is not allow-listed")
    path = resolve_within(_bundle_root(bundle_id, root), filename)
    if not path.is_file() or path.is_symlink():
        raise ScenarioResultBundleError("case artifact does not exist")
    return path


__all__ = [
    "MAX_MANIFEST_BYTES",
    "SCENARIO_RESULT_ROOT",
    "ScenarioResultBundleError",
    "list_published_scenario_results",
    "published_scenario_geojson",
    "published_case_manifest",
    "published_case_artifact",
]
