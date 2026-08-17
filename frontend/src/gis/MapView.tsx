import { Alert, Spin } from 'antd';
import OlMap from 'ol/Map';
import View from 'ol/View';
import TileLayer from 'ol/layer/Tile';
import TileWMS from 'ol/source/TileWMS';
import { defaults as defaultControls, ScaleLine } from 'ol/control';
import type { MapBrowserEvent } from 'ol';
import { useCallback, useEffect, useRef, useState } from 'react';
import 'ol/ol.css';
import { getGISCatalog, getGISFeatureInfo, type GISCatalogResponse } from '../api/generated/client';
import { Coordinate } from './Coordinate';
import { LayerManager, type WebLayerState } from './LayerManager';
import { Popup, type PopupSelection } from './Popup';

interface RuntimeLayer {
  state: WebLayerState;
  layer: TileLayer<TileWMS>;
}

/** Create one version-filtered GeoServer WMS source through the FastAPI gateway. */
function createRuntimeLayer(catalog: GISCatalogResponse, layerState: WebLayerState): RuntimeLayer {
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
export function MapView({ datasetVersionId }: { datasetVersionId: number }) {
  const targetRef = useRef<HTMLDivElement | null>(null);
  const mapRef = useRef<OlMap | null>(null);
  const runtimeRef = useRef<Map<string, RuntimeLayer>>(new Map());
  const identifyRef = useRef<(event: MapBrowserEvent<PointerEvent | KeyboardEvent | WheelEvent>) => void>(() => undefined);
  const [catalog, setCatalog] = useState<GISCatalogResponse | null>(null);
  const [layers, setLayers] = useState<WebLayerState[]>([]);
  const [coordinate, setCoordinate] = useState<[number, number] | null>(null);
  const [selection, setSelection] = useState<PopupSelection | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  useEffect(() => {
    if (!targetRef.current) return;
    const map = new OlMap({
      target: targetRef.current,
      layers: [],
      controls: defaultControls({ rotate: false }).extend([new ScaleLine({ units: 'metric' })]),
      view: new View({ center: [13_355_200, 3_543_900], zoom: 10, minZoom: 3, maxZoom: 20, projection: 'EPSG:3857' }),
    });
    map.on('pointermove', (event) => setCoordinate([event.coordinate[0], event.coordinate[1]]));
    map.on('singleclick', (event) => identifyRef.current(event));
    mapRef.current = map;
    return () => { map.setTarget(undefined); mapRef.current = null; };
  }, []);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError('');
    setSelection(null);
    void getGISCatalog(datasetVersionId)
      .then((nextCatalog) => {
        if (cancelled) return;
        const basemapOpacity = new Map<string, number>();
        nextCatalog.basemaps.forEach((item) => {
          if (item.layer_key) basemapOpacity.set(item.layer_key, item.opacity ?? 1);
        });
        const initialLayers = [...nextCatalog.layers]
          .sort((left, right) => {
            if (basemapOpacity.has(left.key)) return -1;
            if (basemapOpacity.has(right.key)) return 1;
            return left.order - right.order;
          })
          .map<WebLayerState>((layer) => ({
            key: layer.key,
            title: layer.title,
            groupTitle: layer.group_title,
            visible: basemapOpacity.has(layer.key) || layer.default_visible,
            opacity: basemapOpacity.get(layer.key) ?? layer.default_opacity,
            identifyEnabled: layer.identify_enabled,
          }));
        setCatalog(nextCatalog);
        setLayers(initialLayers);
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
  }, [catalog, datasetVersionId]);

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

  return (
    <section className="ol-map-shell panel-surface">
      <div ref={targetRef} className="ol-map" aria-label="OpenLayers GIS 地图" />
      {loading && <div className="ol-map-state"><Spin /><span>正在加载 PostGIS Catalog…</span></div>}
      {error && <Alert className="ol-map-error" type="error" showIcon message="WebGIS 加载失败" description={error} />}
      {!loading && !error && <LayerManager
        layers={layers}
        onVisibility={(key, visible) => updateLayer(key, (layer) => ({ ...layer, visible }))}
        onOpacity={(key, opacity) => updateLayer(key, (layer) => ({ ...layer, opacity }))}
        onMove={moveLayer}
      />}
      <Coordinate coordinate={coordinate} />
      <Popup selection={selection} onClose={() => setSelection(null)} />
      <div className="ol-map-contract">PostGIS · GeoServer · OpenLayers | Web CRS EPSG:3857</div>
    </section>
  );
}
