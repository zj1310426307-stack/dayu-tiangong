# GeoServer Phase 1A

GeoServer publishes the six static PostGIS layers in workspace `dayu`. The source database remains the existing `dayu_tiangong` PostgreSQL/PostGIS instance; the bootstrap creates only a restricted login, not a second database.

- WMS: `/geoserver/dayu/wms`
- WMTS: `/geoserver/gwc/service/wmts`
- Basic WFS: `/geoserver/dayu/ows`
- private catalog/bootstrap: internal container network only; the frontend proxy rejects `/rest`, `/web`, and `/gwc/rest`

`bootstrap.py` is idempotent. It creates or rotates the read-only database login, provisions the workspace/store/styles/layers, restricts WFS to `BASIC`, configures four cached layers, and validates capabilities before the backend and frontend start.

Required secrets are supplied at runtime:

- `GEOSERVER_ADMIN_PASSWORD`
- `GEOSERVER_DB_PASSWORD`

Do not commit either value. For local Compose, set them in the shell or in an ignored `.env` file.

After Compose is healthy, run the real acceptance gate from the repository root:

```powershell
$env:GEOSERVER_DB_PASSWORD="the-local-read-only-secret"
backend\.venv\Scripts\python.exe geoserver\verify.py
```

The script validates WMS/WMTS capabilities and PNG payloads, Basic WFS, read-only SQL behavior, the GeoServer health/layer APIs, and preservation of FastAPI GIS queries.
