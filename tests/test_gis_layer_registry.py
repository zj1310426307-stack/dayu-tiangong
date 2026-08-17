"""PostGIS Catalog schema, seed, and GeoServer permission contracts."""

from pathlib import Path

import pytest

from app.gis.models import GISCatalogLayer
from database.seed.gis_catalog import CATALOG_LAYERS, validate_gis_catalog


ROOT = Path(__file__).resolve().parents[1]


def _checks(model: type) -> str:
    return "\n".join(str(item.sqltext) for item in model.__table__.constraints if hasattr(item, "sqltext"))


def test_catalog_active_rows_are_geoserver_publish_wms_only() -> None:
    columns = GISCatalogLayer.__table__.columns
    assert {
        "layer_key",
        "source_schema",
        "source_relation",
        "service_mode",
        "render_mode",
        "dataset_filter_field",
        "capabilities",
        "active",
        "revision",
    } <= set(columns.keys())
    checks = _checks(GISCatalogLayer)
    for clause in (
        "active IS NOT TRUE OR source_schema = 'publish'",
        "active IS NOT TRUE OR service_mode = 'GEOSERVER_WMS'",
        "active IS NOT TRUE OR render_mode = 'RASTER_WMS'",
        "active IS NOT TRUE OR dataset_filter_field = 'dataset_version_id'",
    ):
        assert clause in checks


def test_seed_registers_exact_twelve_publish_layers() -> None:
    assert len(CATALOG_LAYERS) == 12
    keys = [row[0] for row in CATALOG_LAYERS]
    assert len(keys) == len(set(keys)) == 12
    assert {"river", "cross_section", "gate", "pump"} <= set(keys)
    source = (ROOT / "database/seed/gis_catalog.py").read_text(encoding="utf-8")
    seed_definition = source.split("def validate_gis_catalog", 1)[0]
    for forbidden in ("password=", "token=", "CQL_FILTER", "http://", "https://", "QGIS_WMS", "MARTIN_MVT"):
        assert forbidden not in seed_definition
    assert '"service_mode": "GEOSERVER_WMS"' in seed_definition
    assert '"source_schema": "publish"' in seed_definition


def test_runtime_catalog_validation_checks_sources_and_geoserver_role() -> None:
    class _Result:
        def __init__(self, value: bool) -> None:
            self.value = value

        def scalar_one(self) -> bool:
            return self.value

    class _Query:
        def filter(self, *_args):
            return self

        def order_by(self, *_args):
            return [
                type("Layer", (), {"layer_key": "river", "source_schema": "publish", "source_relation": "river"})(),
            ]

    class _Session:
        def __init__(self, answers: list[bool]) -> None:
            self.answers = iter(answers)

        def query(self, _model):
            return _Query()

        def execute(self, _statement, _params):
            return _Result(next(self.answers))

    assert validate_gis_catalog(_Session([True, True])) == {"sources": 1, "geoserver_permissions": 1}
    with pytest.raises(RuntimeError, match="lacks SELECT"):
        validate_gis_catalog(_Session([True, False]))


def test_gis_reset_migration_is_single_chain_head_parent() -> None:
    migration = (ROOT / "database/migrations/versions/20260817_0015_gis_reset_geoserver_catalog.py").read_text(encoding="utf-8")
    assert 'revision: str = "20260817_0015"' in migration
    assert 'down_revision: str | None = "20260815_0014"' in migration
    assert "ck_gis_catalog_active_service" in migration
    assert "service_mode = 'GEOSERVER_WMS'" in migration
