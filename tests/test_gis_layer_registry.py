"""PostGIS Catalog schema, seed, and GeoServer permission contracts."""

from pathlib import Path

import pytest

from app.gis.models import GISCatalogLayer
from database.seed.gis_catalog import BASEMAPS, CATALOG_LAYERS, validate_gis_catalog


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
        "dataset_filter_field IS NULL OR dataset_filter_field = 'dataset_version_id'",
    ):
        assert clause in checks


def test_seed_registers_nine_truthful_publish_layers() -> None:
    assert len(CATALOG_LAYERS) == 9
    keys = [row[0] for row in CATALOG_LAYERS]
    assert len(keys) == len(set(keys)) == 9
    assert {"river", "cross_section", "gate", "pump"} <= set(keys)
    assert {"administrative_area", "road", "waterway"} <= set(keys)
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


def test_guangdong_open_data_migration_extends_the_single_head() -> None:
    migration = (ROOT / "database/migrations/versions/20260817_0016_guangdong_open_reference_data.py").read_text(encoding="utf-8")
    assert 'revision: str = "20260817_0016"' in migration
    assert 'down_revision: str | None = "20260817_0015"' in migration
    for token in ("reference_data", "administrative_area_open", "road_open", "waterway_open", "nasa_gibs_blue_marble"):
        assert token in migration


def test_high_resolution_imagery_is_the_single_visible_default() -> None:
    migration = (ROOT / "database/migrations/versions/20260817_0017_high_resolution_imagery.py").read_text(encoding="utf-8")
    assert 'revision: str = "20260817_0017"' in migration
    assert 'down_revision: str | None = "20260817_0016"' in migration
    assert "esri_world_imagery" in migration
    assert len(BASEMAPS) == 3
    defaults = {row[0]: row[5] for row in BASEMAPS}
    assert defaults == {
        "nasa_blue_marble": False,
        "nasa_viirs_true_color": False,
        "esri_world_imagery": True,
    }


def test_chinese_label_migration_extends_head_and_styles_use_reviewed_field() -> None:
    """Reference labels must be Chinese-first from DB through GeoServer styling."""

    migration = (ROOT / "database/migrations/versions/20260817_0018_chinese_map_labels.py").read_text(encoding="utf-8")
    assert 'revision: str = "20260817_0018"' in migration
    assert 'down_revision: str | None = "20260817_0017"' in migration
    assert "CHINESE_ADMIN_LABEL_MISSING" in migration
    assert "DROP VIEW publish." in migration
    for filename in (
        "administrative_area_open.sld",
        "road_open.sld",
        "waterway_open.sld",
    ):
        style = (ROOT / "geoserver/styles" / filename).read_text(encoding="utf-8")
        assert "<ogc:PropertyName>name_zh</ogc:PropertyName>" in style
        assert "Noto Sans CJK SC" in style


def test_geoserver_image_installs_cjk_font_and_compose_builds_it() -> None:
    """Chinese WMS labels require a deterministic server-side font package."""

    dockerfile = (ROOT / "docker/geoserver.Dockerfile").read_text(encoding="utf-8")
    compose = (ROOT / "docker/docker-compose.yml").read_text(encoding="utf-8")
    assert "fonts-noto-cjk" in dockerfile and "fc-cache -f" in dockerfile
    assert "dockerfile: docker/geoserver.Dockerfile" in compose
