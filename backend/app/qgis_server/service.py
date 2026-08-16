"""Validate browser WMS parameters and proxy only synthesized QGIS requests."""

from __future__ import annotations

import json
import os
from pathlib import Path
import re
from typing import Any

import httpx
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.gis.models import DatasetVersion, GISLayerRegistry
from app.gis_governance.errors import GovernanceError
from app.qgis_server.schemas import HealthEvidence, QgisServerHealthResponse


ALLOWED_PUBLIC_PARAMETERS = {
    "request", "dataset_version_id", "layer_key", "layer_keys", "bbox",
    "width", "height", "crs", "format", "transparent", "i", "j",
    "feature_count", "template",
}
ALLOWED_REQUESTS = {
    "getcapabilities": "GetCapabilities",
    "getmap": "GetMap",
    "getfeatureinfo": "GetFeatureInfo",
    "getlegendgraphic": "GetLegendGraphic",
}
IDENTIFIER = re.compile(r"^[a-z][a-z0-9_]{1,62}$")
MAX_DIMENSION = 4096
MAX_PIXELS = 16_777_216
MANIFEST_SCHEMA = "dayu-qgis-server-manifest/v1alpha1"
ISOLATION_EVIDENCE_SCHEMA = "dayu-qgis-isolation-evidence/v1alpha1"


def _error(code: str, message: str, *, status_code: int = 422, **context: Any) -> GovernanceError:
    return GovernanceError(code, message, status_code=status_code, context=context)


def _published_version(session: Session, dataset_version_id: int) -> DatasetVersion:
    version = session.get(DatasetVersion, dataset_version_id)
    if version is None:
        raise _error("DATASET_VERSION_NOT_FOUND", "Dataset version does not exist.", status_code=404, dataset_version_id=dataset_version_id)
    if version.status == "retired":
        raise _error("DATASET_VERSION_RETIRED", "Dataset version is retired.", status_code=410, dataset_version_id=dataset_version_id)
    if version.status != "published" or not version.content_hash:
        raise _error("DATASET_VERSION_NOT_PUBLIC", "Dataset version is not publicly available.", status_code=409, dataset_version_id=dataset_version_id, status=version.status)
    return version


def _layers(session: Session, layer_keys: list[str]) -> list[GISLayerRegistry]:
    if not layer_keys or any(not IDENTIFIER.fullmatch(key) for key in layer_keys):
        raise _error("QGIS_LAYER_REQUIRED", "At least one safe layer_key is required.")
    if len(layer_keys) != len(set(layer_keys)):
        raise _error("QGIS_LAYER_DUPLICATE", "layer_key values must be unique.")
    rows = list(
        session.scalars(
            select(GISLayerRegistry).where(
                GISLayerRegistry.layer_key.in_(layer_keys),
                GISLayerRegistry.active.is_(True),
                GISLayerRegistry.service_mode == "QGIS_WMS",
                GISLayerRegistry.render_mode == "RASTER_WMS",
                GISLayerRegistry.source_schema == "publish",
                GISLayerRegistry.dataset_filter_field == "dataset_version_id",
            )
        ).all()
    )
    by_key = {row.layer_key: row for row in rows}
    unknown = [key for key in layer_keys if key not in by_key]
    if unknown:
        raise _error("QGIS_LAYER_NOT_ALLOWED", "One or more layers are not in the QGIS WMS allow-list.", layer_keys=unknown)
    return [by_key[key] for key in layer_keys]


def _positive_int(value: str | None, field: str, *, maximum: int) -> int:
    try:
        parsed = int(value or "")
    except ValueError as exc:
        raise _error("QGIS_PARAMETER_INVALID", f"{field} must be an integer.", field=field) from exc
    if parsed < 0 or parsed > maximum:
        raise _error("QGIS_PARAMETER_INVALID", f"{field} is outside the allowed range.", field=field)
    return parsed


def _bbox(value: str | None) -> str:
    try:
        numbers = [float(item) for item in (value or "").split(",")]
    except ValueError as exc:
        raise _error("QGIS_BBOX_INVALID", "bbox must contain four finite numbers.") from exc
    if len(numbers) != 4 or any(number != number or abs(number) == float("inf") for number in numbers):
        raise _error("QGIS_BBOX_INVALID", "bbox must contain four finite numbers.")
    if numbers[0] >= numbers[2] or numbers[1] >= numbers[3]:
        raise _error("QGIS_BBOX_INVALID", "bbox minimums must be below maximums.")
    return ",".join(format(number, ".15g") for number in numbers)


def build_upstream_parameters(session: Session, public: dict[str, str]) -> dict[str, str]:
    """Build a closed upstream parameter set; raw MAP/FILTER/vendor input never passes."""

    unknown = sorted(set(public) - ALLOWED_PUBLIC_PARAMETERS)
    if unknown:
        raise _error("QGIS_PARAMETER_NOT_ALLOWED", "Unknown or unsafe QGIS parameter.", parameters=unknown)
    request_name = ALLOWED_REQUESTS.get(public.get("request", "").lower())
    if request_name is None:
        raise _error("QGIS_REQUEST_NOT_ALLOWED", "The requested QGIS operation is not allowed.")
    upstream = {"SERVICE": "WMS", "VERSION": "1.3.0", "REQUEST": request_name}
    if request_name == "GetCapabilities":
        return upstream

    dataset_version_id = _positive_int(public.get("dataset_version_id"), "dataset_version_id", maximum=2_147_483_647)
    if dataset_version_id == 0:
        raise _error("QGIS_PARAMETER_INVALID", "dataset_version_id must be positive.")
    _published_version(session, dataset_version_id)
    raw_keys = public.get("layer_keys") or public.get("layer_key") or ""
    layer_keys = [item.strip() for item in raw_keys.split(",") if item.strip()]
    rows = _layers(session, layer_keys)
    short_names = [str(row.qgis_short_name) for row in rows]
    upstream["LAYERS"] = ",".join(short_names)
    upstream["FILTER"] = ";".join(
        f'{short_name}:"dataset_version_id" = {dataset_version_id}'
        for short_name in short_names
    )

    if request_name in {"GetMap", "GetFeatureInfo"}:
        width = _positive_int(public.get("width"), "width", maximum=MAX_DIMENSION)
        height = _positive_int(public.get("height"), "height", maximum=MAX_DIMENSION)
        if width == 0 or height == 0 or width * height > MAX_PIXELS:
            raise _error("QGIS_IMAGE_SIZE_INVALID", "Requested image dimensions exceed the platform limit.")
        crs = public.get("crs", "EPSG:4490").upper()
        if crs not in {"EPSG:4490", "EPSG:3857"}:
            raise _error("QGIS_CRS_NOT_ALLOWED", "crs is outside the platform allow-list.", crs=crs)
        image_format = public.get("format", "image/png").lower()
        if image_format not in {"image/png", "image/jpeg"}:
            raise _error("QGIS_FORMAT_NOT_ALLOWED", "format is outside the platform allow-list.")
        bbox = _bbox(public.get("bbox"))
        if crs == "EPSG:4490":
            # The browser-facing contract is always west,south,east,north.
            # WMS 1.3.0 follows the EPSG axis order for geographic CRS 4490,
            # so QGIS Server must receive south,west,north,east instead.
            west, south, east, north = bbox.split(",")
            bbox = ",".join((south, west, north, east))
        upstream.update({"BBOX": bbox, "WIDTH": str(width), "HEIGHT": str(height), "CRS": crs, "FORMAT": image_format, "TRANSPARENT": "TRUE" if public.get("transparent", "true").lower() == "true" else "FALSE"})
    if request_name == "GetFeatureInfo":
        upstream["QUERY_LAYERS"] = ",".join(short_names)
        pixel_i = _positive_int(public.get("i"), "i", maximum=MAX_DIMENSION)
        pixel_j = _positive_int(public.get("j"), "j", maximum=MAX_DIMENSION)
        if pixel_i >= width or pixel_j >= height:
            raise _error(
                "QGIS_PIXEL_INVALID",
                "FeatureInfo pixel must be inside the requested image.",
            )
        upstream["I"] = str(pixel_i)
        upstream["J"] = str(pixel_j)
        upstream["FEATURE_COUNT"] = str(_positive_int(public.get("feature_count", "5"), "feature_count", maximum=20))
        upstream["INFO_FORMAT"] = "application/json"
    if request_name == "GetLegendGraphic":
        if len(short_names) != 1:
            raise _error("QGIS_LEGEND_SINGLE_LAYER", "Legend requests require exactly one layer_key.")
        upstream["LAYER"] = short_names[0]
        upstream["FORMAT"] = "image/png"
    return upstream


def proxy_wms(session: Session, public: dict[str, str]) -> tuple[bytes, str, int]:
    """Call only the private service with a server-synthesized query."""

    parameters = build_upstream_parameters(session, public)
    url = os.getenv("QGIS_SERVER_INTERNAL_URL", "http://qgis-server/")
    try:
        response = httpx.get(url, params=parameters, timeout=20.0, follow_redirects=False)
    except httpx.HTTPError as exc:
        raise _error("QGIS_SERVER_UNAVAILABLE", "Private QGIS Server is unavailable.", status_code=503) from exc
    content_type = response.headers.get("content-type", "application/octet-stream").split(";", 1)[0].lower()
    if content_type not in {"image/png", "image/jpeg", "application/json", "text/xml", "application/xml", "application/vnd.ogc.se_xml"}:
        raise _error("QGIS_RESPONSE_NOT_ALLOWED", "QGIS Server returned an unexpected content type.", status_code=502, content_type=content_type)
    return response.content, content_type, response.status_code


def read_manifest() -> dict[str, Any]:
    path = Path(os.getenv("QGIS_SERVER_MANIFEST_PATH", "/srv/qgis/dayu_tiangong_server.manifest.json"))
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("schema_version") != MANIFEST_SCHEMA or data.get("project_key") != "dayu_tiangong":
        raise ValueError("QGIS Server manifest identity is invalid")
    short_names = [layer.get("qgis_short_name") for layer in data.get("layers", [])]
    if not short_names or len(short_names) != len(set(short_names)):
        raise ValueError("QGIS Server manifest short names are missing or duplicated")
    return data


def read_isolation_evidence(project_revision: str | None) -> HealthEvidence:
    """Accept only a runtime two-version probe bound to this exact project.

    Two published versions and a manifest FILTER field are necessary, but they
    do not prove that rendered images and FeatureInfo are isolated. The online
    verifier writes this file only after both probes pass.
    """

    path = Path(
        os.getenv(
            "QGIS_SERVER_ISOLATION_EVIDENCE_PATH",
            "/srv/qgis/dayu_tiangong_server.isolation.json",
        )
    )
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        version_ids = data.get("dataset_version_ids")
        passed = bool(
            data.get("schema_version") == ISOLATION_EVIDENCE_SCHEMA
            and project_revision
            and data.get("project_revision") == project_revision
            and isinstance(version_ids, list)
            and len(version_ids) >= 2
            and len(set(version_ids)) == len(version_ids)
            and data.get("getmap_isolated") is True
            and data.get("feature_info_isolated") is True
        )
        return HealthEvidence(
            passed=passed,
            evidence=(
                f"runtime GetMap/GetFeatureInfo probe passed for versions {version_ids}"
                if passed
                else "runtime isolation evidence is stale or incomplete"
            ),
        )
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        return HealthEvidence(
            passed=False,
            evidence="runtime two-version GetMap/GetFeatureInfo probe not verified",
        )


def health(session: Session) -> QgisServerHealthResponse:
    """Collect independent evidence without collapsing failures into one boolean."""

    try:
        manifest = read_manifest()
        project = HealthEvidence(passed=True, evidence=f"manifest {manifest['schema_version']} parsed")
        revision = str(manifest["project_revision"])
    except (OSError, ValueError, json.JSONDecodeError, KeyError) as exc:
        manifest = None
        project = HealthEvidence(passed=False, evidence=f"manifest invalid: {type(exc).__name__}")
        revision = None
    try:
        qgis_layer_count = int(session.scalar(select(func.count(GISLayerRegistry.id)).where(GISLayerRegistry.active.is_(True), GISLayerRegistry.service_mode == "QGIS_WMS")) or 0)
        database_read = HealthEvidence(passed=qgis_layer_count > 0, evidence=f"{qgis_layer_count} active QGIS WMS registry rows readable")
    except Exception as exc:  # database driver errors are evidence, not leaked responses
        database_read = HealthEvidence(passed=False, evidence=f"registry read failed: {type(exc).__name__}")
    try:
        response = httpx.get(os.getenv("QGIS_SERVER_INTERNAL_URL", "http://qgis-server/"), params={"SERVICE": "WMS", "VERSION": "1.3.0", "REQUEST": "GetCapabilities"}, timeout=3.0, follow_redirects=False)
        capabilities_ok = response.status_code == 200 and b"WMS_Capabilities" in response.content
        process = HealthEvidence(passed=True, evidence=f"private endpoint responded HTTP {response.status_code}")
        wms = HealthEvidence(passed=capabilities_ok, evidence="GetCapabilities returned a WMS document" if capabilities_ok else "GetCapabilities evidence missing")
    except httpx.HTTPError as exc:
        process = HealthEvidence(passed=False, evidence=f"private endpoint failed: {type(exc).__name__}")
        wms = HealthEvidence(passed=False, evidence="GetCapabilities not verified")
    published_count = int(session.scalar(select(func.count(DatasetVersion.id)).where(DatasetVersion.status == "published", DatasetVersion.content_hash.is_not(None))) or 0)
    manifest_filter_contract = bool(
        manifest
        and published_count >= 2
        and all(
            layer.get("dataset_filter_field") == "dataset_version_id"
            for layer in manifest.get("layers", [])
        )
    )
    isolation = (
        read_isolation_evidence(revision)
        if manifest_filter_contract
        else HealthEvidence(
            passed=False,
            evidence=(
                f"{published_count} published hashed versions; at least two required"
                if published_count < 2
                else "manifest dataset filter contract is incomplete"
            ),
        )
    )
    checks = [process.passed, project.passed, database_read.passed, wms.passed, isolation.passed]
    return QgisServerHealthResponse(status="healthy" if all(checks) else "degraded", process=process, project_valid=project, manifest_revision=revision, database_read=database_read, wms_capabilities=wms, dataset_version_isolation=isolation, details={"getprint_enabled": False, "public_port": False})
