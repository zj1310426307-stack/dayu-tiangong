import { EnvironmentOutlined, ExpandOutlined, ReloadOutlined } from '@ant-design/icons';
import { Button, Tag, Tooltip } from 'antd';
import {
  Cartesian2, Cartesian3, Color, GridImageryProvider, MVTDataProvider,
  Math as CesiumMath, PointPrimitiveCollection, ScreenSpaceEventType,
  UrlTemplateImageryProvider, Viewer, type Cesium3DTileset, type ImageryLayer,
} from 'cesium';
import 'cesium/Build/Cesium/Widgets/widgets.css';
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  getGISAnnotations, getGISCatalog, getGISLayerCatalog,
  type GISCatalogResponse, type GISComparisonFrame, type GISInteractionFrame,
  type LocationSearchItem, type SpatialFeature,
} from '../../api/generated/client';
import { useDatasetVersion } from '../../context/DatasetVersionContext';
import { catalogMode, normalizeCatalog, shadowDifferences, type CatalogRuntime, type LayerRuntime } from '../../gis/catalog/runtime';
import { identifyQgisLayer } from '../../gis/adapters/qgisFeatureInfo';
import type { CatalogPick } from '../../gis/adapters/types';
import { GisAdapterRuntime } from '../../gis/runtime/manager';
import { parseFeatureIdentity, readFeatureDetail } from '../../gis/selection/identity';
import { AnnotationLayer } from './AnnotationLayer';
import { FeatureInspector, type SelectedGISFeature } from './FeatureInspector';
import { LayerManager } from './LayerManager';
import { ResultRenderer } from './ResultRenderer';
import { SearchBox } from './SearchBox';

type LoadState = 'loading' | 'ready' | 'error';
type BasemapState = 'loading' | 'imagery' | 'fallback';

interface CesiumMapProps {
  variant?: 'dashboard' | 'workspace';
  datasetVersionId?: number;
  interactionFrame?: GISInteractionFrame | null;
  dynamicLoading?: boolean;
  selectedAsset?: string;
  analysisFeatures?: SpatialFeature[];
  comparisonFrame?: GISComparisonFrame | null;
  dgisVectorTileSource?: string | null;
  dgisRasterTileUrl?: string | null;
  dgisThreeDTilesets?: Cesium3DTileset[];
  onViewportChange?: (bbox: [number, number, number, number]) => void;
  onCesiumStatusChange?: (online: boolean) => void;
}

interface LayerSetting { visible: boolean; opacity: number; }
interface LocationPick { kind: 'location'; item: LocationSearchItem; }

/** Use the same Catalog identities for rollback; only the protocol adapter changes. */
function selectRuntime(runtime: CatalogRuntime): CatalogRuntime {
  if (catalogMode() === 'catalog') return runtime;
  const legacyService = runtime.catalog.services.find((service) => service.service_mode === 'GEOSERVER_WMS_LEGACY') ?? {
    service_key: 'geoserver_wms_legacy', service_mode: 'GEOSERVER_WMS_LEGACY' as const,
    endpoint: '/geoserver/dayu/wms', healthy: true,
  };
  return {
    ...runtime,
    layers: runtime.layers.map((layer) => layer.renderMode === 'RASTER_WMS' ? {
      ...layer, serviceMode: 'GEOSERVER_WMS_LEGACY' as const, service: legacyService,
      descriptor: { ...layer.descriptor, service_mode: 'GEOSERVER_WMS_LEGACY' as const, service_key: legacyService.service_key },
    } : layer),
  };
}

/** Catalog-driven Cesium shell; adapters own protocol resources and business rendering. */
export function CesiumMap({
  variant = 'dashboard', datasetVersionId: suppliedVersionId, interactionFrame,
  dynamicLoading = false, selectedAsset, analysisFeatures = [], comparisonFrame,
  dgisVectorTileSource = null, dgisRasterTileUrl = null, dgisThreeDTilesets = [],
  onViewportChange, onCesiumStatusChange,
}: CesiumMapProps) {
  const { datasetVersionId: contextVersionId } = useDatasetVersion();
  const datasetVersionId = suppliedVersionId ?? contextVersionId;
  const navigate = useNavigate();
  const containerRef = useRef<HTMLDivElement>(null);
  const viewerRef = useRef<Viewer | null>(null);
  const runtimeRef = useRef<GisAdapterRuntime | null>(null);
  const annotationLayerRef = useRef<AnnotationLayer | null>(null);
  const resultRendererRef = useRef<ResultRenderer | null>(null);
  const searchPointsRef = useRef<PointPrimitiveCollection | null>(null);
  const basemapLayerRef = useRef<ImageryLayer | null>(null);
  const requestGeneration = useRef(0);
  const runtimeLayersRef = useRef<LayerRuntime[]>([]);

  const [catalog, setCatalog] = useState<GISCatalogResponse | null>(null);
  const [catalogError, setCatalogError] = useState('');
  const [settings, setSettings] = useState<Record<string, LayerSetting>>({});
  const [layerOrder, setLayerOrder] = useState<string[]>([]);
  const [loadState, setLoadState] = useState<LoadState>('loading');
  const [loadMessage, setLoadMessage] = useState('正在读取统一 GIS Catalog');
  const [basemapState, setBasemapState] = useState<BasemapState>('loading');
  const [basemapMessage, setBasemapMessage] = useState('正在读取受控底图');
  const [basemapVisible, setBasemapVisible] = useState(true);
  const [reloadToken, setReloadToken] = useState(0);
  const [selected, setSelected] = useState<SelectedGISFeature | null>(null);
  const [located, setLocated] = useState<LocationSearchItem | null>(null);
  const [annotationCount, setAnnotationCount] = useState(0);

  const normalized = useMemo(() => catalog ? selectRuntime(normalizeCatalog(catalog)) : null, [catalog]);
  const runtimeLayers = useMemo(
    () => normalized?.layers.map((layer) => ({ ...layer, ...(settings[layer.key] ?? {}) })) ?? [],
    [normalized, settings],
  );
  runtimeLayersRef.current = runtimeLayers;

  useEffect(() => {
    if (!datasetVersionId) return;
    const generation = ++requestGeneration.current;
    setLoadState('loading'); setCatalogError(''); setSelected(null);
    void getGISCatalog(datasetVersionId).then(async (value) => {
      if (generation !== requestGeneration.current) return;
      const runtime = normalizeCatalog(value);
      if (catalogMode() === 'shadow') {
        const legacy = await getGISLayerCatalog().catch(() => []);
        if (generation !== requestGeneration.current) return;
        const differences = shadowDifferences(runtime, legacy.map((item) => item.key));
        if (differences.length) console.info('GIS catalog shadow differences', differences);
      }
      setCatalog(value);
      setSettings(Object.fromEntries(runtime.layers.map((layer) => [layer.key, { visible: layer.visible, opacity: layer.opacity }])));
      setLayerOrder(runtime.layers.map((layer) => layer.key));
      setLoadState('ready');
      setLoadMessage(`${catalogMode().toUpperCase()} · ${runtime.layers.length} 个 Catalog 图层 · ${runtime.revision.slice(0, 18)}…`);
    }).catch((error: unknown) => {
      if (generation !== requestGeneration.current) return;
      const message = error instanceof Error ? error.message : 'CATALOG_CUTOVER_FAILED';
      setCatalog(null); setCatalogError(message); setLoadState('error');
      setLoadMessage(`CATALOG_CUTOVER_FAILED · ${message}`);
    });
  }, [datasetVersionId, reloadToken]);

  useEffect(() => {
    if (!containerRef.current || !datasetVersionId || !normalized) return undefined;
    const viewer = new Viewer(containerRef.current, {
      animation: false, baseLayer: false, baseLayerPicker: false, fullscreenButton: false,
      geocoder: false, homeButton: false, infoBox: false, navigationHelpButton: false,
      sceneModePicker: false, selectionIndicator: false, timeline: false, requestRenderMode: true,
    });
    viewerRef.current = viewer; onCesiumStatusChange?.(true);
    viewer.scene.globe.baseColor = Color.fromCssColorString('#071725');
    viewer.scene.backgroundColor = Color.fromCssColorString('#06101c');
    viewer.scene.globe.enableLighting = false;
    viewer.camera.setView({
      destination: Cartesian3.fromDegrees(120.27, 30.27, variant === 'workspace' ? 92_000 : 108_000),
      orientation: { heading: 0, pitch: CesiumMath.toRadians(-90), roll: 0 },
    });
    annotationLayerRef.current = new AnnotationLayer(viewer.scene);
    resultRendererRef.current = new ResultRenderer(viewer.scene);
    searchPointsRef.current = viewer.scene.primitives.add(new PointPrimitiveCollection());
    runtimeRef.current = new GisAdapterRuntime(viewer);

    const basemap = normalized.catalog.basemaps.find((item) => item.visible) ?? normalized.catalog.basemaps[0];
    if (basemap) {
      try {
        const provider = new UrlTemplateImageryProvider({ url: basemap.endpoint, maximumLevel: 22, credit: basemap.credit });
        const layer = viewer.imageryLayers.addImageryProvider(provider);
        layer.alpha = basemap.opacity; layer.show = basemapVisible;
        basemapLayerRef.current = layer; setBasemapState('imagery'); setBasemapMessage(basemap.title);
        provider.errorEvent.addEventListener((error) => { if (error.timesRetried < 2) error.retry = true; });
      } catch {
        const layer = viewer.imageryLayers.addImageryProvider(new GridImageryProvider({ color: Color.fromCssColorString('#286875'), glowColor: Color.fromCssColorString('#2fe6d6'), backgroundColor: Color.fromCssColorString('#071923'), cells: 4, glowWidth: 1 }));
        basemapLayerRef.current = layer; setBasemapState('fallback'); setBasemapMessage('受控底图不可用，已切换经纬网');
      }
    } else {
      const layer = viewer.imageryLayers.addImageryProvider(new GridImageryProvider({ color: Color.fromCssColorString('#286875'), backgroundColor: Color.fromCssColorString('#071923') }));
      basemapLayerRef.current = layer; setBasemapState('fallback'); setBasemapMessage('Catalog 未登记底图，使用经纬网');
    }

    const moveCleanup = viewer.camera.moveEnd.addEventListener(() => {
      const rectangle = viewer.camera.computeViewRectangle();
      if (rectangle) onViewportChange?.([
        CesiumMath.toDegrees(rectangle.west), CesiumMath.toDegrees(rectangle.south),
        CesiumMath.toDegrees(rectangle.east), CesiumMath.toDegrees(rectangle.north),
      ]);
    });
    viewer.screenSpaceEventHandler.setInputAction((event: { position: Cartesian2 }) => {
      const picked = viewer.scene.pick(event.position) as { id?: CatalogPick | LocationPick } | undefined;
      if (picked?.id?.kind === 'location') {
        const item = picked.id.item;
        setSelected({ id: `${item.result_type}:${item.object_id ?? 'coordinate'}`, properties: { feature_type: item.result_type, name: item.name, address: item.address, longitude: item.longitude, latitude: item.latitude, source: item.source } });
      } else if (picked?.id?.kind === 'catalog-feature') {
        const value = picked.id;
        void readFeatureDetail(value.identity, value.detailRouteKey)
          .then((properties) => setSelected({ id: String(value.identity.featureId), properties: { ...value.properties, ...properties, layer_key: value.identity.layerKey } }))
          .catch(() => setSelected({ id: String(value.identity.featureId), properties: value.properties }));
      } else {
        const rectangle = viewer.camera.computeViewRectangle();
        const canvas = viewer.scene.canvas;
        const layer = [...runtimeLayersRef.current].reverse().find((item) => (
          item.visible
          && item.serviceMode === 'QGIS_WMS'
          && item.renderMode === 'RASTER_WMS'
          && item.descriptor.identify_enabled
        ));
        if (!rectangle || !layer || canvas.clientWidth < 1 || canvas.clientHeight < 1) return;
        void identifyQgisLayer(layer, {
          bbox: [
            CesiumMath.toDegrees(rectangle.west), CesiumMath.toDegrees(rectangle.south),
            CesiumMath.toDegrees(rectangle.east), CesiumMath.toDegrees(rectangle.north),
          ],
          width: Math.round(canvas.clientWidth), height: Math.round(canvas.clientHeight),
          i: Math.max(0, Math.min(Math.round(event.position.x), Math.round(canvas.clientWidth) - 1)),
          j: Math.max(0, Math.min(Math.round(event.position.y), Math.round(canvas.clientHeight) - 1)),
        }).then((value) => {
          if (!value || value.identity.datasetVersionId !== datasetVersionId) return;
          void readFeatureDetail(value.identity, value.detailRouteKey)
            .then((properties) => setSelected({ id: String(value.identity.featureId), properties: { ...value.properties, ...properties } }))
            .catch(() => setSelected({ id: String(value.identity.featureId), properties: value.properties }));
        }).catch(() => undefined);
      }
    }, ScreenSpaceEventType.LEFT_CLICK);

    return () => {
      moveCleanup(); runtimeRef.current?.destroy(interactionFrame ?? null); runtimeRef.current = null;
      annotationLayerRef.current = null; resultRendererRef.current = null; searchPointsRef.current = null;
      basemapLayerRef.current = null; viewerRef.current = null; onCesiumStatusChange?.(false);
      if (!viewer.isDestroyed()) viewer.destroy();
    };
  }, [datasetVersionId, normalized?.revision, onCesiumStatusChange, onViewportChange, variant]);

  useEffect(() => {
    if (runtimeRef.current) void runtimeRef.current.sync(runtimeLayers, interactionFrame ?? null);
  }, [runtimeLayers, interactionFrame]);

  useEffect(() => {
    if (!selectedAsset || !datasetVersionId || !normalized) return;
    const identity = parseFeatureIdentity(selectedAsset, datasetVersionId);
    const layer = identity ? normalized.layers.find((item) => item.key === identity.layerKey) : undefined;
    if (!identity || !layer) return;
    void readFeatureDetail(identity, layer.descriptor.identify.detail_route_key as string | null)
      .then((properties) => setSelected({ id: String(identity.featureId), properties }))
      .catch(() => undefined);
  }, [datasetVersionId, normalized, selectedAsset]);

  useEffect(() => {
    const viewer = viewerRef.current; const layer = annotationLayerRef.current;
    if (!viewer || !layer || !datasetVersionId) return;
    const rectangle = viewer.camera.computeViewRectangle();
    const bbox = rectangle ? [CesiumMath.toDegrees(rectangle.west), CesiumMath.toDegrees(rectangle.south), CesiumMath.toDegrees(rectangle.east), CesiumMath.toDegrees(rectangle.north)].join(',') : undefined;
    const scale = Math.max(500, viewer.camera.positionCartographic.height * 5);
    void getGISAnnotations({ dataset_version_id: datasetVersionId, scale_denominator: scale, bbox, limit: 2000, time_seconds: interactionFrame?.selected_time_seconds ?? 0, task_id: interactionFrame?.task_id ?? undefined, dispatch_run_id: interactionFrame?.dispatch_run_id ?? undefined })
      .then((result) => { if (annotationLayerRef.current !== layer) return; layer.sync(result.items, scale); setAnnotationCount(layer.count); viewer.scene.requestRender(); })
      .catch(() => setAnnotationCount(0));
  }, [datasetVersionId, interactionFrame, reloadToken, normalized?.revision]);

  useEffect(() => {
    const renderer = resultRendererRef.current; const viewer = viewerRef.current;
    if (!renderer || !viewer) return;
    if (comparisonFrame) renderer.renderComparison(comparisonFrame); else renderer.renderSpatial(analysisFeatures);
    viewer.scene.requestRender();
  }, [analysisFeatures, comparisonFrame]);

  useEffect(() => {
    const viewer = viewerRef.current; const points = searchPointsRef.current;
    if (!viewer || !points || !located) return;
    points.removeAll();
    points.add({ position: Cartesian3.fromDegrees(located.longitude, located.latitude, 160), pixelSize: 16, color: Color.fromCssColorString('#ffce6a'), outlineColor: Color.WHITE, outlineWidth: 2, id: { kind: 'location', item: located } satisfies LocationPick });
    viewer.camera.flyTo({ destination: Cartesian3.fromDegrees(located.longitude, located.latitude, 18_000), orientation: { heading: 0, pitch: CesiumMath.toRadians(-90), roll: 0 }, duration: 1.2 });
    viewer.scene.requestRender();
  }, [located]);

  useEffect(() => {
    const viewer = viewerRef.current; if (!viewer || !dgisRasterTileUrl) return undefined;
    const layer = viewer.imageryLayers.addImageryProvider(new UrlTemplateImageryProvider({ url: dgisRasterTileUrl, maximumLevel: 18, credit: 'TiTiler COG' }));
    layer.alpha = 0.72;
    return () => { if (!viewer.isDestroyed()) viewer.imageryLayers.remove(layer, true); };
  }, [dgisRasterTileUrl, normalized?.revision]);

  useEffect(() => {
    const viewer = viewerRef.current; if (!viewer || !dgisVectorTileSource || !datasetVersionId) return undefined;
    let disposed = false; let provider: MVTDataProvider | null = null;
    void MVTDataProvider.fromUrl(`/vector/${encodeURIComponent(dgisVectorTileSource)}/{z}/{x}/{y}?dataset_version_id=${datasetVersionId}`, { minZoom: 0, maxZoom: 18, featureIdProperty: 'id' })
      .then((created) => { if (disposed || viewer.isDestroyed()) return; provider = created; viewer.scene.primitives.add(created); });
    return () => { disposed = true; if (provider && !viewer.isDestroyed()) viewer.scene.primitives.remove(provider); };
  }, [datasetVersionId, dgisVectorTileSource, normalized?.revision]);

  useEffect(() => {
    const viewer = viewerRef.current; if (!viewer) return undefined;
    for (const tileset of dgisThreeDTilesets) if (!viewer.scene.primitives.contains(tileset)) viewer.scene.primitives.add(tileset);
    return () => { if (!viewer.isDestroyed()) for (const tileset of dgisThreeDTilesets) if (viewer.scene.primitives.contains(tileset)) viewer.scene.primitives.remove(tileset); };
  }, [dgisThreeDTilesets, normalized?.revision]);

  const updateLayer = useCallback((key: string, update: Partial<LayerSetting>) => {
    setSettings((current) => ({ ...current, [key]: { ...current[key], ...update } }));
    runtimeRef.current?.setState(key, update);
  }, []);

  function moveLayer(key: string, direction: 'up' | 'down') {
    if (!normalized) return;
    setLayerOrder((current) => {
      const group = normalized.layers.find((item) => item.key === key)?.groupKey;
      const groupItems = current.filter((item) => normalized.layers.find((layer) => layer.key === item)?.groupKey === group);
      const index = groupItems.indexOf(key); const neighbor = groupItems[index + (direction === 'up' ? -1 : 1)];
      if (!neighbor) return current;
      const next = [...current]; const left = next.indexOf(key); const right = next.indexOf(neighbor);
      [next[left], next[right]] = [next[right], next[left]]; runtimeRef.current?.raiseInOrder(next); return next;
    });
  }

  function toggleBasemap(visible: boolean) {
    setBasemapVisible(visible); if (basemapLayerRef.current) basemapLayerRef.current.show = visible;
    viewerRef.current?.scene.requestRender();
  }

  if (!datasetVersionId) return <section className={`map-card map-card--${variant} panel-surface map-card--waiting`}>正在读取数据版本…</section>;
  const groupOrder = new Map(normalized?.groups.map((group) => [group.group_key, group.order]) ?? []);
  const layerByKey = new Map(runtimeLayers.map((layer) => [layer.key, layer]));
  return (
    <section className={`map-card map-card--${variant} panel-surface`} aria-label="GIS 河网空间一张图">
      <div className="panel-heading map-card__heading">
        <div><span className="panel-kicker">POSTGIS · QGIS SERVER · CATALOG · CESIUMJS</span><h2>水利空间分析</h2></div>
        <div className="map-toolbar">
          <Tag className="outline-tag" icon={<EnvironmentOutlined />}>CGCS2000 · EPSG:4490</Tag>
          <Tag className="outline-tag">版本 #{datasetVersionId}</Tag><Tag className="outline-tag">{catalogMode().toUpperCase()}</Tag>
          <Tooltip title="重新读取 Catalog"><Button type="text" icon={<ReloadOutlined />} onClick={() => setReloadToken((value) => value + 1)} /></Tooltip>
          {variant === 'dashboard' && <Tooltip title="打开 GIS 工作台"><Button type="text" icon={<ExpandOutlined />} onClick={() => navigate('/gis')} /></Tooltip>}
        </div>
      </div>
      <div className="map-stage">
        <div ref={containerRef} className="cesium-container" />
        {variant === 'workspace' && <SearchBox datasetVersionId={datasetVersionId} onLocate={setLocated} />}
        <div className={`map-load-state map-load-state--${loadState}`} role="status"><i />{loadMessage}</div>
        <div className={`basemap-status basemap-status--${basemapState}`}><i />{basemapMessage}</div>
        {catalogError && <div className="dynamic-frame-loading">{catalogError}</div>}
        {variant === 'workspace' && normalized && <LayerManager
          basemapLabel={basemapMessage} basemapVisible={basemapVisible}
          items={layerOrder.map((key) => layerByKey.get(key)).filter((layer): layer is LayerRuntime => Boolean(layer)).map((layer) => ({ key: layer.key, label: layer.title, visible: layer.visible, opacity: layer.opacity, group: layer.groupKey, groupTitle: layer.groupTitle, groupOrder: groupOrder.get(layer.groupKey) ?? layer.order, dynamic: layer.renderMode === 'DYNAMIC_PRIMITIVE' }))}
          onBasemapChange={toggleBasemap} onLayerChange={updateLayer} onMove={moveLayer}
        />}
        {variant === 'workspace' && <div className="gis-performance" aria-label="GIS Catalog 状态"><div><strong>Catalog Runtime</strong><span>{normalized?.revision.slice(0, 20) ?? 'loading'}</span></div><p><b>图层 / 标注</b><span>{runtimeLayers.length} 层</span><em>{annotationCount} 条</em></p></div>}
        {dynamicLoading && <div className="dynamic-frame-loading">水动力 / 调度状态同步中</div>}
        {selected && <FeatureInspector feature={selected} onClose={() => setSelected(null)} onOpenHydraulicResult={(sectionId) => navigate(`/hydraulic/results?sectionId=${encodeURIComponent(sectionId)}${interactionFrame?.task_id ? `&taskId=${interactionFrame.task_id}` : ''}`)} />}
        <div className="map-coordinate">{located ? `${located.longitude.toFixed(6)}°E / ${located.latitude.toFixed(6)}°N · ${located.name}` : '120.27°E / 30.27°N'} · CGCS2000 · DATASET #{datasetVersionId}</div>
      </div>
    </section>
  );
}
