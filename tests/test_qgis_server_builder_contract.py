"""Offline and optional native contracts for the A1 QGIS Server project builder."""

from __future__ import annotations

from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import xml.etree.ElementTree as ET

import pytest

ROOT = Path(__file__).resolve().parents[1]
SERVER_CODE = ROOT / "qgis/server"
if str(SERVER_CODE) not in sys.path:
    sys.path.insert(0, str(SERVER_CODE))

from build_server_project import build_pruned_qgs
from contracts import BuildContractError, validate_snapshot


SOURCE = ROOT / "qgis/projects/dayu_tiangong_ltr.qgs"
SNAPSHOT = ROOT / "qgis/server/bootstrap_registry.v1.json"
GENERATED = ROOT / "qgis/server/generated/dayu_tiangong_server.qgz"
MANIFEST = ROOT / "qgis/server/generated/dayu_tiangong_server.manifest.json"


def test_bootstrap_snapshot_is_temporary_and_exactly_four_qgis_layers() -> None:
    """Keep A1 deliberately small and prevent a second permanent Registry."""

    raw = json.loads(SNAPSHOT.read_text(encoding="utf-8"))
    layers = validate_snapshot(raw)
    assert "TEMPORARY BOOTSTRAP SNAPSHOT" in raw["notice"]
    assert [layer.layer_key for layer in layers] == ["river", "cross_section", "gate", "pump"]


def test_pruned_project_is_read_only_publish_only_and_preserves_source() -> None:
    """Prove the standard-library build does not mutate Desktop source or retain staging."""

    before = hashlib.sha256(SOURCE.read_bytes()).hexdigest()
    output, semantic = build_pruned_qgs(SOURCE, SNAPSHOT)
    assert hashlib.sha256(SOURCE.read_bytes()).hexdigest() == before
    text = output.decode("utf-8")
    assert "staging_qgis" not in text
    assert "dayu_qgis'" not in text
    assert text.count("service='dayu_qgis_server'") == 8  # four tree nodes + four maplayers
    assert all(item["source_schema"] == "publish" for item in semantic["layers"])
    root = ET.fromstring(output)
    groups = root.findall("./layer-tree-group/layer-tree-group")
    assert [group.get("name") for group in groups] == [
        "01_HYDROGRAPHY",
        "02_HYDRAULIC_MODEL",
        "03_ENGINEERING",
    ]
    layers = root.findall("./projectlayers/maplayer")
    assert len(layers) == 4
    assert all(layer.get("readOnly") == "1" for layer in layers)
    assert len({layer.findtext("shortname") for layer in layers}) == 4


def test_missing_publish_candidate_fails_closed(tmp_path: Path) -> None:
    """A Registry row with no Desktop publish candidate must stop the build."""

    raw = json.loads(SNAPSHOT.read_text(encoding="utf-8"))
    raw["layers"][0]["source_relation"] = "missing_river"
    path = tmp_path / "missing.json"
    path.write_text(json.dumps(raw), encoding="utf-8")
    with pytest.raises(BuildContractError, match="resolved to 0 candidates"):
        build_pruned_qgs(SOURCE, path)


def test_ambiguous_publish_candidate_fails_closed(tmp_path: Path) -> None:
    """Duplicate source candidates must not be resolved by tree order or guessing."""

    root = ET.parse(SOURCE).getroot()
    group = next(
        item
        for item in root.findall("./layer-tree-group/layer-tree-group")
        if item.get("name") == "03_PUBLISH_READONLY"
    )
    river_node = next(
        node
        for node in group.findall("layer-tree-layer")
        if 'table="publish"."river"' in node.get("source", "")
    )
    river_id = river_node.get("id")
    project_layers = root.find("./projectlayers")
    river_layer = next(layer for layer in project_layers.findall("maplayer") if layer.findtext("id") == river_id)
    duplicate_node = deepcopy(river_node)
    duplicate_layer = deepcopy(river_layer)
    duplicate_id = f"{river_id}_duplicate"
    duplicate_node.set("id", duplicate_id)
    duplicate_layer.find("id").text = duplicate_id
    group.append(duplicate_node)
    project_layers.append(duplicate_layer)
    path = tmp_path / "ambiguous.qgs"
    ET.ElementTree(root).write(path, encoding="utf-8", xml_declaration=True)
    with pytest.raises(BuildContractError, match="resolved to 2 candidates"):
        build_pruned_qgs(path, SNAPSHOT)


def test_generated_manifest_and_project_are_present_and_safe() -> None:
    """The tracked deployment pair must match the frozen manifest shape."""

    assert GENERATED.is_file()
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    assert manifest["schema_version"] == "dayu-qgis-server-manifest/v1alpha1"
    assert manifest["qgis_version"].startswith("3.44.")
    assert manifest["project_crs"] == "EPSG:4490"
    assert len(manifest["layers"]) == 4
    assert manifest["layouts"][0]["name"] == "Dayu_A4_Landscape"
    serialized = MANIFEST.read_text(encoding="utf-8")
    for forbidden in ("password=", "authcfg=", "staging_qgis", "C:\\Users\\", "D:\\CH\\"):
        assert forbidden not in serialized


def test_optional_native_qgis_readback() -> None:
    """Use QGIS CLI as a native availability/readability smoke when configured."""

    executable = os.getenv("QGIS_PROCESS_EXECUTABLE")
    if not executable:
        pytest.skip("QGIS_PROCESS_EXECUTABLE is not configured")
    result = subprocess.run(
        [os.environ.get("COMSPEC", "cmd.exe"), "/d", "/c", executable, "--version"],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert result.returncode == 0, result.stderr
