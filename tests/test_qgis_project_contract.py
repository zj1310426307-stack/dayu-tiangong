from __future__ import annotations

import os
import re
import shutil
import subprocess
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
QGIS_ROOT = REPOSITORY_ROOT / "qgis"
PROJECT_PATH = QGIS_ROOT / "projects" / "dayu_tiangong_ltr.qgs"
STYLE_ROOT = QGIS_ROOT / "styles"
SERVICE_EXAMPLE = QGIS_ROOT / "docs" / "pg_service.conf.example"

GROUP_LAYERS = {
    "01_REFERENCE_READONLY": {
        "ref_river",
        "ref_river_node",
        "ref_river_segment",
        "ref_administrative_area",
        "ref_road",
        "ref_place_name",
    },
    "02_EDIT_STAGING": {
        "stg_river",
        "stg_cross_section",
        "stg_gate",
        "stg_pump",
    },
    "03_PUBLISH_READONLY": {
        "pub_river",
        "pub_cross_section",
        "pub_gate",
        "pub_pump",
    },
}

LAYER_SOURCES = {
    "ref_river": ("publish", "river", "LineString"),
    "ref_river_node": ("publish", "river_node", "Point"),
    "ref_river_segment": ("publish", "river_segment", "LineString"),
    "ref_administrative_area": ("publish", "administrative_area", "Polygon"),
    "ref_road": ("publish", "road", "LineString"),
    "ref_place_name": ("publish", "place_name", "Point"),
    "stg_river": ("staging_qgis", "river", "LineString"),
    "stg_cross_section": ("staging_qgis", "cross_section", "Point"),
    "stg_gate": ("staging_qgis", "gate", "Point"),
    "stg_pump": ("staging_qgis", "pump", "Point"),
    "pub_river": ("publish", "river", "LineString"),
    "pub_cross_section": ("publish", "cross_section", "Point"),
    "pub_gate": ("publish", "gate", "Point"),
    "pub_pump": ("publish", "pump", "Point"),
}

STAGING_STYLE_FILES = {
    "staging_river.qml",
    "staging_cross_section.qml",
    "staging_gate.qml",
    "staging_pump.qml",
}
PUBLISH_STYLE_FILES = {
    "publish_river.qml",
    "publish_cross_section.qml",
    "publish_gate.qml",
    "publish_pump.qml",
}

SECRET_ASSIGNMENT = re.compile(
    r"(?i)(?:password|pwd|passfile|api[_-]?key|secret|token|authcfg)\s*="
)
PERSONAL_ABSOLUTE_PATH = re.compile(
    r"(?i)(?:(?<![a-z0-9])[a-z]:[\\/]|"
    r"/(?:home|users)/|\\\\[^\\\s]+\\)"
)


def _project_root() -> ET.Element:
    return ET.parse(PROJECT_PATH).getroot()


def _project_layers(root: ET.Element) -> dict[str, ET.Element]:
    return {
        layer.findtext("shortname", default="") or layer.findtext("id", default=""): layer
        for layer in root.findall("./projectlayers/maplayer")
    }


def _native_to_logical_layer_ids(root: ET.Element) -> dict[str, str]:
    return {
        layer.findtext("id", default=""): (
            layer.findtext("shortname", default="")
            or layer.findtext("id", default="")
        )
        for layer in root.findall("./projectlayers/maplayer")
    }


def test_qgis_xml_assets_are_well_formed_and_target_ltr() -> None:
    root = _project_root()
    assert root.tag == "qgis"
    assert root.attrib["version"].startswith("3.44.")

    qml_files = sorted(STYLE_ROOT.glob("*.qml"))
    assert len(qml_files) >= 8
    for path in qml_files:
        style_root = ET.parse(path).getroot()
        assert style_root.tag == "qgis"
        assert style_root.attrib["version"].startswith("3.44.")
        assert style_root.find("renderer-v2") is not None


def test_project_crs_transactions_paths_and_topology() -> None:
    root = _project_root()
    assert root.findtext("./projectCrs/spatialrefsys/authid") == "EPSG:4490"
    assert root.findtext("./projectCrs/spatialrefsys/srid") == "4490"
    assert root.find("transaction").attrib["mode"] == "AutomaticGroups"
    assert (
        root.find("projectFlags").attrib["set"]
        == "EvaluateDefaultValuesOnProviderSide"
    )
    assert root.findtext("./properties/Paths/Absolute") == "false"
    assert root.findtext("./properties/Digitizing/TopologicalEditing") == "1"
    assert root.find("homePath").attrib["path"] == ".."


def test_project_has_exactly_three_required_top_level_groups() -> None:
    root = _project_root()
    native_to_logical = _native_to_logical_layer_ids(root)
    tree_root = root.find("layer-tree-group")
    groups = tree_root.findall("./layer-tree-group")
    assert [group.attrib["name"] for group in groups] == list(GROUP_LAYERS)

    for group in groups:
        ids = {
            native_to_logical[item.attrib["id"]]
            for item in group.findall("./layer-tree-layer")
        }
        assert ids == GROUP_LAYERS[group.attrib["name"]]


def test_layer_ids_providers_sources_and_write_boundaries() -> None:
    root = _project_root()
    layers = _project_layers(root)
    expected_ids = set().union(*GROUP_LAYERS.values())
    assert set(layers) == expected_ids

    for layer_id, layer in layers.items():
        assert layer.findtext("provider") == "postgres"
        datasource = layer.findtext("datasource", default="")
        schema, table, geometry_type = LAYER_SOURCES[layer_id]
        assert "service='dayu_qgis'" in datasource
        assert "key='id'" in datasource
        assert "srid=4490" in datasource
        assert f"type={geometry_type}" in datasource
        assert f'table="{schema}"."{table}" (geometry)' in datasource

        if layer_id.startswith("stg_"):
            assert layer.attrib["readOnly"] == "0"
        else:
            assert layer.attrib["readOnly"] == "1"


def test_datasources_use_service_only_and_assets_have_no_secrets_or_personal_paths() -> None:
    root = _project_root()
    forbidden_connection_keys = re.compile(
        r"(?i)(?:host|port|dbname|user|password|pwd|passfile|sslmode|authcfg|token|secret)="
    )
    for layer in root.findall("./projectlayers/maplayer"):
        datasource = layer.findtext("datasource", default="")
        assert not forbidden_connection_keys.search(datasource)

    scanned_files = [
        path
        for path in QGIS_ROOT.rglob("*")
        if path.is_file()
        and path.suffix.lower() in {".qgs", ".qml", ".md", ".example", ".ps1", ".cmd"}
    ]
    for path in scanned_files:
        text = path.read_text(encoding="utf-8")
        assert not SECRET_ASSIGNMENT.search(text), path
        path_scan_text = text
        if path.name in {"Start_Dayu_QGIS.ps1", "Start_Dayu_QGIS.cmd"}:
            path_scan_text = re.sub(r"(?i)(?<![a-z0-9])[qrs]:[\\/]", "", text)
        assert not PERSONAL_ABSOLUTE_PATH.search(path_scan_text), path


def test_snapping_is_pixel_based_and_limited_to_staging() -> None:
    root = _project_root()
    snapping = root.find("snapping-settings")
    assert snapping.attrib["enabled"] == "1"
    # QGIS 3.44 serializes AdvancedConfiguration as mode=3.
    assert snapping.attrib["mode"] == "3"
    assert snapping.attrib["type"] == "3"
    assert snapping.attrib["unit"] == "1"
    assert snapping.attrib["intersection-snapping"] == "1"
    assert snapping.attrib["self-snapping"] == "1"

    native_to_logical = _native_to_logical_layer_ids(root)
    settings = [
        setting
        for setting in snapping.findall("./individual-layer-settings/layer-setting")
        if setting.attrib["enabled"] == "1"
    ]
    assert {native_to_logical[setting.attrib["id"]] for setting in settings} == GROUP_LAYERS[
        "02_EDIT_STAGING"
    ]
    assert all(setting.attrib["enabled"] == "1" for setting in settings)
    assert all(setting.attrib["units"] == "1" for setting in settings)


def test_staging_forms_have_hard_constraints_and_system_fields_are_read_only() -> None:
    layers = _project_layers(_project_root())
    business_required = {
        "stg_river": {
            "batch_id",
            "source_feature_id",
            "operation",
            "name",
            "code",
            "length",
        },
        "stg_cross_section": {
            "batch_id",
            "source_feature_id",
            "operation",
            "river_code",
            "section_code",
            "station",
            "roughness",
        },
        "stg_gate": {
            "batch_id",
            "source_feature_id",
            "operation",
            "river_code",
            "gate_code",
            "width",
            "height",
            "max_flow",
        },
        "stg_pump": {
            "batch_id",
            "source_feature_id",
            "operation",
            "river_code",
            "pump_code",
            "design_flow",
            "head",
            "power",
        },
    }
    read_only_system_fields = {
        "id",
        "quality_status",
        "source_crs",
        "target_crs",
        "source_hash",
        "operator",
        "source_payload",
        "created_at",
        "updated_at",
    }

    for layer_id, required in business_required.items():
        layer = layers[layer_id]
        constraints = {
            item.attrib["field"]: item
            for item in layer.findall("./constraints/constraint")
        }
        assert required <= set(constraints)
        assert all(constraints[field].attrib["notnull_strength"] == "1" for field in required)

        explicitly_editable = {
            item.attrib["name"]: item.attrib["editable"]
            for item in layer.findall("./editable/field")
        }
        assert all(explicitly_editable[field] == "0" for field in read_only_system_fields)
        # Native QGIS serialization omits ordinary editable fields; absence means editable.
        assert explicitly_editable.get("operation", "1") == "1"
        assert explicitly_editable.get("survey_time", "1") == "1"

        aliases = {
            item.attrib["field"]: item.attrib["name"]
            for item in layer.findall("./aliases/alias")
        }
        assert aliases["operation"] == "变更操作"

        operation_widget = layer.find(
            "./fieldConfiguration/field[@name='operation']/editWidget"
        )
        assert operation_widget is not None
        assert operation_widget.attrib["type"] == "ValueMap"
        value_map = operation_widget.find("./config/Option/Option[@name='map']")
        assert value_map is not None
        values = {
            item.attrib["name"]: item.attrib["value"]
            for item in value_map.findall(".//Option[@name][@value]")
        }
        assert values == {"新增或更新": "upsert", "删除": "delete"}

    # Entity batches are independent: lookup relations may target the published river
    # reference but must never imply that a child batch owns a same-batch staging river.
    relations = _project_root().findall("./relations/relation")
    assert len(relations) == 3
    native_to_logical = _native_to_logical_layer_ids(_project_root())
    assert {
        native_to_logical[relation.attrib["referencingLayer"]]
        for relation in relations
    } == {
        "stg_cross_section",
        "stg_gate",
        "stg_pump",
    }
    assert all(
        native_to_logical[relation.attrib["referencedLayer"]] == "ref_river"
        for relation in relations
    )
    assert all(
        relation.find("fieldRef").attrib
        == {"referencingField": "river_code", "referencedField": "code"}
        for relation in relations
    )


def test_canonical_qml_set_and_quality_categories() -> None:
    style_names = {path.name for path in STYLE_ROOT.glob("*.qml")}
    assert STAGING_STYLE_FILES | PUBLISH_STYLE_FILES <= style_names

    expected_markers = {
        "staging_cross_section.qml": "circle",
        "staging_gate.qml": "square",
        "staging_pump.qml": "triangle",
    }
    for filename in STAGING_STYLE_FILES:
        root = ET.parse(STYLE_ROOT / filename).getroot()
        renderer = root.find("renderer-v2")
        assert renderer.attrib["type"] == "categorizedSymbol"
        assert renderer.attrib["attr"] == "quality_status"
        values = {
            category.attrib["value"]
            for category in renderer.findall("./categories/category")
        }
        assert values == {"pending", "passed", "failed"}
        if filename in expected_markers:
            assert expected_markers[filename] in (STYLE_ROOT / filename).read_text(
                encoding="utf-8"
            )


def test_pg_service_example_is_credential_free() -> None:
    text = SERVICE_EXAMPLE.read_text(encoding="utf-8")
    assert "[dayu_qgis]" in text
    assert "dbname=dayu_tiangong" in text
    assert "user=dayu_qgis_editor" in text
    assert not SECRET_ASSIGNMENT.search(text)


def test_readme_documents_database_owned_staging_provenance() -> None:
    text = (QGIS_ROOT / "README.md").read_text(encoding="utf-8")
    assert "数据库批次溯源触发器" in text
    assert "source_crs" in text
    assert "source_hash" in text
    assert "operator" in text
    assert "survey_time" in text
    assert "gis_import_batch" in text


def test_qgis_process_is_available_when_running_optional_smoke() -> None:
    executable = (
        os.getenv("QGIS_PROCESS_EXECUTABLE")
        or shutil.which("qgis_process")
        or shutil.which("qgis_process-qgis-ltr")
    )
    if executable is None:
        pytest.skip("qgis_process is not installed; static QGIS contracts remain authoritative")
    command = [executable, "--version"]
    if os.name == "nt" and Path(executable).suffix.lower() in {".bat", ".cmd"}:
        command = [os.environ.get("COMSPEC", "cmd.exe"), "/d", "/c", *command]
    result = subprocess.run(
        command,
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
