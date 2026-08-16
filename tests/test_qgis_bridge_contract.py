"""Offline security and lifecycle checks for the thin QGIS bridge."""

import importlib.util
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
PLUGIN = ROOT / "qgis/plugins/dayu_tiangong_bridge"


def _api_module():
    spec = importlib.util.spec_from_file_location("dayu_bridge_api", PLUGIN / "api_client.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_plugin_metadata_targets_qgis_344_and_is_not_server_plugin() -> None:
    value = (PLUGIN / "metadata.txt").read_text(encoding="utf-8")
    assert "qgisMinimumVersion=3.44" in value
    assert "server=False" in value
    assert "hasProcessingProvider=False" in value


def test_production_mutation_fails_closed_without_iam() -> None:
    api = _api_module()
    client = api.BridgeApiClient("https://dayu.example", token=None, mode="production")
    assert client.identity_label == "UNVERIFIED LOCAL IDENTITY"
    assert client.mutation_allowed is False
    with pytest.raises(api.BridgeError, match="PRODUCTION_MUTATION_REQUIRES_IAM"):
        client.post("validate", batch_id=1)


def test_api_routes_are_allowlisted_and_deep_link_uses_stable_identity() -> None:
    api = _api_module()
    client = api.BridgeApiClient("http://127.0.0.1:8001", mode="demo")
    with pytest.raises(api.BridgeError, match="allow-list"):
        client.get("admin", batch_id=1)
    assert api.GET_ROUTES["health"] == "/api/v1/health"
    assert client.deep_link(7, "river", 12) == "http://127.0.0.1:8001/gis?datasetVersionId=7&selectedAsset=river%3A12"
    source = (PLUGIN / "api_client.py").read_text(encoding="utf-8")
    assert "psycopg" not in source and "sqlalchemy" not in source
    assert "/rest" not in source and "/admin" not in source


def test_issue_layer_is_private_memory_only_with_exact_severities() -> None:
    source = (PLUGIN / "issue_layer.py").read_text(encoding="utf-8")
    assert '"error": "ERROR"' in source
    assert '"warning": "WARNING"' in source
    assert '"info": "INFO"' in source
    assert "CRITICAL" not in source
    assert '"memory"' in source
    assert "MapLayerFlag.Private" in source
    assert "removeMapLayer" in source


def test_bridge_shows_review_publish_and_locates_only_latest_run_issues() -> None:
    source = (PLUGIN / "dock.py").read_text(encoding="utf-8")
    assert "self.validation_status" in source
    assert "self.review_status" in source
    assert "self.publication_status" in source
    assert "validation_run_id" in source and "run_id" in source
    assert "source_feature_id" in source
    assert "QgsHighlight" in source
    assert "expected_batch" in source
    assert 'self.client.get("health")' in source
    assert "exc.status_code != 404" in source
    assert "批次不存在" in source


def test_plugin_tree_contains_no_secrets_or_personal_paths() -> None:
    combined = "\n".join(
        path.read_text(encoding="utf-8")
        for path in PLUGIN.rglob("*")
        if path.is_file() and path.suffix.lower() in {".py", ".txt", ".md"}
    )
    lowered = combined.lower()
    for forbidden in ("password=", "token=", "authcfg=", "c:\\users", "d:\\ch", "/home/"):
        assert forbidden not in lowered


def test_windows_launcher_installs_and_starts_the_bundled_bridge() -> None:
    launcher = (ROOT / "qgis/Start_Dayu_QGIS.ps1").read_text(encoding="utf-8")
    startup = (ROOT / "qgis/Start_Dayu_QGIS.py").read_text(encoding="utf-8")
    assert "Copy-Item -LiteralPath $pluginSource" in launcher
    assert '$probePath = "${driveRoot}${Probe}"' in launcher
    assert 'Start-Process -FilePath "cmd.exe" -ArgumentList $arguments -Wait' in launcher
    assert "-WindowStyle Hidden" not in launcher
    assert "--noplugins" not in launcher
    assert "--code S:\\qgis\\Start_Dayu_QGIS.py" in launcher
    assert "Start_Dayu_QGIS_Runtime.cmd" in launcher
    runtime = (ROOT / "qgis/Start_Dayu_QGIS_Runtime.cmd").read_text(encoding="utf-8")
    assert "start /B" not in runtime
    assert 'start "QGIS" /wait "%OSGEO4W_ROOT%\\bin\\qgis-ltr-bin.exe" %*' in runtime
    assert 'PLUGIN_ID = "dayu_tiangong_bridge"' in startup
    assert "loadPlugin(PLUGIN_ID)" in startup
    assert "startPlugin(PLUGIN_ID)" in startup
    assert "plugin.show_dock()" in startup
