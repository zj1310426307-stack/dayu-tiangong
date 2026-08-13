"""Generate deterministic DEMO COG and 3D Tiles assets in Docker-managed volumes."""

from __future__ import annotations

import json
import shutil
import struct
import subprocess
from pathlib import Path


RASTER_ROOT = Path("/data")
TILES_ROOT = Path("/3d")


def _run(arguments: list[str]) -> None:
    """Run one fixed GDAL command and surface its bounded diagnostic output."""

    result = subprocess.run(arguments, capture_output=True, text=True, check=False, timeout=120)
    if result.returncode:
        raise RuntimeError((result.stderr or result.stdout).strip()[-500:])


def _create_cog(name: str, value: float) -> None:
    """Create one georeferenced constant DEMO raster and convert it to a valid COG."""

    temporary = RASTER_ROOT / f".{name}.source.tif"
    target = RASTER_ROOT / f"{name}.tif"
    _run([
        "gdal_create", "-of", "GTiff", "-outsize", "256", "256", "-bands", "1",
        "-ot", "Float32", "-burn", str(value), "-a_srs", "EPSG:4490", "-a_ullr",
        "113.10", "23.35", "113.55", "22.95", str(temporary),
    ])
    _run([
        "gdal_translate", "-of", "COG", "-co", "COMPRESS=DEFLATE",
        "-co", "OVERVIEWS=AUTO", str(temporary), str(target),
    ])
    temporary.unlink(missing_ok=True)


def _create_glb(path: Path) -> None:
    """Write a minimal valid glTF binary triangle used by the DEMO 3D Tiles manifest."""

    positions = struct.pack("<9f", -40.0, -40.0, 0.0, 40.0, -40.0, 0.0, 0.0, 40.0, 80.0)
    document = {
        "asset": {"version": "2.0", "generator": "Dayu Tiangong DGIS DEMO"},
        "scene": 0,
        "scenes": [{"nodes": [0]}],
        "nodes": [{"mesh": 0}],
        "meshes": [{"primitives": [{"attributes": {"POSITION": 0}, "mode": 4}]}],
        "buffers": [{"byteLength": len(positions)}],
        "bufferViews": [{"buffer": 0, "byteOffset": 0, "byteLength": len(positions)}],
        "accessors": [{
            "bufferView": 0, "componentType": 5126, "count": 3, "type": "VEC3",
            "min": [-40.0, -40.0, 0.0], "max": [40.0, 40.0, 80.0],
        }],
    }
    json_chunk = json.dumps(document, separators=(",", ":")).encode("utf-8")
    json_chunk += b" " * ((4 - len(json_chunk) % 4) % 4)
    binary_chunk = positions + b"\x00" * ((4 - len(positions) % 4) % 4)
    total = 12 + 8 + len(json_chunk) + 8 + len(binary_chunk)
    path.write_bytes(
        struct.pack("<4sII", b"glTF", 2, total)
        + struct.pack("<I4s", len(json_chunk), b"JSON") + json_chunk
        + struct.pack("<I4s", len(binary_chunk), b"BIN\x00") + binary_chunk
    )


def _create_tileset() -> None:
    """Create a 3D Tiles 1.1 manifest around the deterministic local glTF asset."""

    target = TILES_ROOT / "demo-tileset.json"
    _create_glb(TILES_ROOT / "demo-facility.glb")
    target.write_text(json.dumps({
        "asset": {"version": "1.1", "tilesetVersion": "dgis-demo-v1"},
        "geometricError": 500,
        "root": {
            "boundingVolume": {"region": [1.977, 0.403, 1.979, 0.405, 0, 120]},
            "geometricError": 0,
            "refine": "ADD",
            "transform": [
                -0.919, 0.394, 0, 0, -0.158, -0.369, 0.916, 0,
                0.361, 0.842, 0.401, 0, -2251774, 5015907, 3228525, 1,
            ],
            "content": {"uri": "demo-facility.glb"},
        },
    }, ensure_ascii=False, indent=2), encoding="utf-8")


def main() -> None:
    """Refresh all generated DEMO assets without touching business source data."""

    if shutil.which("gdal_create") is None or shutil.which("gdal_translate") is None:
        raise RuntimeError("GDAL command-line tools are required for DGIS asset generation")
    RASTER_ROOT.mkdir(parents=True, exist_ok=True)
    TILES_ROOT.mkdir(parents=True, exist_ok=True)
    for name, value in (("water-depth-demo", 3.2), ("velocity-demo", 1.4), ("flood-risk-demo", 0.72)):
        _create_cog(name, value)
    _create_tileset()
    print("DGIS DEMO assets ready: 3 COG rasters, 1 3D Tiles 1.1 manifest")


if __name__ == "__main__":
    main()
