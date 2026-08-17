"""Static gates for the OpenLayers-only WebGIS cutover."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MAP_VIEW = ROOT / "frontend/src/gis/MapView.tsx"
GIS_PAGE = ROOT / "frontend/src/pages/GisPage.tsx"
LAYER_MANAGER = ROOT / "frontend/src/gis/LayerManager.tsx"
GENERATED = ROOT / "frontend/src/api/generated/client.ts"
GENERATOR = ROOT / "frontend/scripts/update-openapi.mjs"


def test_minimal_openlayers_components_exist_and_use_catalog() -> None:
    for relative in (
        "frontend/src/gis/MapView.tsx",
        "frontend/src/gis/LayerManager.tsx",
        "frontend/src/gis/Popup.tsx",
        "frontend/src/gis/StyleManager.ts",
        "frontend/src/gis/Coordinate.tsx",
    ):
        assert (ROOT / relative).is_file()
    map_source = MAP_VIEW.read_text(encoding="utf-8")
    assert "from 'ol/Map'" in map_source
    assert "new TileWMS" in map_source
    assert "projection: 'EPSG:3857'" in map_source
    assert "getGISCatalog" in map_source
    assert "getGISFeatureInfo" in map_source
    assert "fetch(" not in map_source


def test_frontend_has_one_renderer_and_no_business_layer_catalog() -> None:
    combined = "\n".join(path.read_text(encoding="utf-8") for path in (MAP_VIEW, GIS_PAGE, LAYER_MANAGER))
    for forbidden in (
        "Cesium",
        "QGIS Server",
        "MARTIN_MVT",
        "TITILER",
        "WORLD_IMAGERY_URL",
        "services.arcgisonline.com",
        "staticLayerKeys",
    ):
        assert forbidden not in combined
    assert "nextCatalog.layers" in MAP_VIEW.read_text(encoding="utf-8")
    assert "layers].reverse().map" in LAYER_MANAGER.read_text(encoding="utf-8")


def test_layer_controls_cover_visibility_opacity_order_and_identify() -> None:
    manager = LAYER_MANAGER.read_text(encoding="utf-8")
    map_source = MAP_VIEW.read_text(encoding="utf-8")
    for token in ("onVisibility", "onOpacity", "onMove"):
        assert token in manager
    assert "setVisible" in map_source
    assert "setOpacity" in map_source
    assert "setZIndex" in map_source
    assert "singleclick" in map_source
    assert "response.features" in map_source


def test_openapi_generator_owns_catalog_and_feature_info_clients() -> None:
    generator = GENERATOR.read_text(encoding="utf-8")
    generated = GENERATED.read_text(encoding="utf-8")
    for path in ("/api/v1/gis/catalog", "/api/v1/gis/layers", "/api/v1/gis/feature-info"):
        assert path in generator and path in generated
    for function_name in ("getGISCatalog", "getGISLayers", "getGISFeatureInfo"):
        assert f"export const {function_name}" in generator
        assert f"export const {function_name}" in generated
    for forbidden in ("getQgisServerHealth", "getQgisWmsFeatureInfo", "/qgis-server/wms"):
        assert forbidden not in generator
        assert forbidden not in generated
