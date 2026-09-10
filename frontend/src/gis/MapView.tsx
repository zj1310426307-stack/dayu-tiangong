import { AimOutlined, AppstoreOutlined } from '@ant-design/icons';
import { Alert, Button, Spin } from 'antd';
import OlMap from 'ol/Map';
import View from 'ol/View';
import proj4 from 'proj4';
import Feature from 'ol/Feature';
import Point from 'ol/geom/Point';
import GeoJSON from 'ol/format/GeoJSON';
import TileLayer from 'ol/layer/Tile';
import VectorLayer from 'ol/layer/Vector';
import TileWMS from 'ol/source/TileWMS';
import VectorSource from 'ol/source/Vector';
import XYZ from 'ol/source/XYZ';
import { defaults as defaultControls, ScaleLine } from 'ol/control';
import { fromLonLat, toLonLat, transform } from 'ol/proj';
import { register } from 'ol/proj/proj4';
import { Circle as CircleStyle, Fill, Stroke, Style } from 'ol/style';
import type { MapBrowserEvent } from 'ol';
import { useCallback, useEffect, useRef, useState } from 'react';
import 'ol/ol.css';
import { getGISCatalog, getGISFeatureInfo, getHydraulicCrossSections, getPublishedScenarioGeoJSON, type GISCatalogResponse } from '../api/generated/client';
import { Coordinate } from './Coordinate';
import { CoordinateLocator, type CgcsCentralMeridian, type CoordinateInputMode } from './CoordinateLocator';
import { LayerManager, type WebLayerState } from './LayerManager';
import { Popup, type PopupSelection } from './Popup';

interface RuntimeLayer {
  state: WebLayerState;
  layer: TileLayer<TileWMS | XYZ>;
}

type MapTool = 'layers' | 'coordinates';

const CGCS2000_GAUSS_KRUGER: Record<CgcsCentralMeridian, { code: string; definition: string }> = {
  111: { code: 'EPSG:4546', definition: '+proj=tmerc +lat_0=0 +lon_0=111 +k=1 +x_0=500000 +y_0=0 +ellps=GRS80 +units=m +no_defs +type=crs' },
  114: { code: 'EPSG:4547', definition: '+proj=tmerc +lat_0=0 +lon_0=114 +k=1 +x_0=500000 +y_0=0 +ellps=GRS80 +units=m +no_defs +type=crs' },
  117: { code: 'EPSG:4548', definition: '+proj=tmerc +lat_0=0 +lon_0=117 +k=1 +x_0=500000 +y_0=0 +ellps=GRS80 +units=m +no_defs +type=crs' },
};

Object.values(CGCS2000_GAUSS_KRUGER).forEach(({ code, definition }) => proj4.defs(code, definition));
register(proj4);

/** Create one allow-listed imagery basemap or version-aware GeoServer WMS layer. */
function createRuntimeLayer(catalog: GISCatalogResponse, layerState: WebLayerState): RuntimeLayer {
  const basemap = catalog.basemaps.find((item) => `basemap:${item.basemap_key}` === layerState.key);
  if (basemap) {
    const source = new XYZ({
      url: basemap.endpoint,
      projection: 'EPSG:3857',
      minZoom: basemap.min_zoom,
      maxZoom: basemap.max_zoom,
      attributions: [basemap.credit],
      transition: 150,
    });
    return { state: layerState, layer: new TileLayer({ source }) };
  }
  const descriptor = catalog.layers.find((item) => item.key === layerState.key);
  if (!descriptor) throw new Error(`Catalog 图层不存在：${layerState.key}`);
  const source = new TileWMS({
    url: catalog.services[0]?.endpoint ?? '/api/v1/gis/ogc/wms',
    params: {
      LAYERS: descriptor.layer_name,
      VERSION: '1.1.1',
      FORMAT: 'image/png',
      TRANSPARENT: true,
      dataset_version_id: catalog.dataset.dataset_version_id,
      layer_key: descriptor.key,
    },
    projection: 'EPSG:3857',
    transition: 150,
  });
  return { state: layerState, layer: new TileLayer({ source }) };
}

/** Provide the only WebGIS map: OpenLayers + generated API client + GeoServer WMS. */
export function MapView({
  datasetVersionId,
  scenarioBundleId,
  scenarioId,
}: {
  datasetVersionId: number;
  scenarioBundleId?: string;
  scenarioId?: string;
}) {
  const targetRef = useRef<HTMLDivElement | null>(null);
  const mapRef = useRef<OlMap | null>(null);
  const runtimeRef = useRef<Map<string, RuntimeLayer>>(new Map());
  const locatorSourceRef = useRef<VectorSource | null>(null);
  const locatorLayerRef = useRef<VectorLayer<VectorSource> | null>(null);
  const scenarioLayerRef = useRef<VectorLayer<VectorSource> | null>(null);
  const hydraulicSectionLayerRef = useRef<VectorLayer<VectorSource> | null>(null);
  const identifyRef = useRef<(event: MapBrowserEvent<PointerEvent | KeyboardEvent | WheelEvent>) => void>(() => undefined);
  const [catalog, setCatalog] = useState<GISCatalogResponse | null>(null);
  const [layers, setLayers] = useState<WebLayerState[]>([]);
  const [longitudeLatitude, setLongitudeLatitude] = useState<[number, number] | null>(null);
  const [xy, setXy] = useState<[number, number] | null>(null);
  const [selection, setSelection] = useState<PopupSelection | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [activeTool, setActiveTool] = useState<MapTool | null>(null);

  useEffect(() => {
    if (!targetRef.current) return;
    const map = new OlMap({
      target: targetRef.current,
      layers: [],
      controls: defaultControls({ rotate: false }).extend([new ScaleLine({ units: 'metric' })]),
      view: new View({ center: fromLonLat([113.27, 23.13]), zoom: 7, minZoom: 3, maxZoom: 20, projection: 'EPSG:3857' }),
    });
    const locatorSource = new VectorSource();
    const locatorLayer = new VectorLayer({
      source: locatorSource,
      style: new Style({
        image: new CircleStyle({
          radius: 9,
          fill: new Fill({ color: 'rgba(255, 74, 92, 0.88)' }),
          stroke: new Stroke({ color: '#ffffff', width: 3 }),
        }),
      }),
    });
    locatorLayer.setZIndex(10_000);
    locatorSourceRef.current = locatorSource;
    locatorLayerRef.current = locatorLayer;
    map.addLayer(locatorLayer);
    const scenarioLayer = new VectorLayer({
      source: new VectorSource(),
      style: (feature) => {
        const velocity = Number(feature.get('velocity_m_s') ?? 0);
        const color = velocity >= 3 ? '#ff5c68' : velocity >= 1.5 ? '#ffc85c' : '#2fe6d6';
        return feature.getGeometry()?.getType() === 'LineString'
          ? new Style({ stroke: new Stroke({ color: '#2fe6d6', width: 4, lineDash: [10, 6] }) })
          : new Style({ image: new CircleStyle({ radius: 7, fill: new Fill({ color }), stroke: new Stroke({ color: '#ffffff', width: 2 }) }) });
      },
    });
    scenarioLayer.setZIndex(9_500);
    scenarioLayerRef.current = scenarioLayer;
    map.addLayer(scenarioLayer);
    const hydraulicSectionLayer = new VectorLayer({
      source: new VectorSource(),
      style: (feature) => {
        const overlayType = feature.get('overlay_type');
        if (overlayType === 'intersection') {
          return new Style({ image: new CircleStyle({ radius: 5, fill: new Fill({ color: '#ffffff' }), stroke: new Stroke({ color: '#00e5ff', width: 2 }) }) });
        }
        if (overlayType === 'marker') {
          const markerKind = feature.get('marker_kind');
          const color = markerKind === 'marker1' ? '#ff8a65' : markerKind === 'marker3' ? '#ba68c8' : '#ffd54f';
          return new Style({ image: new CircleStyle({ radius: 5, fill: new Fill({ color }), stroke: new Stroke({ color: '#101923', width: 1.5 }) }) });
        }
        return new Style({ stroke: new Stroke({ color: '#00e5ff', width: 2, lineDash: [8, 5] }) });
      },
    });
    hydraulicSectionLayer.setZIndex(9_700);
    hydraulicSectionLayerRef.current = hydraulicSectionLayer;
    map.addLayer(hydraulicSectionLayer);
    map.on('pointermove', (event) => {
      const [longitude, latitude] = toLonLat(event.coordinate);
      setLongitudeLatitude([longitude, latitude]);
      setXy([event.coordinate[0], event.coordinate[1]]);
    });
    map.on('singleclick', (event) => identifyRef.current(event));
    mapRef.current = map;
    return () => {
      map.setTarget(undefined);
      mapRef.current = null;
      locatorSourceRef.current = null;
      locatorLayerRef.current = null;
      scenarioLayerRef.current = null;
      hydraulicSectionLayerRef.current = null;
    };
  }, []);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError('');
    setSelection(null);
    if (!datasetVersionId) {
      setCatalog(null);
      setLayers([]);
      setLoading(false);
      return () => { cancelled = true; };
    }
    void getGISCatalog(datasetVersionId)
      .then((nextCatalog) => {
        if (cancelled) return;
        const basemapLayers = nextCatalog.basemaps.map<WebLayerState>((item) => ({
          key: `basemap:${item.basemap_key}`,
          title: item.title,
          groupTitle: '影像底图',
          visible: item.visible ?? true,
          opacity: item.opacity ?? 1,
          identifyEnabled: false,
        }));
        const businessLayers = [...nextCatalog.layers]
          .sort((left, right) => left.order - right.order)
          .map<WebLayerState>((layer) => ({
            key: layer.key,
            title: layer.title,
            groupTitle: layer.group_title,
            visible: layer.default_visible,
            opacity: layer.default_opacity,
            identifyEnabled: layer.identify_enabled,
          }));
        setCatalog(nextCatalog);
        setLayers([...basemapLayers, ...businessLayers]);
      })
      .catch((reason: unknown) => { if (!cancelled) setError(reason instanceof Error ? reason.message : 'GIS Catalog 加载失败'); })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [datasetVersionId]);

  useEffect(() => {
    const map = mapRef.current;
    if (!map || !catalog) return;
    map.getLayers().clear();
    runtimeRef.current.clear();
    layers.forEach((state, index) => {
      const runtime = createRuntimeLayer(catalog, state);
      runtime.layer.setVisible(state.visible);
      runtime.layer.setOpacity(state.opacity);
      runtime.layer.setZIndex(index);
      runtimeRef.current.set(state.key, runtime);
      map.addLayer(runtime.layer);
    });
    const locatorLayer = locatorLayerRef.current;
    if (locatorLayer) map.addLayer(locatorLayer);
    const scenarioLayer = scenarioLayerRef.current;
    if (scenarioLayer) map.addLayer(scenarioLayer);
    const hydraulicSectionLayer = hydraulicSectionLayerRef.current;
    if (hydraulicSectionLayer) map.addLayer(hydraulicSectionLayer);
  }, [catalog, datasetVersionId]);

  useEffect(() => {
    const layer = hydraulicSectionLayerRef.current;
    if (!layer) return;
    const source = layer.getSource();
    if (!source) return;
    source.clear();
    if (!datasetVersionId) return;
    void getHydraulicCrossSections({ dataset_version_id: datasetVersionId, limit: 1000 })
      .then((payload) => {
        const lines = new GeoJSON().readFeatures(payload, {
          dataProjection: 'EPSG:4490',
          featureProjection: 'EPSG:3857',
        });
        lines.forEach((line) => {
          line.set('overlay_type', 'cross_section');
          source.addFeature(line);
          const properties = line.getProperties() as Record<string, unknown>;
          const markers = (properties.markers ?? {}) as Record<string, { coordinates?: number[] }>;
          Object.entries(markers).forEach(([markerKind, marker]) => {
            const coordinates = marker.coordinates;
            if (!coordinates || coordinates.length < 2) return;
            const markerFeature = new Feature({
              geometry: new Point(transform([coordinates[0], coordinates[1]], 'EPSG:4490', 'EPSG:3857')),
              overlay_type: 'marker',
              marker_kind: markerKind,
              section_code: properties.section_code,
            });
            source.addFeature(markerFeature);
          });
          const intersection = properties.intersection_geometry as { coordinates?: number[] } | undefined;
          if (intersection?.coordinates && intersection.coordinates.length >= 2) {
            source.addFeature(new Feature({
              geometry: new Point(transform([intersection.coordinates[0], intersection.coordinates[1]], 'EPSG:4490', 'EPSG:3857')),
              overlay_type: 'intersection',
              section_code: properties.section_code,
            }));
          }
        });
      })
      .catch(() => {
        // WMS remains available when a draft has no hydraulic spatial overlay yet.
      });
  }, [datasetVersionId]);

  useEffect(() => {
    const map = mapRef.current;
    const layer = scenarioLayerRef.current;
    if (!map || !layer) return;
    const source = layer.getSource();
    if (!source) return;
    source.clear();
    if (!scenarioBundleId) return;
    void getPublishedScenarioGeoJSON(scenarioBundleId, scenarioId)
      .then((payload) => {
        const features = new GeoJSON().readFeatures(payload, {
          dataProjection: 'EPSG:4547',
          featureProjection: 'EPSG:3857',
        });
        source.addFeatures(features);
        const extent = source.getExtent();
        if (features.length > 0 && extent) map.getView().fit(extent, { padding: [80, 80, 80, 80], maxZoom: 15, duration: 500 });
      })
      .catch((reason) => setError(reason instanceof Error ? reason.message : '方案成果图层加载失败'));
  }, [scenarioBundleId, scenarioId]);

  useEffect(() => {
    layers.forEach((state, index) => {
      const runtime = runtimeRef.current.get(state.key);
      if (!runtime) return;
      runtime.state = state;
      runtime.layer.setVisible(state.visible);
      runtime.layer.setOpacity(state.opacity);
      runtime.layer.setZIndex(index);
    });
  }, [layers]);

  identifyRef.current = (event) => {
    const map = mapRef.current;
    if (!map || !catalog) return;
    const size = map.getSize();
    if (!size) return;
    const extent = map.getView().calculateExtent(size);
    const candidates = [...layers].reverse().filter((layer) => layer.visible && layer.identifyEnabled);
    void (async () => {
      setSelection(null);
      for (const layer of candidates) {
        try {
          const response = await getGISFeatureInfo({
            dataset_version_id: datasetVersionId,
            layer_key: layer.key,
            bbox: extent.join(','),
            width: size[0],
            height: size[1],
            x: Math.max(0, Math.min(size[0] - 1, Math.round(event.pixel[0]))),
            y: Math.max(0, Math.min(size[1] - 1, Math.round(event.pixel[1]))),
          });
          if (response.features.length > 0) {
            setSelection({ layerTitle: layer.title, pixel: [event.pixel[0], event.pixel[1]], features: response.features });
            return;
          }
        } catch {
          // A single unavailable layer must not disable inspection of the remaining Catalog.
        }
      }
      setSelection({ layerTitle: '点选查询', pixel: [event.pixel[0], event.pixel[1]], features: [] });
    })();
  };

  const updateLayer = useCallback((key: string, updater: (layer: WebLayerState) => WebLayerState) => {
    setLayers((current) => current.map((layer) => layer.key === key ? updater(layer) : layer));
  }, []);
  const moveLayer = useCallback((key: string, direction: -1 | 1) => {
    setLayers((current) => {
      const index = current.findIndex((layer) => layer.key === key);
      const target = index + direction;
      if (index < 0 || target < 0 || target >= current.length) return current;
      const next = [...current];
      [next[index], next[target]] = [next[target], next[index]];
      return next;
    });
  }, []);

  /** Convert the selected CRS to the Web view; UI CGCS2000 input uses X=easting, Y=northing. */
  const locateCoordinate = useCallback((first: number, second: number, mode: CoordinateInputMode, centralMeridian: CgcsCentralMeridian) => {
    const map = mapRef.current;
    const source = locatorSourceRef.current;
    if (!map || !source) return null;
    const cgcsProjection = CGCS2000_GAUSS_KRUGER[centralMeridian].code;
    const center = mode === 'lonlat'
      ? fromLonLat([first, second])
      : mode === 'webmercator'
        ? [first, second]
        : transform([first, second], cgcsProjection, 'EPSG:3857');
    source.clear();
    source.addFeature(new Feature({ geometry: new Point(center) }));
    setSelection(null);
    map.getView().animate({ center, zoom: 17, duration: 700 });
    const [longitude, latitude] = toLonLat(center);
    return [longitude, latitude] as [number, number];
  }, []);

  /** Clear the locator overlay without changing the current view or published layers. */
  const clearCoordinate = useCallback(() => locatorSourceRef.current?.clear(), []);

  /** Keep one compact map tool open at a time while preserving each mounted tool's state. */
  const toggleTool = useCallback((tool: MapTool) => {
    setActiveTool((current) => current === tool ? null : tool);
  }, []);

  return (
    <section className="ol-map-shell panel-surface">
      <div ref={targetRef} className="ol-map" aria-label="OpenLayers GIS 地图" />
      {loading && <div className="ol-map-state"><Spin /><span>正在加载 PostGIS Catalog…</span></div>}
      {error && <Alert className="ol-map-error" type="error" showIcon message="WebGIS 加载失败" description={error} />}
      {!loading && !error && <nav className="ol-map-tool-menu" aria-label="地图工具菜单">
        <Button
          size="small"
          type={activeTool === 'layers' ? 'primary' : 'default'}
          icon={<AppstoreOutlined />}
          aria-controls="gis-layer-tool"
          aria-expanded={activeTool === 'layers'}
          onClick={() => toggleTool('layers')}
        >图层管理</Button>
        <Button
          size="small"
          type={activeTool === 'coordinates' ? 'primary' : 'default'}
          icon={<AimOutlined />}
          aria-controls="gis-coordinate-tool"
          aria-expanded={activeTool === 'coordinates'}
          onClick={() => toggleTool('coordinates')}
        >坐标定位</Button>
      </nav>}
      {!loading && !error && <LayerManager
        layers={layers}
        onVisibility={(key, visible) => updateLayer(key, (layer) => ({ ...layer, visible }))}
        onOpacity={(key, opacity) => updateLayer(key, (layer) => ({ ...layer, opacity }))}
        onMove={moveLayer}
        hidden={activeTool !== 'layers'}
      />}
      {!loading && !error && <CoordinateLocator hidden={activeTool !== 'coordinates'} onLocate={locateCoordinate} onClear={clearCoordinate} />}
      <Coordinate longitudeLatitude={longitudeLatitude} xy={xy} />
      <Popup selection={selection} onClose={() => setSelection(null)} />
      <div className="ol-map-contract">Esri · Vantor · Earthstar Geographics · GIS User Community · © OpenStreetMap contributors · geoBoundaries · NASA GIBS</div>
    </section>
  );
}
