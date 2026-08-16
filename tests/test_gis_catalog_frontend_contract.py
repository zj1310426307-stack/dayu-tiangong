"""Static gates for the Catalog-driven frontend cutover."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CESIUM = ROOT / "frontend/src/components/gis/CesiumMap.tsx"
GIS_PAGE = ROOT / "frontend/src/pages/GisPage.tsx"
LAYER_MANAGER = ROOT / "frontend/src/components/gis/LayerManager.tsx"


def test_three_map_components_do_not_own_business_layer_catalogs() -> None:
    combined = "\n".join(path.read_text(encoding="utf-8") for path in (CESIUM, GIS_PAGE, LAYER_MANAGER))
    for forbidden in (
        "staticLayerKeys", "dynamicLayerKeys", "layerLabels", "layerGroups",
        "CACHED_LAYERS", "WORLD_IMAGERY_URL", "services.arcgisonline.com",
        "versionFilter(",
    ):
        assert forbidden not in combined
    assert "getGISCatalog" in CESIUM.read_text(encoding="utf-8")
    assert "items.map" in LAYER_MANAGER.read_text(encoding="utf-8")


def test_adapter_selection_is_protocol_based_and_exhaustive() -> None:
    registry = (ROOT / "frontend/src/gis/adapters/registry.ts").read_text(encoding="utf-8")
    expected = {
        "QGIS_WMS|RASTER_WMS", "GEOSERVER_WMS_LEGACY|RASTER_WMS",
        "GEOSERVER_WMS_LEGACY|RASTER_TILE", "MARTIN_MVT|VECTOR_TILE",
        "TITILER|RASTER_TILE", "FASTAPI|DYNAMIC_PRIMITIVE",
        "CESIUM_DYNAMIC|DYNAMIC_PRIMITIVE", "THREE_D_TILES|THREE_D",
    }
    for key in expected:
        assert key in registry
    assert "UNSUPPORTED_GIS_ADAPTER" in registry
    assert "layer.key ===" not in registry


def test_levee_fixture_requires_no_change_to_three_components() -> None:
    runtime = (ROOT / "frontend/src/gis/catalog/runtime.ts").read_text(encoding="utf-8")
    for path in (CESIUM, GIS_PAGE, LAYER_MANAGER):
        assert "levee" not in path.read_text(encoding="utf-8").lower()
    assert "catalog.layers.map" in runtime
    assert "layer.service_mode" in runtime and "layer.render_mode" in runtime


def test_runtime_has_race_and_symmetric_resource_guards() -> None:
    manager = (ROOT / "frontend/src/gis/runtime/manager.ts").read_text(encoding="utf-8")
    assert "const generation = ++this.generation" in manager
    assert "generation !== this.generation" in manager
    assert "Promise.allSettled" in manager
    assert "adapter.destroy" in manager
    assert "this.errors.set(layer.key" in manager


def test_openapi_generator_owns_catalog_client() -> None:
    generator = (ROOT / "frontend/scripts/update-openapi.mjs").read_text(encoding="utf-8")
    generated = (ROOT / "frontend/src/api/generated/client.ts").read_text(encoding="utf-8")
    for value in ("/api/v1/gis/catalog", "getGISCatalog", "GISCatalogResponse"):
        assert value in generator or value in generated
    assert "export const getGISCatalog" in generator
    assert "export const getGISCatalog" in generated


def test_qgis_feature_info_uses_generated_safe_gateway_client() -> None:
    helper = (ROOT / "frontend/src/gis/adapters/qgisFeatureInfo.ts").read_text(encoding="utf-8")
    generated = (ROOT / "frontend/src/api/generated/client.ts").read_text(encoding="utf-8")
    map_source = CESIUM.read_text(encoding="utf-8")
    assert "getQgisWmsFeatureInfo" in helper
    assert "request: 'GetFeatureInfo'" in helper
    assert "FILTER:" not in helper and "MAP:" not in helper
    assert "export const getQgisWmsFeatureInfo" in generated
    assert "identifyQgisLayer" in map_source
