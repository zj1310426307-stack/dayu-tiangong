"""Measure comparable GeoJSON, WMS, WMTS, and MVT responses from the live stack."""

from __future__ import annotations

import argparse
import json
import statistics
import time
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any


def _url(base_url: str, path: str, query: dict[str, Any] | None = None) -> str:
    """Build one local acceptance URL without depending on third-party clients."""

    suffix = f"?{urllib.parse.urlencode(query)}" if query else ""
    return f"{base_url.rstrip('/')}{path}{suffix}"


def _targets(base_url: str) -> dict[str, str]:
    """Return fixed version-one requests over each supported delivery protocol."""

    wms = {
        "service": "WMS", "version": "1.1.1", "request": "GetMap",
        "layers": "dayu:river", "styles": "", "srs": "EPSG:4490",
        "bbox": "119.9,30.0,120.65,30.55", "width": 256, "height": 256,
        "format": "image/png", "transparent": "true",
        "CQL_FILTER": "dataset_version_id=1",
    }
    wmts = {
        "service": "WMTS", "version": "1.0.0", "request": "GetTile",
        "layer": "dayu:river", "style": "", "tilematrixset": "EPSG:900913",
        "tilematrix": "EPSG:900913:8", "tilerow": 105, "tilecol": 213,
        "format": "image/png", "CQL_FILTER": "dataset_version_id=1",
    }
    return {
        "GeoJSON": _url(base_url, "/api/v1/gis/rivers", {
            "dataset_version_id": 1, "limit": 500,
        }),
        "WMS": _url(base_url, "/geoserver/dayu/wms", wms),
        "WMTS": _url(base_url, "/geoserver/gwc/service/wmts", wmts),
        "MVT": _url(base_url, "/vector/tiles.river/8/213/105", {
            "dataset_version_id": 1,
        }),
    }


def _sample(url: str, runs: int) -> dict[str, Any]:
    """Warm one endpoint, then record response size and wall-clock latency."""

    latencies: list[float] = []
    sizes: list[int] = []
    content_type = ""
    for index in range(runs + 1):
        started = time.perf_counter()
        request = urllib.request.Request(url, headers={"Accept-Encoding": "identity"})
        with urllib.request.urlopen(request, timeout=30) as response:
            payload = response.read()
            status = response.status
            content_type = response.headers.get_content_type()
        elapsed_ms = (time.perf_counter() - started) * 1000
        if status != 200:
            raise RuntimeError(f"benchmark request failed with HTTP {status}: {url}")
        if index:
            latencies.append(elapsed_ms)
            sizes.append(len(payload))
    return {
        "status": 200,
        "content_type": content_type,
        "response_bytes": int(statistics.median(sizes)),
        "latency_ms_min": round(min(latencies), 3),
        "latency_ms_median": round(statistics.median(latencies), 3),
        "latency_ms_mean": round(statistics.fmean(latencies), 3),
        "runs": runs,
    }


def main() -> None:
    """Run the live protocol comparison and optionally persist machine-readable evidence."""

    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1:8080")
    parser.add_argument("--runs", type=int, default=10)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.runs < 1 or args.runs > 100:
        parser.error("--runs must be between 1 and 100")
    results = {
        "base_url": args.base_url,
        "measurement": "one warm-up followed by identity-encoded sequential requests",
        "protocols": {
            name: {"url": url, **_sample(url, args.runs)}
            for name, url in _targets(args.base_url).items()
        },
    }
    payload = json.dumps(results, ensure_ascii=False, indent=2)
    print(payload)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(f"{payload}\n", encoding="utf-8")


if __name__ == "__main__":
    main()
