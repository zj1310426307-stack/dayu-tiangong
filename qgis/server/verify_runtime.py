"""Verify two-version QGIS WMS isolation through the public safe gateway."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen


SCHEMA = "dayu-qgis-isolation-evidence/v1alpha1"


def _request(base_url: str, query: dict[str, str | int]) -> tuple[bytes, str]:
    request = Request(
        f"{base_url.rstrip('/')}?{urlencode(query)}",
        headers={"Accept": "application/json,image/png"},
    )
    with urlopen(request, timeout=30) as response:  # noqa: S310 - operator-owned URL
        return response.read(), response.headers.get_content_type()


def _feature_ids(payload: bytes) -> set[str]:
    document = json.loads(payload.decode("utf-8"))
    return {
        str(feature.get("properties", {}).get("id", feature.get("id")))
        for feature in document.get("features", [])
    } - {"None"}


def verify(args: argparse.Namespace) -> dict[str, object]:
    common = {
        "layer_key": args.layer_key,
        "bbox": args.bbox,
        "width": args.width,
        "height": args.height,
        "crs": "EPSG:4490",
        "format": "image/png",
        "transparent": "true",
    }
    map_hashes: list[str] = []
    feature_sets: list[set[str]] = []
    for version_id in (args.version_a, args.version_b):
        image, image_type = _request(
            args.gateway,
            {**common, "request": "GetMap", "dataset_version_id": version_id},
        )
        if image_type != "image/png" or not image.startswith(b"\x89PNG"):
            raise RuntimeError(f"GetMap for version {version_id} did not return PNG")
        map_hashes.append(hashlib.sha256(image).hexdigest())
        info, info_type = _request(
            args.gateway,
            {
                **common,
                "request": "GetFeatureInfo",
                "dataset_version_id": version_id,
                "i": args.i,
                "j": args.j,
                "feature_count": 20,
            },
        )
        if info_type != "application/json":
            raise RuntimeError(
                f"GetFeatureInfo for version {version_id} did not return JSON"
            )
        feature_sets.append(_feature_ids(info))
    getmap_isolated = map_hashes[0] != map_hashes[1]
    feature_info_isolated = bool(
        feature_sets[0]
        and feature_sets[1]
        and feature_sets[0].isdisjoint(feature_sets[1])
    )
    if not getmap_isolated or not feature_info_isolated:
        raise RuntimeError(
            "QGIS_TWO_VERSION_ISOLATION_FAILED: images or feature identities overlap"
        )
    evidence = {
        "schema_version": SCHEMA,
        "project_revision": args.project_revision,
        "dataset_version_ids": [args.version_a, args.version_b],
        "layer_key": args.layer_key,
        "getmap_isolated": True,
        "feature_info_isolated": True,
        "getmap_sha256": map_hashes,
        "feature_ids": [sorted(values) for values in feature_sets],
    }
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_suffix(output.suffix + ".tmp")
    temporary.write_text(
        json.dumps(evidence, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    temporary.replace(output)
    return evidence


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--gateway", default="http://127.0.0.1:8080/qgis-server/wms")
    parser.add_argument("--version-a", type=int, required=True)
    parser.add_argument("--version-b", type=int, required=True)
    parser.add_argument("--layer-key", default="river")
    parser.add_argument("--bbox", required=True)
    parser.add_argument("--width", type=int, default=1024)
    parser.add_argument("--height", type=int, default=768)
    parser.add_argument("--i", type=int, required=True)
    parser.add_argument("--j", type=int, required=True)
    parser.add_argument("--project-revision", required=True)
    parser.add_argument(
        "--output",
        default="qgis/server/generated/dayu_tiangong_server.isolation.json",
    )
    evidence = verify(parser.parse_args())
    print(json.dumps(evidence, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
