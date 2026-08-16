"""Canonical manifest contracts that do not require a running QGIS Server."""

from __future__ import annotations

import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
SERVER_CODE = ROOT / "qgis/server"
if str(SERVER_CODE) not in sys.path:
    sys.path.insert(0, str(SERVER_CODE))

from manifest import canonical_json_bytes, project_revision


MANIFEST = ROOT / "qgis/server/generated/dayu_tiangong_server.manifest.json"


def test_canonical_json_ignores_mapping_insertion_order() -> None:
    """Registry export order must not change its canonical snapshot identity."""

    assert canonical_json_bytes({"b": 2, "a": 1}) == canonical_json_bytes({"a": 1, "b": 2})


def test_project_revision_is_semantically_sensitive() -> None:
    """A real project or manifest change must produce a different revision."""

    xml = b"<qgis><title>dayu</title></qgis>"
    first = project_revision(xml, {"layers": [{"layer_key": "river"}]})
    assert first == project_revision(xml, {"layers": [{"layer_key": "river"}]})
    assert first != project_revision(xml, {"layers": [{"layer_key": "gate"}]})


def test_manifest_layers_have_fingerprints_and_version_filter() -> None:
    """Every QGIS WMS layer must bind cartography and dataset version semantics."""

    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    assert len({layer["qgis_short_name"] for layer in manifest["layers"]}) == 4
    for layer in manifest["layers"]:
        assert layer["dataset_filter_field"] == "dataset_version_id"
        assert len(layer["style_fingerprint"]) == 64
        assert len(layer["labeling_fingerprint"]) == 64
