"""Read locally published scenario-result bundles from governed runtime storage."""

from __future__ import annotations

from hashlib import sha256
from json import JSONDecodeError, loads
from pathlib import Path

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


__all__ = [
    "MAX_MANIFEST_BYTES",
    "SCENARIO_RESULT_ROOT",
    "ScenarioResultBundleError",
    "list_published_scenario_results",
]
