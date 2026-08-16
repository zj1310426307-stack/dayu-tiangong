"""Build the deterministic, read-only QGIS Server deployment project.

The standard-library phase selects and rewrites only allowlisted publish layers. The
native phase uses QGIS 3.44 LTR to add the print layout, write QGZ, and read it back.
"""

from __future__ import annotations

import argparse
from copy import deepcopy
import json
import os
from pathlib import Path
import sys
import tempfile
from typing import Any
import xml.etree.ElementTree as ET
from zipfile import ZipFile

sys.path.insert(0, str(Path(__file__).resolve().parent))
from contracts import ALLOWED_GROUPS, BootstrapLayer, BuildContractError, validate_snapshot
from manifest import canonical_json_bytes, canonical_xml_bytes, element_fingerprint, project_revision, sha256_bytes, sha256_file


BUILDER_VERSION = "1.0.0"
SOURCE_GROUP = "03_PUBLISH_READONLY"
LAYOUT_NAME = "Dayu_A4_Landscape"
LAYOUT_ITEM_IDS = (
    "map_main",
    "title",
    "legend",
    "scale_bar",
    "north_arrow",
    "dataset_version",
    "map_time",
    "crs",
    "notice",
)


def _table_identity(datasource: str) -> tuple[str, str] | None:
    """Extract the quoted schema/relation pair from a trusted source project URI."""

    marker = 'table="'
    if marker not in datasource:
        return None
    tail = datasource.split(marker, 1)[1]
    pieces = tail.split('"."', 1)
    if len(pieces) != 2 or '"' not in pieces[1]:
        return None
    return pieces[0], pieces[1].split('"', 1)[0]


def _project_layer_map(root: ET.Element) -> dict[str, ET.Element]:
    """Index source maplayer elements by stable project layer id."""

    result: dict[str, ET.Element] = {}
    for layer in root.findall("./projectlayers/maplayer"):
        layer_id = layer.findtext("id")
        if layer_id:
            result[layer_id] = layer
    return result


def _source_group_nodes(root: ET.Element) -> list[ET.Element]:
    """Return tree nodes only from the frozen publish group, never reference/staging."""

    groups = root.findall("./layer-tree-group/layer-tree-group")
    matches = [group for group in groups if group.get("name") == SOURCE_GROUP]
    if len(matches) != 1:
        raise BuildContractError(f"expected exactly one {SOURCE_GROUP} group")
    return list(matches[0].iterfind(".//layer-tree-layer"))


def _select_layers(root: ET.Element, layers: tuple[BootstrapLayer, ...]) -> list[tuple[BootstrapLayer, ET.Element, ET.Element]]:
    """Resolve every Registry row to exactly one source tree node and maplayer."""

    project_layers = _project_layer_map(root)
    source_nodes = _source_group_nodes(root)
    selected: list[tuple[BootstrapLayer, ET.Element, ET.Element]] = []
    for contract in layers:
        candidates: list[tuple[ET.Element, ET.Element]] = []
        for node in source_nodes:
            maplayer = project_layers.get(node.get("id", ""))
            if maplayer is None:
                continue
            identity = _table_identity(maplayer.findtext("datasource") or "")
            if identity == (contract.source_schema, contract.source_relation):
                candidates.append((node, maplayer))
        if len(candidates) != 1:
            raise BuildContractError(
                f"{contract.layer_key} resolved to {len(candidates)} candidates in {SOURCE_GROUP}"
            )
        selected.append((contract, candidates[0][0], candidates[0][1]))
    return selected


def _set_property(properties: ET.Element, name: str, value: str, value_type: str = "QString") -> None:
    """Set one QGIS project property without carrying unsafe source values forward."""

    existing = properties.find(name)
    if existing is None:
        existing = ET.SubElement(properties, name)
    existing.set("type", value_type)
    existing.text = value


def build_pruned_qgs(source: Path, snapshot: Path) -> tuple[bytes, dict[str, Any]]:
    """Create safe QGS XML and semantic manifest inputs without importing QGIS."""

    source_bytes = source.read_bytes()
    snapshot_raw = json.loads(snapshot.read_text(encoding="utf-8"))
    contracts = validate_snapshot(snapshot_raw)
    root = ET.fromstring(source_bytes)
    selected = _select_layers(root, contracts)

    tree_root = root.find("./layer-tree-group")
    project_layers = root.find("./projectlayers")
    if tree_root is None or project_layers is None:
        raise BuildContractError("source project is missing layer tree or projectlayers")
    for child in list(tree_root):
        if child.tag in {"layer-tree-group", "layer-tree-layer"}:
            tree_root.remove(child)
    for child in list(project_layers):
        project_layers.remove(child)

    output_ids: list[str] = []
    manifest_layers: list[dict[str, Any]] = []
    for group_name in ALLOWED_GROUPS:
        group = ET.SubElement(
            tree_root,
            "layer-tree-group",
            {"checked": "Qt::Checked", "expanded": "1", "groupLayer": "", "name": group_name},
        )
        ET.SubElement(group, "customproperties")
        for contract, source_node, source_layer in selected:
            if contract.group_key != group_name:
                continue
            node = deepcopy(source_node)
            node.set("name", contract.display_title)
            safe_datasource = (
                "service='dayu_qgis_server' key='id' srid=4490 "
                f"type={contract.geometry_type} checkPrimaryKeyUnicity='1' "
                f'table="publish"."{contract.source_relation}" (geometry)'
            )
            node.set("source", safe_datasource)
            node.set("providerKey", "postgres")
            group.append(node)
            layer = deepcopy(source_layer)
            layer.set("readOnly", "1")
            layer_id = layer.findtext("id")
            if not layer_id:
                raise BuildContractError(f"{contract.layer_key} has no project layer id")
            output_ids.append(layer_id)
            layer.find("layername").text = contract.display_title
            short_name = layer.find("shortname")
            if short_name is None:
                short_name = ET.SubElement(layer, "shortname")
            short_name.text = contract.qgis_short_name
            datasource = layer.find("datasource")
            if datasource is None:
                raise BuildContractError(f"{contract.layer_key} has no datasource")
            datasource.text = safe_datasource
            for tag in (
                "editform",
                "editforminit",
                "editforminitcodesource",
                "editforminitfilepath",
                "editforminitcode",
                "featformsuppress",
                "editable",
                "labelOnTop",
                "reuseLastValue",
            ):
                for element in list(layer.findall(tag)):
                    layer.remove(element)
            project_layers.append(layer)
            manifest_layers.append(
                {
                    "layer_key": contract.layer_key,
                    "title": contract.title,
                    "display_title": contract.display_title,
                    "group_key": contract.group_key,
                    "order": contract.order,
                    "source_schema": contract.source_schema,
                    "source_relation": contract.source_relation,
                    "qgis_short_name": contract.qgis_short_name,
                    "geometry_type": contract.geometry_type,
                    "dataset_filter_field": contract.dataset_filter_field,
                    "min_scale": float(layer.get("minScale", "0")),
                    "max_scale": float(layer.get("maxScale", "0")),
                    "feature_info_fields": list(contract.feature_info_fields),
                    "style_fingerprint": element_fingerprint(layer.find("renderer-v2")),
                    "labeling_fingerprint": element_fingerprint(layer.find("labeling")),
                }
            )

    layer_order = root.find("./layerorder")
    if layer_order is not None:
        for child in list(layer_order):
            layer_order.remove(child)
        for layer_id in output_ids:
            ET.SubElement(layer_order, "layer", {"id": layer_id})
    relations = root.find("./relations")
    if relations is not None:
        relations.clear()
    snapping = root.find("./snapping-settings")
    if snapping is not None:
        snapping.set("enabled", "0")
        for child in list(snapping):
            snapping.remove(child)
    transaction = root.find("./transaction")
    if transaction is not None:
        transaction.set("mode", "Disabled")
    title = root.find("./title")
    if title is None:
        title = ET.SubElement(root, "title")
    title.text = "大禹·天工 QGIS Server"
    layouts = root.find("./Layouts")
    if layouts is not None:
        layouts.clear()
    properties = root.find("./properties")
    if properties is None:
        properties = ET.SubElement(root, "properties")
    _set_property(properties, "WMSServiceTitle", "大禹·天工 QGIS Server")
    _set_property(properties, "WMSServiceCapabilities", "true", "bool")
    _set_property(properties, "WMSRequestDefinedDataSources", "false", "bool")
    _set_property(properties, "WMSAddWktGeometry", "false", "bool")

    semantic = {
        "schema_version": "dayu-qgis-server-manifest/v1alpha1",
        "project_key": "dayu_tiangong",
        "source_project_hash": sha256_bytes(source_bytes),
        "registry_snapshot_hash": sha256_file(snapshot),
        "builder_version": BUILDER_VERSION,
        "project_crs": "EPSG:4490",
        "layers": sorted(manifest_layers, key=lambda item: (item["order"], item["layer_key"])),
        "groups": list(ALLOWED_GROUPS),
        "layouts": [{"name": LAYOUT_NAME, "items": list(LAYOUT_ITEM_IDS), "print_enabled": False}],
        "warnings": ["GetPrint remains disabled until A2 two-version isolation passes."],
    }
    return ET.tostring(root, encoding="utf-8", xml_declaration=True), semantic


def _prepare_windows_dll_search() -> list[Any]:
    """Keep DLL directory handles alive for portable Windows QGIS installations."""

    if os.name != "nt" or not hasattr(os, "add_dll_directory"):
        return []
    prefix = Path(os.environ.get("QGIS_PREFIX_PATH", ""))
    if not prefix:
        return []
    root = prefix.parents[1]
    handles = []
    for directory in (root / "bin", root / "apps" / "Qt5" / "bin", prefix / "bin"):
        if directory.exists():
            handles.append(os.add_dll_directory(str(directory)))
    return handles


def _add_layout(project: Any) -> None:
    """Add the frozen A4 landscape layout with stable item IDs and safe placeholders."""

    from qgis.core import (
        QgsLayoutItemLabel,
        QgsLayoutItemLegend,
        QgsLayoutItemMap,
        QgsLayoutItemPicture,
        QgsLayoutItemScaleBar,
        QgsLayoutPoint,
        QgsLayoutSize,
        QgsPrintLayout,
        QgsRectangle,
        QgsUnitTypes,
    )

    units = QgsUnitTypes.LayoutMillimeters
    layout = QgsPrintLayout(project)
    layout.initializeDefaults()
    layout.setName(LAYOUT_NAME)
    page = layout.pageCollection().page(0)
    page.attemptResize(QgsLayoutSize(297, 210, units))

    map_item = QgsLayoutItemMap(layout)
    map_item.setId("map_main")
    map_item.attemptMove(QgsLayoutPoint(10, 25, units))
    map_item.attemptResize(QgsLayoutSize(215, 160, units))
    map_item.setExtent(QgsRectangle(119.0, 29.0, 121.0, 31.0))
    layout.addLayoutItem(map_item)

    def add_label(item_id: str, text: str, x: float, y: float, width: float, height: float) -> None:
        label = QgsLayoutItemLabel(layout)
        label.setId(item_id)
        label.setText(text)
        label.attemptMove(QgsLayoutPoint(x, y, units))
        label.attemptResize(QgsLayoutSize(width, height, units))
        layout.addLayoutItem(label)

    add_label("title", "大禹·天工 专业 GIS 地图", 10, 7, 215, 12)
    add_label("dataset_version", "DATASET_VERSION_NOT_INJECTED", 230, 28, 57, 12)
    add_label("map_time", "MAP_TIME_NOT_INJECTED", 230, 43, 57, 12)
    add_label("crs", "CGCS2000 / EPSG:4490", 230, 58, 57, 12)
    add_label("notice", "DEMO / 未率定 / 非调度指令", 230, 170, 57, 15)

    legend = QgsLayoutItemLegend(layout)
    legend.setId("legend")
    legend.setLinkedMap(map_item)
    legend.attemptMove(QgsLayoutPoint(230, 78, units))
    legend.attemptResize(QgsLayoutSize(57, 60, units))
    layout.addLayoutItem(legend)

    scale = QgsLayoutItemScaleBar(layout)
    scale.setId("scale_bar")
    scale.setLinkedMap(map_item)
    scale.attemptMove(QgsLayoutPoint(15, 188, units))
    scale.attemptResize(QgsLayoutSize(80, 8, units))
    layout.addLayoutItem(scale)

    north = QgsLayoutItemPicture(layout)
    north.setId("north_arrow")
    north.attemptMove(QgsLayoutPoint(198, 28, units))
    north.attemptResize(QgsLayoutSize(20, 20, units))
    layout.addLayoutItem(north)
    project.layoutManager().addLayout(layout)


def _qgs_from_qgz(path: Path) -> bytes:
    """Read the single project XML member from a generated QGZ archive."""

    with ZipFile(path) as archive:
        members = [name for name in archive.namelist() if name.lower().endswith(".qgs")]
        if len(members) != 1:
            raise BuildContractError("generated QGZ must contain exactly one QGS member")
        return archive.read(members[0])


def build(
    source: Path,
    snapshot: Path,
    output: Path,
    manifest_path: Path,
    *,
    terminate_windows_process: bool = False,
) -> dict[str, Any]:
    """Run the full PyQGIS build, native readback, and canonical manifest emission."""

    def progress(message: str) -> None:
        """Emit a bounded build stage marker for diagnosing native provider startup."""

        print(f"[qgis-builder] {message}", file=sys.stderr, flush=True)

    progress("prepare safe QGS")
    qgs_bytes, semantic = build_pruned_qgs(source, snapshot)
    dll_handles = _prepare_windows_dll_search()
    progress("import PyQGIS")
    from qgis.core import Qgis, QgsApplication, QgsProject

    prefix = os.environ.get("QGIS_PREFIX_PATH")
    if prefix:
        QgsApplication.setPrefixPath(prefix, True)
    application = QgsApplication([], False)
    progress("initialize QGIS")
    application.initQgis()
    try:
        if not str(Qgis.QGIS_VERSION).startswith("3.44."):
            raise BuildContractError(f"QGIS 3.44 LTR required, got {Qgis.QGIS_VERSION}")
        output.parent.mkdir(parents=True, exist_ok=True)
        manifest_path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix="dayu-qgis-builder-") as temporary:
            temporary_qgs = Path(temporary) / "dayu_tiangong_server.qgs"
            temporary_qgs.write_bytes(qgs_bytes)
            read_flags = Qgis.ProjectReadFlag.DontResolveLayers | Qgis.ProjectReadFlag.ForceReadOnlyLayers
            project = QgsProject()
            progress("read pruned project")
            if not project.read(str(temporary_qgs), read_flags):
                raise BuildContractError("QGIS could not read the pruned server project")
            progress("add layout")
            _add_layout(project)
            progress("write QGZ")
            if not project.write(str(output)):
                raise BuildContractError("QGIS could not write the generated QGZ")
            readback = QgsProject()
            progress("native readback")
            if not readback.read(str(output), read_flags):
                raise BuildContractError("QGIS native readback failed")
            if readback.crs().authid() != "EPSG:4490":
                raise BuildContractError("generated project CRS drifted")
            if len(readback.mapLayers()) != len(semantic["layers"]):
                raise BuildContractError("generated project layer count drifted")
            if readback.layoutManager().layoutByName(LAYOUT_NAME) is None:
                raise BuildContractError("generated project layout is missing")
        final_qgs = _qgs_from_qgz(output)
        semantic["qgis_version"] = str(Qgis.QGIS_VERSION)
        semantic["qgis_project_hash"] = sha256_bytes(canonical_xml_bytes(ET.fromstring(final_qgs)))
        semantic["project_revision"] = project_revision(final_qgs, semantic)
        manifest_path.write_bytes(canonical_json_bytes(semantic) + b"\n")
        progress("complete")
        if os.name == "nt" and terminate_windows_process:
            print(
                json.dumps(
                    {"project_revision": semantic["project_revision"], "layers": len(semantic["layers"])},
                    sort_keys=True,
                ),
                flush=True,
            )
            sys.stderr.flush()
            os._exit(0)
        return semantic
    finally:
        if os.name != "nt":
            application.exitQgis()
            for handle in dll_handles:
                handle.close()


def main() -> int:
    """Parse explicit paths so build outputs never escape the repository by accident."""

    root = Path(__file__).resolve().parents[2]
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, default=root / "qgis/projects/dayu_tiangong_ltr.qgs")
    parser.add_argument("--snapshot", type=Path, default=root / "qgis/server/bootstrap_registry.v1.json")
    parser.add_argument("--output", type=Path, default=root / "qgis/server/generated/dayu_tiangong_server.qgz")
    parser.add_argument(
        "--manifest",
        type=Path,
        default=root / "qgis/server/generated/dayu_tiangong_server.manifest.json",
    )
    args = parser.parse_args()
    manifest = build(
        args.source.resolve(),
        args.snapshot.resolve(),
        args.output.resolve(),
        args.manifest.resolve(),
        terminate_windows_process=True,
    )
    print(json.dumps({"project_revision": manifest["project_revision"], "layers": len(manifest["layers"])}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
