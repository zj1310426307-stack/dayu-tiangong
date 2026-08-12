"""Idempotently provision the read-only GeoServer catalog for Phase 1A."""

from __future__ import annotations

import base64
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path
from xml.sax.saxutils import escape

import psycopg
from psycopg import sql


WORKSPACE = os.getenv("GEOSERVER_WORKSPACE", "dayu")
DATASTORE = os.getenv("GEOSERVER_DATASTORE", "dayu_postgis")
GEOSERVER_URL = os.getenv("GEOSERVER_INTERNAL_URL", "http://geoserver:8080/geoserver").rstrip("/")
ADMIN_USER = os.getenv("GEOSERVER_ADMIN_USER", "admin")
ADMIN_PASSWORD = os.environ["GEOSERVER_ADMIN_PASSWORD"]
READONLY_USER = os.getenv("GEOSERVER_DB_USER", "dayu_geoserver")
READONLY_PASSWORD = os.environ["GEOSERVER_DB_PASSWORD"]
STYLE_DIRECTORY = Path(__file__).resolve().parent / "styles"
SRID = 4490

LAYER_TITLES = {
    "river": "河道",
    "river_segment": "河段",
    "river_node": "河网节点",
    "cross_section": "横断面",
    "gate": "闸门",
    "pump": "泵站",
}
CACHED_LAYERS = {"river", "river_segment", "gate", "pump"}


def _require_identifier(value: str, label: str) -> str:
    """Reject unsafe SQL/catalog identifiers before using them in provisioning."""

    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", value):
        raise ValueError(f"{label} contains unsupported characters")
    return value


def _configure_database_role() -> None:
    """Create or rotate the login and apply defense-in-depth read-only grants."""

    admin_user = _require_identifier(os.getenv("POSTGRES_USER", "dayu"), "POSTGRES_USER")
    role_name = _require_identifier(READONLY_USER, "GEOSERVER_DB_USER")
    database_name = _require_identifier(os.getenv("POSTGRES_DB", "dayu_tiangong"), "POSTGRES_DB")
    connection = psycopg.connect(
        host=os.getenv("POSTGRES_HOST", "database"),
        port=int(os.getenv("POSTGRES_PORT", "5432")),
        dbname=database_name,
        user=admin_user,
        password=os.environ["POSTGRES_PASSWORD"],
        autocommit=True,
    )
    with connection, connection.cursor() as cursor:
        exists = cursor.execute(
            "SELECT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = %s)",
            (role_name,),
        ).fetchone()[0]
        if not exists:
            cursor.execute(
                sql.SQL(
                    "CREATE ROLE {} LOGIN PASSWORD {} NOSUPERUSER NOCREATEDB "
                    "NOCREATEROLE NOINHERIT NOREPLICATION"
                ).format(sql.Identifier(role_name), sql.Literal(READONLY_PASSWORD))
            )
        else:
            cursor.execute(
                sql.SQL(
                    "ALTER ROLE {} WITH LOGIN PASSWORD {} NOSUPERUSER NOCREATEDB "
                    "NOCREATEROLE NOINHERIT NOREPLICATION"
                ).format(sql.Identifier(role_name), sql.Literal(READONLY_PASSWORD))
            )

        cursor.execute(sql.SQL("REVOKE {} FROM CURRENT_USER").format(sql.Identifier(role_name)))
        role = sql.Identifier(role_name)
        database = sql.Identifier(database_name)
        owner = sql.Identifier(admin_user)
        cursor.execute(sql.SQL("ALTER ROLE {} SET default_transaction_read_only = on").format(role))
        cursor.execute(sql.SQL("REVOKE ALL ON DATABASE {} FROM {}").format(database, role))
        cursor.execute(sql.SQL("GRANT CONNECT ON DATABASE {} TO {}").format(database, role))
        cursor.execute(sql.SQL("REVOKE CREATE ON SCHEMA public FROM {}").format(role))
        cursor.execute(sql.SQL("GRANT USAGE ON SCHEMA public TO {}").format(role))
        cursor.execute(sql.SQL("GRANT SELECT ON ALL TABLES IN SCHEMA public TO {}").format(role))
        cursor.execute(sql.SQL("GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO {}").format(role))
        cursor.execute(
            sql.SQL("ALTER DEFAULT PRIVILEGES FOR ROLE {} IN SCHEMA public GRANT SELECT ON TABLES TO {}").format(
                owner, role
            )
        )
        cursor.execute(sql.SQL("REVOKE ALL ON ALL SEQUENCES IN SCHEMA public FROM {}").format(role))
        cursor.execute(sql.SQL("GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO {}").format(role))
        cursor.execute(
            sql.SQL(
                "ALTER DEFAULT PRIVILEGES FOR ROLE {} IN SCHEMA public "
                "GRANT USAGE, SELECT ON SEQUENCES TO {}"
            ).format(owner, role)
        )
        cursor.execute(sql.SQL("REVOKE ALL ON ALL TABLES IN SCHEMA public FROM {}").format(role))
        cursor.execute(sql.SQL("GRANT SELECT ON ALL TABLES IN SCHEMA public TO {}").format(role))


def _request(
    path: str,
    *,
    method: str = "GET",
    body: str | bytes | None = None,
    content_type: str | None = None,
    accept: str = "application/xml",
    allow_not_found: bool = False,
) -> tuple[int, bytes]:
    """Call the private GeoServer management API with bounded timeouts."""

    payload = body.encode("utf-8") if isinstance(body, str) else body
    request = urllib.request.Request(f"{GEOSERVER_URL}{path}", data=payload, method=method)
    token = base64.b64encode(f"{ADMIN_USER}:{ADMIN_PASSWORD}".encode()).decode()
    request.add_header("Authorization", f"Basic {token}")
    request.add_header("Accept", accept)
    if content_type:
        request.add_header("Content-Type", content_type)
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            return response.status, response.read()
    except urllib.error.HTTPError as exc:
        if allow_not_found and exc.code == 404:
            return exc.code, exc.read()
        detail = exc.read().decode("utf-8", errors="replace")[:500]
        raise RuntimeError(f"GeoServer {method} {path} failed: {exc.code} {detail}") from exc


def _exists(path: str) -> bool:
    """Return whether a GeoServer catalog resource already exists."""

    status, _ = _request(path, allow_not_found=True)
    return status != 404


def _wait_for_geoserver() -> None:
    """Wait for the authenticated catalog endpoint to accept requests."""

    last_error: Exception | None = None
    for _ in range(40):
        try:
            _request("/rest/about/status.xml")
            return
        except Exception as exc:  # noqa: BLE001 - retry boundary records the final cause.
            last_error = exc
            time.sleep(3)
    raise RuntimeError("GeoServer did not become ready") from last_error


def _ensure_workspace() -> None:
    """Create the dayu workspace once and preserve it across data-volume reuse."""

    path = f"/rest/workspaces/{urllib.parse.quote(WORKSPACE)}.xml?quietOnNotFound=true"
    if _exists(path):
        return
    _request(
        "/rest/workspaces",
        method="POST",
        body=f"<workspace><name>{WORKSPACE}</name></workspace>",
        content_type="application/xml",
    )


def _ensure_datastore() -> None:
    """Point GeoServer at the only PostGIS database using the read-only login."""

    db_host = escape(os.getenv("GEOSERVER_DB_HOST", "database"))
    db_port = escape(os.getenv("POSTGRES_PORT", "5432"))
    db_name = escape(os.getenv("POSTGRES_DB", "dayu_tiangong"))
    db_user = escape(READONLY_USER)
    db_password = escape(READONLY_PASSWORD)
    body = f"""<dataStore>
  <name>{DATASTORE}</name>
  <enabled>true</enabled>
  <connectionParameters>
    <entry key="host">{db_host}</entry>
    <entry key="port">{db_port}</entry>
    <entry key="database">{db_name}</entry>
    <entry key="schema">public</entry>
    <entry key="user">{db_user}</entry>
    <entry key="passwd">{db_password}</entry>
    <entry key="dbtype">postgis</entry>
    <entry key="Expose primary keys">true</entry>
    <entry key="validate connections">true</entry>
    <entry key="Loose bbox">true</entry>
    <entry key="preparedStatements">true</entry>
  </connectionParameters>
</dataStore>"""
    resource = f"/rest/workspaces/{WORKSPACE}/datastores/{DATASTORE}.xml"
    method = "PUT" if _exists(f"{resource}?quietOnNotFound=true") else "POST"
    target = resource if method == "PUT" else f"/rest/workspaces/{WORKSPACE}/datastores"
    _request(target, method=method, body=body, content_type="application/xml")


def _ensure_style(name: str) -> None:
    """Upload one workspace-scoped SLD and keep source-controlled styling authoritative."""

    resource = f"/rest/workspaces/{WORKSPACE}/styles/{urllib.parse.quote(name)}"
    sld = (STYLE_DIRECTORY / f"{name}.sld").read_bytes()
    if not _exists(f"{resource}.xml?quietOnNotFound=true"):
        _request(
            f"/rest/workspaces/{WORKSPACE}/styles?name={urllib.parse.quote(name)}",
            method="POST",
            body=sld,
            content_type="application/vnd.ogc.sld+xml",
        )
    else:
        _request(
            resource,
            method="PUT",
            body=sld,
            content_type="application/vnd.ogc.sld+xml",
        )


def _ensure_feature_type(name: str, title: str) -> None:
    """Publish one existing PostGIS table without creating or mutating source data."""

    base = f"/rest/workspaces/{WORKSPACE}/datastores/{DATASTORE}/featuretypes"
    resource = f"{base}/{urllib.parse.quote(name)}.xml"
    if not _exists(f"{resource}?quietOnNotFound=true"):
        _request(
            base,
            method="POST",
            body=(
                f"<featureType><name>{name}</name><nativeName>{name}</nativeName>"
                f"<title>{title}</title><srs>EPSG:{SRID}</srs>"
                "<projectionPolicy>FORCE_DECLARED</projectionPolicy><enabled>true</enabled></featureType>"
            ),
            content_type="application/xml",
        )
    qualified = urllib.parse.quote(f"{WORKSPACE}:{name}", safe="")
    _request(
        f"/rest/layers/{qualified}.xml",
        method="PUT",
        body=(
            "<layer><enabled>true</enabled><defaultStyle>"
            f"<name>{name}</name><workspace><name>{WORKSPACE}</name></workspace>"
            "</defaultStyle></layer>"
        ),
        content_type="application/xml",
    )


def _configure_read_only_wfs() -> None:
    """Expose Basic WFS querying while removing WFS-T transaction operations."""

    _request(
        "/rest/services/wfs/settings.xml",
        method="PUT",
        body="<wfs><enabled>true</enabled><serviceLevel>BASIC</serviceLevel></wfs>",
        content_type="application/xml",
    )


def _configure_cache(name: str) -> None:
    """Enable WMTS and isolate cached tiles by normalized dataset version CQL."""

    qualified = f"{WORKSPACE}:{name}"
    resource = f"/gwc/rest/layers/{urllib.parse.quote(qualified, safe='')}.xml"
    if name not in CACHED_LAYERS:
        if _exists(resource):
            _request(resource, method="DELETE")
        return
    body = f"""<GeoServerLayer>
  <enabled>true</enabled>
  <name>{qualified}</name>
  <mimeFormats><string>image/png</string></mimeFormats>
  <gridSubsets>
    <gridSubset><gridSetName>EPSG:4326</gridSetName><zoomStart>0</zoomStart><zoomStop>20</zoomStop></gridSubset>
    <gridSubset><gridSetName>EPSG:900913</gridSetName><zoomStart>0</zoomStart><zoomStop>22</zoomStop></gridSubset>
  </gridSubsets>
  <metaWidthHeight><int>4</int><int>4</int></metaWidthHeight>
  <parameterFilters>
    <regexParameterFilter>
      <key>CQL_FILTER</key>
      <defaultValue>dataset_version_id=1</defaultValue>
      <regex>dataset_version_id=[1-9][0-9]*</regex>
    </regexParameterFilter>
  </parameterFilters>
  <gutter>16</gutter>
  <autoCacheStyles>true</autoCacheStyles>
</GeoServerLayer>"""
    _request(resource, method="PUT", body=body, content_type="application/xml")


def _validate_public_services() -> None:
    """Verify WMS, WMTS, and read-only WFS contracts before releasing dependents."""

    expected = set(LAYER_TITLES)
    wms_path = f"/{WORKSPACE}/wms?service=WMS&version=1.3.0&request=GetCapabilities"
    _, wms = _request(wms_path)
    wms_root = ET.fromstring(wms)
    names = {node.text.split(":")[-1] for node in wms_root.iter() if node.tag.endswith("Name") and node.text}
    missing = expected - names
    if missing:
        raise RuntimeError(f"WMS capabilities missing layers: {sorted(missing)}")

    _, wmts = _request("/gwc/service/wmts?service=WMTS&version=1.0.0&request=GetCapabilities")
    wmts_text = wmts.decode("utf-8", errors="replace")
    missing_cache = {name for name in CACHED_LAYERS if f"{WORKSPACE}:{name}" not in wmts_text}
    if missing_cache:
        raise RuntimeError(f"WMTS capabilities missing layers: {sorted(missing_cache)}")

    _, wfs = _request(f"/{WORKSPACE}/ows?service=WFS&version=2.0.0&request=GetCapabilities")
    wfs_root = ET.fromstring(wfs)
    operations = {
        node.attrib.get("name")
        for node in wfs_root.iter()
        if node.tag.endswith("Operation") and node.attrib.get("name")
    }
    if "Transaction" in operations or "LockFeature" in operations:
        raise RuntimeError("WFS-T is enabled; Phase 1A requires Basic read-only WFS")


def main() -> None:
    """Run the complete Phase 1A provisioning sequence."""

    _configure_database_role()
    _wait_for_geoserver()
    _ensure_workspace()
    _ensure_datastore()
    for layer_name in LAYER_TITLES:
        _ensure_style(layer_name)
        _ensure_feature_type(layer_name, LAYER_TITLES[layer_name])
        _configure_cache(layer_name)
    _configure_read_only_wfs()
    _validate_public_services()
    print(
        f"GeoServer bootstrap complete: workspace={WORKSPACE}, "
        f"layers={len(LAYER_TITLES)}, cached={len(CACHED_LAYERS)}, srid=EPSG:{SRID}"
    )


if __name__ == "__main__":
    main()
