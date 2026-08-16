"""Registry schema, seed, and immutable export contracts."""

from pathlib import Path

from app.gis.models import BasemapRegistry, GISLayerRegistry
from database.seed.gis_registry import (
    DYNAMIC_LAYERS,
    MARTIN_LAYERS,
    STATIC_LAYERS,
    validate_gis_registry,
)


ROOT = Path(__file__).resolve().parents[1]


def _checks(model: type) -> str:
    return "\n".join(str(item.sqltext) for item in model.__table__.constraints if hasattr(item, "sqltext"))


def test_registry_has_identity_and_fail_closed_constraints() -> None:
    columns = GISLayerRegistry.__table__.columns
    assert {"layer_key", "source_schema", "source_relation", "service_mode", "render_mode", "dataset_filter_field", "capabilities", "active", "revision"} <= set(columns.keys())
    checks = _checks(GISLayerRegistry)
    assert "source_schema IN ('publish','tiles')" in checks
    assert "service_mode = 'QGIS_WMS'" in checks
    assert "dataset_filter_field = 'dataset_version_id'" in checks
    assert "GEOSERVER_WMS_LEGACY" in checks and "MARTIN_MVT" in checks
    assert {"basemap_key", "endpoint_key", "basemap_type"} <= set(BasemapRegistry.__table__.columns.keys())


def test_seed_registers_current_assets_without_urls_or_queries() -> None:
    assert len(STATIC_LAYERS) == 12
    assert len(DYNAMIC_LAYERS) == 5
    assert len(MARTIN_LAYERS) == 5
    keys = [row[0] for row in (*STATIC_LAYERS, *DYNAMIC_LAYERS, *MARTIN_LAYERS)]
    assert len(keys) == len(set(keys)) == 22
    source = (ROOT / "database/seed/gis_registry.py").read_text(encoding="utf-8")
    seed_definition = source.split("def validate_gis_registry", 1)[0]
    for forbidden in ("password=", "token=", "SELECT ", "CQL_FILTER", "http://", "https://"):
        assert forbidden not in seed_definition


def test_export_snapshot_is_read_only_and_browser_secret_free() -> None:
    source = (ROOT / "qgis/server/export_registry_snapshot.py").read_text(encoding="utf-8")
    assert "WHERE active IS TRUE AND service_mode = 'QGIS_WMS'" in source
    assert "source_schema" in source and "feature_info_fields" in source
    assert "INSERT " not in source and "UPDATE " not in source and "DELETE " not in source
    assert "password=os.environ" in source
    assert '"password"' not in source


def test_registry_migration_is_single_chain_head_parent() -> None:
    migration = (ROOT / "database/migrations/versions/20260815_0013_gis_layer_registry.py").read_text(encoding="utf-8")
    assert 'revision: str = "20260815_0013"' in migration
    assert 'down_revision: str | None = "20260814_0012"' in migration
    assert "uq_gis_layer_registry_qgis_short_name" in migration
    assert "basemap_registry" in migration


def test_runtime_registry_validation_checks_sources_and_qgis_role() -> None:
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
                type("Layer", (), {
                    "layer_key": "river", "source_schema": "publish",
                    "source_relation": "river", "service_mode": "QGIS_WMS",
                })(),
                type("Layer", (), {
                    "layer_key": "river_mvt", "source_schema": "tiles",
                    "source_relation": "river", "service_mode": "MARTIN_MVT",
                })(),
            ]

    class _Session:
        def __init__(self, answers: list[bool]) -> None:
            self.answers = iter(answers)

        def query(self, _model):
            return _Query()

        def execute(self, _statement, _params):
            return _Result(next(self.answers))

    assert validate_gis_registry(_Session([True, True, True])) == {
        "sources": 2,
        "qgis_permissions": 1,
    }

    import pytest

    with pytest.raises(RuntimeError, match="lacks SELECT"):
        validate_gis_registry(_Session([True, False, True]))
