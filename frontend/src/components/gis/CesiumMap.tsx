import { EnvironmentOutlined, ExpandOutlined, ReloadOutlined } from '@ant-design/icons';
import { Button, Tag, Tooltip } from 'antd';
import {
  ArcGisMapServerImageryProvider,
  Cartesian2,
  Cartesian3,
  Color,
  GridImageryProvider,
  Material,
  Math as CesiumMath,
  PointPrimitiveCollection,
  PolylineCollection,
  ScreenSpaceEventType,
  Viewer,
  WebMapServiceImageryProvider,
  WebMapTileServiceImageryProvider,
  type ImageryLayer,
  type ImageryLayerFeatureInfo,
} from 'cesium';
import 'cesium/Build/Cesium/Widgets/widgets.css';
import { useCallback, useEffect, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  getCrossSection,
  getGate,
  getGeoServerConfig,
  getGISAnnotations,
  getPump,
  getRiver,
  type GISComparisonFrame,
  type GISInteractionFrame,
  type GISStructureSample,
  type GISWaterSample,
  type GeoJSONFeature,
  type SpatialFeature,
} from '../../api/generated/client';
import { useDatasetVersion } from '../../context/DatasetVersionContext';
import { AnnotationLayer } from './AnnotationLayer';
import { FeatureInspector, type SelectedGISFeature } from './FeatureInspector';
import { LayerManager } from './LayerManager';
import { formatBytes, runPerformanceProbes, type GISPerformanceMetric } from './performance';
import { ResultRenderer } from './ResultRenderer';

type StaticLayerKey = 'river' | 'river_segment' | 'river_node' | 'cross_section' | 'gate' | 'pump';
type DynamicLayerKey = 'water_result' | 'velocity_result' | 'dispatch_status';
type LayerKey = StaticLayerKey | DynamicLayerKey;
type LoadState = 'loading' | 'ready' | 'error';
type BasemapState = 'loading' | 'imagery' | 'fallback';
type ScaleMode = 'wmts' | 'wms';

interface CesiumMapProps {
  variant?: 'dashboard' | 'workspace';
  datasetVersionId?: number;
  interactionFrame?: GISInteractionFrame | null;
  dynamicLoading?: boolean;
  selectedAsset?: string;
  analysisFeatures?: SpatialFeature[];
  comparisonFrame?: GISComparisonFrame | null;
  onViewportChange?: (bbox: [number, number, number, number]) => void;
  onCesiumStatusChange?: (online: boolean) => void;
}

interface ThematicLayers {
  wms: ImageryLayer;
  wmts?: ImageryLayer;
}

interface LayerSetting {
  visible: boolean;
  opacity: number;
}

interface DynamicPick {
  kind: 'dynamic';
  layer: DynamicLayerKey;
  sample: GISWaterSample | GISStructureSample;
}

const WORLD_IMAGERY_URL = 'https://services.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer';
const MEDIUM_SCALE_HEIGHT_METRES = 72_000;
const CACHED_LAYERS = new Set<StaticLayerKey>(['river', 'river_segment', 'gate', 'pump']);
const TILE_MATRIX_LABELS = Array.from({ length: 23 }, (_, level) => `EPSG:900913:${level}`);
const staticLayerKeys: StaticLayerKey[] = ['river', 'river_segment', 'river_node', 'cross_section', 'gate', 'pump'];
const dynamicLayerKeys: DynamicLayerKey[] = ['water_result', 'velocity_result', 'dispatch_status'];
const layerLabels: Record<LayerKey, string> = {
  river: '河道', river_segment: '河段', river_node: '河网节点', cross_section: '横断面',
  gate: '闸门', pump: '泵站', water_result: '水位结果', velocity_result: '流速结果',
  dispatch_status: '调度状态',
};

const initialLayerSettings = Object.fromEntries(
  [...staticLayerKeys, ...dynamicLayerKeys].map((key) => [key, { visible: true, opacity: 0.88 }]),
) as Record<LayerKey, LayerSetting>;

/** Parse stable GeoServer feature identifiers without using display names as identity. */
function parseAssetKey(raw: string | undefined): { type: StaticLayerKey; id: number } | null {
  if (!raw) return null;
  const match = raw.match(/(river_segment|river_node|cross_section|river|gate|pump)[.:](\d+)$/);
  if (!match) return null;
  return { type: match[1] as StaticLayerKey, id: Number(match[2]) };
}

/** Extract the business key from a WMS GetFeatureInfo result. */
function parsePickedFeature(feature: ImageryLayerFeatureInfo): { type: StaticLayerKey; id: number; properties: Record<string, unknown> } | null {
  const data = feature.data as { id?: string; properties?: Record<string, unknown> } | undefined;
  const properties = data?.properties ?? {};
  const parsed = parseAssetKey(data?.id ?? feature.name);
  const id = Number(properties.id ?? parsed?.id);
  if (!parsed || !Number.isFinite(id)) return null;
  return { type: parsed.type, id, properties: { ...properties, feature_type: parsed.type } };
}

/** Read authoritative business attributes through the generated FastAPI client. */
async function readBusinessFeature(type: StaticLayerKey, id: number, datasetVersionId: number): Promise<SelectedGISFeature> {
  let feature: GeoJSONFeature | null = null;
  if (type === 'river') feature = await getRiver(id, datasetVersionId);
  if (type === 'gate') feature = await getGate(id, datasetVersionId);
  if (type === 'pump') feature = await getPump(id, datasetVersionId);
  if (type === 'cross_section') feature = await getCrossSection(id, datasetVersionId);
  if (feature) return { id: String(feature.id), properties: feature.properties };
  return { id: String(id), properties: { id, feature_type: type, dataset_version_id: datasetVersionId, source: 'GeoServer WMS GetFeatureInfo' } };
}

/** Build one version filter shared by WMS, WMTS and browser performance probes. */
function versionFilter(datasetVersionId: number): string {
  return `dataset_version_id=${datasetVersionId}`;
}

/** Convert simulated risk levels into one stable engineering legend. */
function riskColor(level: GISWaterSample['risk_level'], opacity: number): Color {
  if (level === 'danger') return Color.fromCssColorString('#ff5b62').withAlpha(opacity);
  if (level === 'warning') return Color.fromCssColorString('#ffc85c').withAlpha(opacity);
  return Color.fromCssColorString('#2fe6d6').withAlpha(opacity);
}

/** Convert velocity classes into map colors independent from water-level risk. */
function velocityColor(level: GISWaterSample['velocity_level'], opacity: number): Color {
  if (level === 'high') return Color.fromCssColorString('#a972ff').withAlpha(opacity);
  if (level === 'medium') return Color.fromCssColorString('#3b8fff').withAlpha(opacity);
  return Color.fromCssColorString('#77d9ff').withAlpha(opacity);
}

/** Calculate a short map-space arrow endpoint from a PostGIS-derived bearing. */
function arrowEnd(sample: GISWaterSample): Cartesian3 {
  const bearing = CesiumMath.toRadians(sample.flow_bearing_degrees);
  const distanceMetres = 900;
  const latitudeDelta = Math.cos(bearing) * distanceMetres / 110_540;
  const longitudeDelta = Math.sin(bearing) * distanceMetres / (111_320 * Math.max(0.2, Math.cos(CesiumMath.toRadians(sample.latitude))));
  return Cartesian3.fromDegrees(sample.longitude + longitudeDelta, sample.latitude + latitudeDelta, 45);
}

/** Render the version-safe Phase 1C spatial workspace while keeping one Viewer per mount. */
export function CesiumMap({
  variant = 'dashboard', datasetVersionId: suppliedVersionId, interactionFrame,
  dynamicLoading = false, selectedAsset, analysisFeatures = [], comparisonFrame,
  onViewportChange, onCesiumStatusChange,
}: CesiumMapProps) {
  const { datasetVersionId: contextVersionId } = useDatasetVersion();
  const datasetVersionId = suppliedVersionId ?? contextVersionId;
  const containerRef = useRef<HTMLDivElement>(null);
  const viewerRef = useRef<Viewer | null>(null);
  const basemapLayerRef = useRef<ImageryLayer | null>(null);
  const thematicLayersRef = useRef(new Map<StaticLayerKey, ThematicLayers>());
  const waterPointsRef = useRef<PointPrimitiveCollection | null>(null);
  const velocityPointsRef = useRef<PointPrimitiveCollection | null>(null);
  const velocityLinesRef = useRef<PolylineCollection | null>(null);
  const structurePointsRef = useRef<PointPrimitiveCollection | null>(null);
  const annotationLayerRef = useRef<AnnotationLayer | null>(null);
  const resultRendererRef = useRef<ResultRenderer | null>(null);
  const settingsRef = useRef(initialLayerSettings);
  const interactionFrameRef = useRef(interactionFrame);
  const scaleModeRef = useRef<ScaleMode>('wmts');
  const navigate = useNavigate();
  const [loadState, setLoadState] = useState<LoadState>('loading');
  const [loadMessage, setLoadMessage] = useState('正在连接 GeoServer 空间服务');
  const [basemapState, setBasemapState] = useState<BasemapState>('loading');
  const [basemapMessage, setBasemapMessage] = useState('正在连接卫星影像');
  const [basemapVisible, setBasemapVisible] = useState(true);
  const [reloadToken, setReloadToken] = useState(0);
  const [selected, setSelected] = useState<SelectedGISFeature | null>(null);
  const [scaleMode, setScaleMode] = useState<ScaleMode>('wmts');
  const [settings, setSettings] = useState(initialLayerSettings);
  const [performanceMetrics, setPerformanceMetrics] = useState<GISPerformanceMetric[]>([]);
  const [jsHeapMb, setJsHeapMb] = useState<number | null>(null);
  const [annotationCount, setAnnotationCount] = useState(0);
  const [framesPerSecond, setFramesPerSecond] = useState(0);
  interactionFrameRef.current = interactionFrame;

  useEffect(() => {
    setSelected(null);
  }, [datasetVersionId]);

  useEffect(() => {
    const asset = parseAssetKey(selectedAsset);
    if (!asset || !datasetVersionId) return;
    void readBusinessFeature(asset.type, asset.id, datasetVersionId).then(setSelected).catch(() => undefined);
  }, [datasetVersionId, selectedAsset]);

  useEffect(() => {
    const memory = (performance as Performance & { memory?: { usedJSHeapSize: number } }).memory;
    setJsHeapMb(memory ? memory.usedJSHeapSize / 1024 / 1024 : null);
  }, [interactionFrame, reloadToken]);

  useEffect(() => {
    if (!containerRef.current || !datasetVersionId) return undefined;
    const activeDatasetVersionId = datasetVersionId;
    let cancelled = false;
    const cleanups: Array<() => void> = [];
    const viewer = new Viewer(containerRef.current, {
      animation: false, baseLayer: false, baseLayerPicker: false, fullscreenButton: false,
      geocoder: false, homeButton: false, infoBox: false, navigationHelpButton: false,
      sceneModePicker: false, selectionIndicator: false, timeline: false, requestRenderMode: true,
    });
    viewerRef.current = viewer;
    thematicLayersRef.current.clear();
    onCesiumStatusChange?.(true);
    viewer.scene.globe.baseColor = Color.fromCssColorString('#071725');
    viewer.scene.backgroundColor = Color.fromCssColorString('#06101c');
    viewer.scene.globe.enableLighting = false;
    viewer.camera.setView({
      destination: Cartesian3.fromDegrees(120.27, 30.27, variant === 'workspace' ? 92_000 : 108_000),
      orientation: { heading: 0, pitch: CesiumMath.toRadians(-90), roll: 0 },
    });

    waterPointsRef.current = viewer.scene.primitives.add(new PointPrimitiveCollection());
    velocityPointsRef.current = viewer.scene.primitives.add(new PointPrimitiveCollection());
    velocityLinesRef.current = viewer.scene.primitives.add(new PolylineCollection());
    structurePointsRef.current = viewer.scene.primitives.add(new PointPrimitiveCollection());
    annotationLayerRef.current = new AnnotationLayer(viewer.scene);
    resultRendererRef.current = new ResultRenderer(viewer.scene);

    let renderedFrames = 0;
    let frameWindowStarted = performance.now();
    cleanups.push(viewer.scene.postRender.addEventListener(() => {
      renderedFrames += 1;
      const now = performance.now();
      if (now - frameWindowStarted >= 1000) {
        setFramesPerSecond(Math.round(renderedFrames * 1000 / (now - frameWindowStarted)));
        renderedFrames = 0;
        frameWindowStarted = now;
      }
    }));

    async function syncAnnotations() {
      const layer = annotationLayerRef.current;
      if (!layer) return;
      const rectangle = viewer.camera.computeViewRectangle();
      const bbox = rectangle ? [
        CesiumMath.toDegrees(rectangle.west), CesiumMath.toDegrees(rectangle.south),
        CesiumMath.toDegrees(rectangle.east), CesiumMath.toDegrees(rectangle.north),
      ].join(',') : undefined;
      const frame = interactionFrameRef.current;
      const scaleDenominator = Math.max(500, viewer.camera.positionCartographic.height * 5);
      try {
        const result = await getGISAnnotations({
          dataset_version_id: activeDatasetVersionId, scale_denominator: scaleDenominator,
          bbox, limit: 2000, time_seconds: frame?.selected_time_seconds ?? 0,
          task_id: frame?.task_id ?? undefined, dispatch_run_id: frame?.dispatch_run_id ?? undefined,
        });
        if (cancelled) return;
        layer.sync(result.items, scaleDenominator);
        setAnnotationCount(layer.count);
        viewer.scene.requestRender();
      } catch {
        if (!cancelled) setAnnotationCount(0);
      }
    }

    function syncThematicLayers(mode: ScaleMode) {
      for (const [key, layers] of thematicLayersRef.current) {
        const setting = settingsRef.current[key];
        layers.wms.show = setting.visible && mode === 'wms';
        layers.wms.alpha = setting.opacity;
        if (layers.wmts) {
          layers.wmts.show = setting.visible && mode === 'wmts';
          layers.wmts.alpha = setting.opacity;
        }
      }
      viewer.scene.requestRender();
    }

    function updateScaleMode() {
      const mode: ScaleMode = viewer.camera.positionCartographic.height <= MEDIUM_SCALE_HEIGHT_METRES ? 'wms' : 'wmts';
      scaleModeRef.current = mode;
      setScaleMode(mode);
      syncThematicLayers(mode);
      const rectangle = viewer.camera.computeViewRectangle();
      if (rectangle) onViewportChange?.([
        CesiumMath.toDegrees(rectangle.west), CesiumMath.toDegrees(rectangle.south),
        CesiumMath.toDegrees(rectangle.east), CesiumMath.toDegrees(rectangle.north),
      ]);
      void syncAnnotations();
    }

    cleanups.push(viewer.camera.moveEnd.addEventListener(updateScaleMode));
    viewer.screenSpaceEventHandler.setInputAction((event: { position: Cartesian2 }) => {
      const scenePick = viewer.scene.pick(event.position) as { id?: unknown } | undefined;
      const dynamicPick = scenePick?.id as DynamicPick | undefined;
      if (dynamicPick?.kind === 'dynamic') {
        if ('section_id' in dynamicPick.sample) {
          const waterSample = dynamicPick.sample;
          void getCrossSection(waterSample.section_id, activeDatasetVersionId)
            .then((feature) => setSelected({
              id: String(waterSample.section_id),
              properties: {
                ...feature.properties,
                ...waterSample,
                feature_type: dynamicPick.layer,
                time_seconds: interactionFrameRef.current?.selected_time_seconds,
              },
            }));
        } else {
          setSelected({
            id: String(dynamicPick.sample.structure_id),
            properties: { ...dynamicPick.sample, feature_type: 'dispatch_status', time_seconds: interactionFrameRef.current?.selected_time_seconds },
          });
        }
        return;
      }
      const ray = viewer.camera.getPickRay(event.position);
      if (!ray) return;
      const picked = viewer.imageryLayers.pickImageryLayerFeatures(ray, viewer.scene);
      if (!picked) return;
      void picked.then(async (features) => {
        if (cancelled) return;
        const parsed = features.map(parsePickedFeature).find(Boolean);
        if (!parsed) return;
        try {
          const detail = await readBusinessFeature(parsed.type, parsed.id, activeDatasetVersionId);
          if (!cancelled) setSelected({ id: detail.id, properties: { ...parsed.properties, ...detail.properties } });
        } catch {
          if (!cancelled) setSelected({ id: String(parsed.id), properties: parsed.properties });
        }
      });
    }, ScreenSpaceEventType.LEFT_CLICK);

    let activeBasemapLayer: ImageryLayer | undefined;
    let fallbackActive = false;
    function activateFallback(reason: string) {
      if (cancelled || fallbackActive) return;
      fallbackActive = true;
      if (activeBasemapLayer) viewer.imageryLayers.remove(activeBasemapLayer, true);
      activeBasemapLayer = viewer.imageryLayers.addImageryProvider(new GridImageryProvider({
        color: Color.fromCssColorString('#286875'), glowColor: Color.fromCssColorString('#2fe6d6'),
        backgroundColor: Color.fromCssColorString('#071923'), cells: 4, glowWidth: 1,
      }));
      activeBasemapLayer.show = basemapVisible;
      basemapLayerRef.current = activeBasemapLayer;
      setBasemapState('fallback');
      setBasemapMessage(reason);
      viewer.scene.requestRender();
    }

    async function loadBasemap() {
      setBasemapState('loading');
      try {
        const provider = await ArcGisMapServerImageryProvider.fromUrl(WORLD_IMAGERY_URL);
        if (cancelled) return;
        cleanups.push(provider.errorEvent.addEventListener((error) => {
          if (error.timesRetried < 2) error.retry = true;
          else activateFallback('卫星影像请求失败，已切换经纬网');
        }));
        activeBasemapLayer = viewer.imageryLayers.addImageryProvider(provider);
        activeBasemapLayer.show = basemapVisible;
        basemapLayerRef.current = activeBasemapLayer;
        setBasemapState('imagery');
        setBasemapMessage('Esri World Imagery 卫星影像');
      } catch {
        activateFallback('卫星影像连接失败，已切换经纬网');
      }
    }

    async function loadGeoServerLayers() {
      setLoadState('loading');
      setLoadMessage(`正在读取版本 #${activeDatasetVersionId} 的 WMS / WMTS`);
      try {
        const config = await getGeoServerConfig();
        if (cancelled) return;
        const cql = versionFilter(activeDatasetVersionId);
        for (const key of staticLayerKeys) {
          const wmsProvider = new WebMapServiceImageryProvider({
            url: config.wms_url, layers: `dayu:${key}`,
            parameters: { transparent: true, format: 'image/png', version: '1.1.1', CQL_FILTER: cql },
            getFeatureInfoParameters: { info_format: 'application/json', feature_count: 5, CQL_FILTER: cql },
            srs: 'EPSG:4490', enablePickFeatures: true, credit: 'GeoServer / PostGIS / CGCS2000',
          });
          const wms = viewer.imageryLayers.addImageryProvider(wmsProvider);
          wms.show = false;
          cleanups.push(wmsProvider.errorEvent.addEventListener((error) => { if (error.timesRetried < 2) error.retry = true; }));
          let wmts: ImageryLayer | undefined;
          if (CACHED_LAYERS.has(key)) {
            const wmtsProvider = new WebMapTileServiceImageryProvider({
              url: config.wmts_url, layer: `dayu:${key}`, style: '', format: 'image/png',
              tileMatrixSetID: config.preferred_wmts_matrix_set ?? 'EPSG:900913',
              tileMatrixLabels: TILE_MATRIX_LABELS, maximumLevel: 22, enablePickFeatures: false,
              dimensions: { CQL_FILTER: cql }, credit: 'GeoWebCache / PostGIS / CGCS2000',
            });
            wmts = viewer.imageryLayers.addImageryProvider(wmtsProvider);
            cleanups.push(wmtsProvider.errorEvent.addEventListener((error) => { if (error.timesRetried < 2) error.retry = true; }));
          }
          thematicLayersRef.current.set(key, { wms, wmts });
        }
        updateScaleMode();
        setLoadState('ready');
        setLoadMessage(`版本 #${activeDatasetVersionId} · CQL 隔离 · 6 个静态图层`);
        if (variant === 'workspace') {
          setPerformanceMetrics([
            { source: 'WMS', durationMs: null, bytes: null, status: 'testing' },
            { source: 'WMTS', durationMs: null, bytes: null, status: 'testing' },
            { source: 'GeoJSON', durationMs: null, bytes: null, status: 'testing' },
          ]);
          void runPerformanceProbes(config, activeDatasetVersionId).then((metrics) => { if (!cancelled) setPerformanceMetrics(metrics); });
        }
      } catch (error) {
        if (cancelled) return;
        setLoadState('error');
        setLoadMessage(error instanceof Error ? error.message : 'GeoServer 图层加载失败');
      }
    }

    void loadBasemap();
    void loadGeoServerLayers();
    void syncAnnotations();
    return () => {
      cancelled = true;
      cleanups.forEach((cleanup) => cleanup());
      thematicLayersRef.current.clear();
      waterPointsRef.current = null;
      velocityPointsRef.current = null;
      velocityLinesRef.current = null;
      structurePointsRef.current = null;
      annotationLayerRef.current = null;
      resultRendererRef.current = null;
      basemapLayerRef.current = null;
      viewerRef.current = null;
      onCesiumStatusChange?.(false);
      if (!viewer.isDestroyed()) viewer.destroy();
    };
  }, [datasetVersionId, onViewportChange, reloadToken, variant]);

  useEffect(() => {
    const viewer = viewerRef.current;
    const layer = annotationLayerRef.current;
    if (!viewer || !layer || !datasetVersionId) return;
    const frame = interactionFrame;
    const scaleDenominator = Math.max(500, viewer.camera.positionCartographic.height * 5);
    const rectangle = viewer.camera.computeViewRectangle();
    const bbox = rectangle ? [
      CesiumMath.toDegrees(rectangle.west), CesiumMath.toDegrees(rectangle.south),
      CesiumMath.toDegrees(rectangle.east), CesiumMath.toDegrees(rectangle.north),
    ].join(',') : undefined;
    void getGISAnnotations({
      dataset_version_id: datasetVersionId, scale_denominator: scaleDenominator, bbox,
      limit: 2000, time_seconds: frame?.selected_time_seconds ?? 0,
      task_id: frame?.task_id ?? undefined, dispatch_run_id: frame?.dispatch_run_id ?? undefined,
    }).then((result) => {
      if (annotationLayerRef.current !== layer) return;
      layer.sync(result.items, scaleDenominator);
      setAnnotationCount(layer.count);
      viewer.scene.requestRender();
    }).catch(() => setAnnotationCount(0));
  }, [datasetVersionId, interactionFrame, reloadToken]);

  useEffect(() => {
    const renderer = resultRendererRef.current;
    const viewer = viewerRef.current;
    if (!renderer || !viewer) return;
    if (comparisonFrame) renderer.renderComparison(comparisonFrame);
    else renderer.renderSpatial(analysisFeatures);
    viewer.scene.requestRender();
  }, [analysisFeatures, comparisonFrame]);

  useEffect(() => {
    const viewer = viewerRef.current;
    const waterPoints = waterPointsRef.current;
    const velocityPoints = velocityPointsRef.current;
    const velocityLines = velocityLinesRef.current;
    const structurePoints = structurePointsRef.current;
    if (!viewer || !waterPoints || !velocityPoints || !velocityLines || !structurePoints) return;
    waterPoints.removeAll();
    velocityPoints.removeAll();
    velocityLines.removeAll();
    structurePoints.removeAll();
    const waterSetting = settings.water_result;
    const velocitySetting = settings.velocity_result;
    const structureSetting = settings.dispatch_status;
    for (const sample of interactionFrame?.water_samples ?? []) {
      if (waterSetting.visible) {
        waterPoints.add({
          position: Cartesian3.fromDegrees(sample.longitude, sample.latitude, 70),
          pixelSize: sample.risk_level === 'danger' ? 14 : 11,
          color: riskColor(sample.risk_level, waterSetting.opacity),
          outlineColor: Color.WHITE.withAlpha(0.82), outlineWidth: 1.5,
          id: { kind: 'dynamic', layer: 'water_result', sample } satisfies DynamicPick,
        });
      }
      if (velocitySetting.visible) {
        const color = velocityColor(sample.velocity_level, velocitySetting.opacity);
        velocityPoints.add({
          position: Cartesian3.fromDegrees(sample.longitude, sample.latitude, 85),
          pixelSize: 6, color, outlineColor: Color.WHITE.withAlpha(0.6), outlineWidth: 1,
          id: { kind: 'dynamic', layer: 'velocity_result', sample } satisfies DynamicPick,
        });
        if (sample.flow_direction !== 'stationary') {
          velocityLines.add({
            positions: [Cartesian3.fromDegrees(sample.longitude, sample.latitude, 75), arrowEnd(sample)],
            width: sample.velocity_level === 'high' ? 5 : 3,
            material: Material.fromType('PolylineArrow', { color }),
            id: { kind: 'dynamic', layer: 'velocity_result', sample } satisfies DynamicPick,
          });
        }
      }
    }
    for (const sample of interactionFrame?.structure_samples ?? []) {
      if (!structureSetting.visible) continue;
      const active = sample.state === 'open' || sample.state === 'running';
      structurePoints.add({
        position: Cartesian3.fromDegrees(sample.longitude, sample.latitude, 100),
        pixelSize: sample.structure_type === 'gate' ? 15 : 17,
        color: (active ? Color.fromCssColorString('#48e58b') : Color.fromCssColorString('#8092a2')).withAlpha(structureSetting.opacity),
        outlineColor: sample.constraint_flags.length > 0 ? Color.fromCssColorString('#ffc85c') : Color.WHITE.withAlpha(0.8),
        outlineWidth: sample.constraint_flags.length > 0 ? 3 : 1.5,
        id: { kind: 'dynamic', layer: 'dispatch_status', sample } satisfies DynamicPick,
      });
    }
    viewer.scene.requestRender();
  }, [interactionFrame, settings]);

  const updateLayer = useCallback((key: LayerKey, patch: Partial<LayerSetting>) => {
    setSettings((current) => {
      const next = { ...current, [key]: { ...current[key], ...patch } };
      settingsRef.current = next;
      const layers = thematicLayersRef.current.get(key as StaticLayerKey);
      if (layers) {
        layers.wms.show = next[key].visible && scaleModeRef.current === 'wms';
        layers.wms.alpha = next[key].opacity;
        if (layers.wmts) {
          layers.wmts.show = next[key].visible && scaleModeRef.current === 'wmts';
          layers.wmts.alpha = next[key].opacity;
        }
        viewerRef.current?.scene.requestRender();
      }
      return next;
    });
  }, []);

  function toggleBasemap(checked: boolean) {
    setBasemapVisible(checked);
    if (basemapLayerRef.current) basemapLayerRef.current.show = checked;
    viewerRef.current?.scene.requestRender();
  }

  if (!datasetVersionId) {
    return <section className={`map-card map-card--${variant} panel-surface map-card--waiting`}>正在读取数据版本…</section>;
  }
  return (
    <section className={`map-card map-card--${variant} panel-surface`} aria-label="GIS 河网空间一张图">
      <div className="panel-heading map-card__heading">
        <div><span className="panel-kicker">POSTGIS · GEOSERVER · CESIUMJS / 1C</span><h2>专业 GIS 与模型融合</h2></div>
        <div className="map-toolbar">
          <Tag className="outline-tag" icon={<EnvironmentOutlined />}>CGCS2000 · EPSG:4490</Tag>
          <Tag className="outline-tag">版本 #{datasetVersionId}</Tag>
          <Tag className="outline-tag">{scaleMode === 'wmts' ? '小比例尺 · WMTS' : '中比例尺 · WMS'}</Tag>
          <Tooltip title="重新读取空间服务"><Button type="text" icon={<ReloadOutlined />} onClick={() => setReloadToken((value) => value + 1)} aria-label="重新加载空间服务" /></Tooltip>
          {variant === 'dashboard' && <Tooltip title="打开 GIS 工作台"><Button type="text" icon={<ExpandOutlined />} onClick={() => navigate('/gis')} aria-label="打开 GIS 工作台" /></Tooltip>}
        </div>
      </div>
      <div className="map-stage">
        <div ref={containerRef} className="cesium-container" />
        <div className={`map-load-state map-load-state--${loadState}`} role="status"><i />{loadMessage}</div>
        <div className={`basemap-status basemap-status--${basemapState}`} data-imagery-source={basemapState === 'imagery' ? 'arcgis-world-imagery' : basemapState}><i />{basemapMessage}</div>
        {variant === 'workspace' && <LayerManager
          basemapLabel={basemapState === 'fallback' ? '经纬网底图' : '卫星影像'}
          basemapVisible={basemapVisible}
          items={[...staticLayerKeys, ...dynamicLayerKeys].map((key) => ({
            key, label: layerLabels[key], visible: settings[key].visible,
            opacity: settings[key].opacity, dynamic: dynamicLayerKeys.includes(key as DynamicLayerKey),
          }))}
          onBasemapChange={toggleBasemap}
          onLayerChange={(key, update) => updateLayer(key as LayerKey, update)}
        />}
        {variant === 'workspace' && performanceMetrics.length > 0 && (
          <div className="gis-performance" aria-label="GIS 性能监控">
            <div><strong>性能监控 · {framesPerSecond} FPS</strong><span>{jsHeapMb === null ? '内存 API 不可用' : `JS 堆 ${jsHeapMb.toFixed(1)} MB`}</span></div>
            <p><b>图层 / 标注</b><span>{thematicLayersRef.current.size + 7} 层</span><em>{annotationCount} 条</em></p>
            {performanceMetrics.map((metric) => (
              <p key={metric.source} className={`gis-performance--${metric.status}`}><b>{metric.source}</b><span>{metric.durationMs === null ? '测试中' : `${metric.durationMs.toFixed(0)} ms`}</span><em>{formatBytes(metric.bytes)}</em></p>
            ))}
          </div>
        )}
        {dynamicLoading && <div className="dynamic-frame-loading">水位 / 流速 / 调度状态同步中</div>}
        {selected && <FeatureInspector feature={selected} onClose={() => setSelected(null)} onOpenHydraulicResult={(sectionId) => navigate(`/hydraulic/results?sectionId=${encodeURIComponent(sectionId)}${interactionFrame?.task_id ? `&taskId=${interactionFrame.task_id}` : ''}`)} />}
        <div className="map-coordinate">120.27°E / 30.27°N · CGCS2000 · DATASET #{datasetVersionId}</div>
      </div>
    </section>
  );
}
