"""Offline security contracts for the private QGIS Server boundary."""

from pathlib import Path
import json
from types import SimpleNamespace

import pytest
import yaml


ROOT = Path(__file__).resolve().parents[1]


def test_compose_pins_private_read_only_qgis_server() -> None:
    compose = yaml.safe_load((ROOT / "docker/docker-compose.yml").read_text(encoding="utf-8"))
    server = compose["services"]["qgis-server"]
    assert server["image"] == "qgis/qgis-server:3.44.12-trixie"
    assert "ports" not in server
    assert server["read_only"] is True
    assert server["environment"]["QGIS_SERVER_DISABLE_GETPRINT"] == "true"
    assert server["environment"]["QGIS_SERVER_FORCE_READONLY_LAYERS"] == "true"
    assert "PGPASSWORD" not in server["environment"]
    assert server["secrets"] == ["qgis_server_db_password"]
    assert compose["secrets"]["qgis_server_db_password"]["file"] == (
        "${QGIS_SERVER_DB_PASSWORD_FILE:-../qgis/server/generated/qgis_server_db_password.secret}"
    )
    assert all(str(volume).endswith(":ro") for volume in server["volumes"])
    assert any("dayu-qgis.conf:/etc/nginx/qgis.d/dayu-qgis.conf:ro" in str(volume) for volume in server["volumes"])
    assert {
        "/tmp",
        "/var/tmp",
        "/run",
        "/var/lib/nginx",
        "/var/cache/nginx",
        "/var/cache/fontconfig",
        "/var/log/nginx",
    }.issubset(server["tmpfs"])


def test_nginx_routes_browser_through_fastapi_only() -> None:
    nginx = (ROOT / "docker/nginx.conf").read_text(encoding="utf-8")
    block = nginx.split("location /qgis-server/", 1)[1].split("}", 1)[0]
    assert "backend:8000/qgis-server/" in block
    assert "qgis-server:80" not in block


def test_private_fastcgi_location_propagates_fixed_project_and_service_paths() -> None:
    """Keep environment paths fixed without embedding credentials in Nginx."""

    config = (ROOT / "qgis/server/nginx/dayu-qgis.conf").read_text(encoding="utf-8")
    assert "location = /dayu-ows/" in config
    assert "QGIS_PROJECT_FILE /srv/qgis/dayu_tiangong_server.qgz" in config
    assert "PGSERVICEFILE /srv/qgis/pg_service.server.conf" in config
    assert "PGPASSFILE /tmp/dayu_qgis_server.pgpass" in config
    assert "password" not in config.lower()
    compose = yaml.safe_load((ROOT / "docker/docker-compose.yml").read_text(encoding="utf-8"))
    assert compose["services"]["backend"]["environment"]["QGIS_SERVER_INTERNAL_URL"] == "http://qgis-server/dayu-ows/"


def test_database_role_bootstraps_are_serialized() -> None:
    """Avoid concurrent PostgreSQL catalog updates during repeated Compose startup."""

    compose = yaml.safe_load((ROOT / "docker/docker-compose.yml").read_text(encoding="utf-8"))
    services = compose["services"]
    assert services["app-bootstrap"]["depends_on"]["qgis-bootstrap"]["condition"] == "service_completed_successfully"
    assert services["dgis-bootstrap"]["depends_on"]["app-bootstrap"]["condition"] == "service_completed_successfully"
    assert services["geoserver-init"]["depends_on"]["dgis-bootstrap"]["condition"] == "service_completed_successfully"


def test_gateway_synthesizes_filter_and_rejects_raw_controls(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.qgis_server import service

    monkeypatch.setattr(service, "_published_version", lambda session, version_id: object())
    monkeypatch.setattr(
        service,
        "_layers",
        lambda session, keys: [SimpleNamespace(qgis_short_name=key) for key in keys],
    )
    parameters = service.build_upstream_parameters(
        object(),
        {
            "request": "GetMap", "dataset_version_id": "7", "layer_keys": "river,gate",
            "bbox": "120,30,121,31", "width": "800", "height": "600",
            "crs": "EPSG:4490", "format": "image/png", "transparent": "true",
        },
    )
    assert parameters["LAYERS"] == "river,gate"
    assert parameters["FILTER"] == 'river:"dataset_version_id" = 7;gate:"dataset_version_id" = 7'
    assert parameters["BBOX"] == "30,120,31,121"
    for forbidden in ("MAP", "SQL", "CQL", "datasource", "url"):
        with pytest.raises(service.GovernanceError) as exc:
            service.build_upstream_parameters(object(), {"request": "GetCapabilities", forbidden: "x"})
        assert exc.value.code == "QGIS_PARAMETER_NOT_ALLOWED"


def test_qgis_server_database_role_is_fail_closed() -> None:
    source = (ROOT / "database/bootstrap_qgis.py").read_text(encoding="utf-8")
    assert 'QGIS_SERVER_RELATIONS = ("river", "cross_section", "gate", "pump")' in source
    assert "default_transaction_read_only = on" in source
    assert "_qualified_identifiers(\"publish\", QGIS_SERVER_RELATIONS)" in source
    assert "dayu_qgis_server" in source
    assert "search_path = publish, public, pg_catalog" in source
    assert "GRANT USAGE ON SCHEMA public" in source
    assert "_reset_role_privileges" in source


def test_server_service_file_contains_no_secret() -> None:
    value = (ROOT / "qgis/server/pg_service.server.conf").read_text(encoding="utf-8").lower()
    assert "password" not in value
    assert "authcfg" not in value
    assert "dayu_qgis_server" in value


def test_feature_info_pixel_and_runtime_isolation_evidence_are_strict(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from app.qgis_server import service

    monkeypatch.setattr(service, "_published_version", lambda session, version_id: object())
    monkeypatch.setattr(
        service,
        "_layers",
        lambda session, keys: [SimpleNamespace(qgis_short_name=key) for key in keys],
    )
    public = {
        "request": "GetFeatureInfo", "dataset_version_id": "7", "layer_key": "river",
        "bbox": "120,30,121,31", "width": "256", "height": "256",
        "crs": "EPSG:4490", "format": "image/png", "i": "256", "j": "10",
    }
    with pytest.raises(service.GovernanceError) as exc:
        service.build_upstream_parameters(object(), public)
    assert exc.value.code == "QGIS_PIXEL_INVALID"

    evidence_path = tmp_path / "isolation.json"
    evidence_path.write_text(json.dumps({
        "schema_version": "dayu-qgis-isolation-evidence/v1alpha1",
        "project_revision": "rev-a",
        "dataset_version_ids": [1, 2],
        "getmap_isolated": True,
        "feature_info_isolated": True,
    }), encoding="utf-8")
    monkeypatch.setenv("QGIS_SERVER_ISOLATION_EVIDENCE_PATH", str(evidence_path))
    assert service.read_isolation_evidence("rev-a").passed is True
    assert service.read_isolation_evidence("rev-b").passed is False


def test_runtime_verifier_uses_only_public_gateway_fields() -> None:
    source = (ROOT / "qgis/server/verify_runtime.py").read_text(encoding="utf-8")
    assert "GetMap" in source and "GetFeatureInfo" in source
    assert "getmap_isolated" in source and "feature_info_isolated" in source
    assert '"FILTER"' not in source and '"MAP"' not in source
    assert "temporary.replace(output)" in source
