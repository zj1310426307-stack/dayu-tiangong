import { EnvironmentOutlined, ExpandOutlined, ReloadOutlined } from '@ant-design/icons';
import { Button, Checkbox, Tag, Tooltip } from 'antd';
import {
  ArcGisMapServerImageryProvider,
  Cartesian2,
  Cartesian3,
  Color,
  GridImageryProvider,
  type ImageryLayer,
  type ImageryLayerFeatureInfo,
  Math as CesiumMath,
  ScreenSpaceEventType,
  Viewer,
  WebMapServiceImageryProvider,
  WebMapTileServiceImageryProvider,
} from 'cesium';
import 'cesium/Build/Cesium/Widgets/widgets.css';
import { useEffect, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  getCrossSection,
  getGate,
  getGeoServerConfig,
  getPump,
  getRiver,
  type GeoJSONFeature,
} from '../../api/generated/client';

type LayerKey = 'river' | 'river_segment' | 'river_node' | 'cross_section' | 'gate' | 'pump';
type LoadState = 'loading' | 'ready' | 'error';
type BasemapState = 'loading' | 'imagery' | 'fallback';
type ScaleMode = 'wmts' | 'wms';

interface CesiumMapProps {
  variant?: 'dashboard' | 'workspace';
  dispatchRunId?: number;
  timeSeconds?: number;
  selectedAsset?: string;
  onCesiumStatusChange?: (online: boolean) => void;
}

interface SelectedFeature {
  id: string;
  properties: Record<string, unknown>;
}

interface ThematicLayers {
  wms: ImageryLayer;
  wmts?: ImageryLayer;
}

const WORLD_IMAGERY_URL =
  'https://services.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer';
const MEDIUM_SCALE_HEIGHT_METRES = 72_000;
const CACHED_LAYERS = new Set<LayerKey>(['river', 'river_segment', 'gate', 'pump']);
const TILE_MATRIX_LABELS = Array.from({ length: 23 }, (_, level) => `EPSG:900913:${level}`);
const layerLabels: Record<LayerKey, string> = {
  river: '河道',
  river_segment: '河段',
  river_node: '河网节点',
  cross_section: '横断面',
  gate: '闸门',
  pump: '泵站',
};

function displayValue(value: unknown): string {
  if (value === null || value === undefined) return '—';
  if (typeof value === 'object') return JSON.stringify(value);
  return String(value);
}

function parseAssetKey(raw: string | undefined): { type: LayerKey; id: number } | null {
  if (!raw) return null;
  const match = raw.match(/(river_segment|river_node|cross_section|river|gate|pump)[.:](\d+)$/);
  if (!match) return null;
  return { type: match[1] as LayerKey, id: Number(match[2]) };
}

function parsePickedFeature(feature: ImageryLayerFeatureInfo): { type: LayerKey; id: number; properties: Record<string, unknown> } | null {
  const data = feature.data as { id?: string; properties?: Record<string, unknown> } | undefined;
  const properties = data?.properties ?? {};
  const parsed = parseAssetKey(data?.id ?? feature.name);
  const id = Number(properties.id ?? parsed?.id);
  if (!parsed || !Number.isFinite(id)) return null;
  return { type: parsed.type, id, properties: { ...properties, feature_type: parsed.type } };
}

async function readBusinessFeature(type: LayerKey, id: number): Promise<SelectedFeature> {
  let feature: GeoJSONFeature | null = null;
  if (type === 'river') feature = await getRiver(id);
  if (type === 'gate') feature = await getGate(id);
  if (type === 'pump') feature = await getPump(id);
  if (type === 'cross_section') feature = await getCrossSection(id);
  if (feature) return { id: String(feature.id), properties: feature.properties };
  return { id: String(id), properties: { id, feature_type: type, source: 'GeoServer WMS GetFeatureInfo' } };
}

// GeoServer owns static cartography; FastAPI is consulted only after a precise feature pick.
export function CesiumMap({
  variant = 'dashboard',
  dispatchRunId,
  timeSeconds = 0,
  selectedAsset,
  onCesiumStatusChange,
}: CesiumMapProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const viewerRef = useRef<Viewer | null>(null);
  const basemapLayerRef = useRef<ImageryLayer | null>(null);
  const thematicLayersRef = useRef(new Map<LayerKey, ThematicLayers>());
  const visibilityRef = useRef<Record<LayerKey, boolean>>({
    river: true,
    river_segment: true,
    river_node: true,
    cross_section: true,
    gate: true,
    pump: true,
  });
  const scaleModeRef = useRef<ScaleMode>('wmts');
  const navigate = useNavigate();
  const [loadState, setLoadState] = useState<LoadState>('loading');
  const [loadMessage, setLoadMessage] = useState('正在连接 GeoServer 空间服务');
  const [basemapState, setBasemapState] = useState<BasemapState>('loading');
  const [basemapMessage, setBasemapMessage] = useState('正在连接卫星影像');
  const [basemapVisible, setBasemapVisible] = useState(true);
  const [reloadToken, setReloadToken] = useState(0);
  const [selected, setSelected] = useState<SelectedFeature | null>(null);
  const [scaleMode, setScaleMode] = useState<ScaleMode>('wmts');
  const [visibility, setVisibility] = useState(visibilityRef.current);

  useEffect(() => {
    const asset = parseAssetKey(selectedAsset);
    if (!asset) return;
    void readBusinessFeature(asset.type, asset.id).then(setSelected).catch(() => undefined);
  }, [selectedAsset]);

  useEffect(() => {
    if (!containerRef.current) return undefined;
    let cancelled = false;
    const cleanups: Array<() => void> = [];
    const viewer = new Viewer(containerRef.current, {
      animation: false,
      baseLayer: false,
      baseLayerPicker: false,
      fullscreenButton: false,
      geocoder: false,
      homeButton: false,
      infoBox: false,
      navigationHelpButton: false,
      sceneModePicker: false,
      selectionIndicator: false,
      timeline: false,
      requestRenderMode: true,
    });
    viewerRef.current = viewer;
    thematicLayersRef.current.clear();
    onCesiumStatusChange?.(true);
    viewer.scene.globe.baseColor = Color.fromCssColorString('#071725');
    viewer.scene.backgroundColor = Color.fromCssColorString('#06101c');
    viewer.scene.globe.enableLighting = false;
    viewer.camera.setView({
      destination: Cartesian3.fromDegrees(120.27, 30.27, variant === 'workspace' ? 92_000 : 108_000),
      orientation: {
        heading: CesiumMath.toRadians(0),
        pitch: CesiumMath.toRadians(-90),
        roll: 0,
      },
    });

    function syncThematicLayers(mode: ScaleMode) {
      for (const [key, layers] of thematicLayersRef.current) {
        const visible = visibilityRef.current[key];
        layers.wms.show = visible && mode === 'wms';
        if (layers.wmts) layers.wmts.show = visible && mode === 'wmts';
      }
      viewer.scene.requestRender();
    }

    function updateScaleMode() {
      const mode: ScaleMode = viewer.camera.positionCartographic.height <= MEDIUM_SCALE_HEIGHT_METRES ? 'wms' : 'wmts';
      scaleModeRef.current = mode;
      setScaleMode(mode);
      syncThematicLayers(mode);
    }

    const removeMoveEnd = viewer.camera.moveEnd.addEventListener(updateScaleMode);
    cleanups.push(removeMoveEnd);

    viewer.screenSpaceEventHandler.setInputAction((event: { position: Cartesian2 }) => {
      const ray = viewer.camera.getPickRay(event.position);
      if (!ray) return;
      const picked = viewer.imageryLayers.pickImageryLayerFeatures(ray, viewer.scene);
      if (!picked) return;
      void picked.then(async (features) => {
        if (cancelled) return;
        const parsed = features.map(parsePickedFeature).find(Boolean);
        if (!parsed) return;
        try {
          const detail = await readBusinessFeature(parsed.type, parsed.id);
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
        color: Color.fromCssColorString('#286875'),
        glowColor: Color.fromCssColorString('#2fe6d6'),
        backgroundColor: Color.fromCssColorString('#071923'),
        cells: 4,
        glowWidth: 1,
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
      setLoadMessage('正在读取 GeoServer WMS / WMTS 配置');
      try {
        const config = await getGeoServerConfig();
        if (cancelled) return;
        for (const key of Object.keys(layerLabels) as LayerKey[]) {
          const wmsProvider = new WebMapServiceImageryProvider({
            url: config.wms_url,
            layers: `dayu:${key}`,
            parameters: { transparent: true, format: 'image/png', version: '1.1.1' },
            getFeatureInfoParameters: { info_format: 'application/json', feature_count: 5 },
            srs: 'EPSG:4490',
            enablePickFeatures: true,
            credit: 'GeoServer / PostGIS / CGCS2000',
          });
          const wms = viewer.imageryLayers.addImageryProvider(wmsProvider);
          wms.show = false;
          cleanups.push(wmsProvider.errorEvent.addEventListener((error) => {
            if (error.timesRetried < 2) error.retry = true;
          }));
          let wmts: ImageryLayer | undefined;
          if (CACHED_LAYERS.has(key)) {
            const wmtsProvider = new WebMapTileServiceImageryProvider({
              url: config.wmts_url,
              layer: `dayu:${key}`,
              style: '',
              format: 'image/png',
              tileMatrixSetID: config.preferred_wmts_matrix_set ?? 'EPSG:900913',
              tileMatrixLabels: TILE_MATRIX_LABELS,
              maximumLevel: 22,
              enablePickFeatures: false,
              credit: 'GeoWebCache / PostGIS / CGCS2000',
            });
            wmts = viewer.imageryLayers.addImageryProvider(wmtsProvider);
            cleanups.push(wmtsProvider.errorEvent.addEventListener((error) => {
              if (error.timesRetried < 2) error.retry = true;
            }));
          }
          thematicLayersRef.current.set(key, { wms, wmts });
        }
        updateScaleMode();
        setLoadState('ready');
        setLoadMessage('GeoServer 已发布 6 个图层 · WMTS 4 个缓存图层');
      } catch (error) {
        if (cancelled) return;
        setLoadState('error');
        setLoadMessage(error instanceof Error ? error.message : 'GeoServer 图层加载失败');
      }
    }

    void loadBasemap();
    void loadGeoServerLayers();
    return () => {
      cancelled = true;
      cleanups.forEach((cleanup) => cleanup());
      thematicLayersRef.current.clear();
      basemapLayerRef.current = null;
      viewerRef.current = null;
      onCesiumStatusChange?.(false);
      if (!viewer.isDestroyed()) viewer.destroy();
    };
  }, [reloadToken, variant]);

  function toggleLayer(key: LayerKey, checked: boolean) {
    const next = { ...visibilityRef.current, [key]: checked };
    visibilityRef.current = next;
    setVisibility(next);
    const layers = thematicLayersRef.current.get(key);
    if (!layers) return;
    layers.wms.show = checked && scaleModeRef.current === 'wms';
    if (layers.wmts) layers.wmts.show = checked && scaleModeRef.current === 'wmts';
    viewerRef.current?.scene.requestRender();
  }

  function toggleBasemap(checked: boolean) {
    setBasemapVisible(checked);
    if (basemapLayerRef.current) basemapLayerRef.current.show = checked;
    viewerRef.current?.scene.requestRender();
  }

  return (
    <section className={`map-card map-card--${variant} panel-surface`} aria-label="GIS 河网空间一张图">
      <div className="panel-heading map-card__heading">
        <div>
          <span className="panel-kicker">GEOSERVER · CESIUMJS / 1A</span>
          <h2>GIS 河网空间一张图</h2>
        </div>
        <div className="map-toolbar">
          <Tag className="outline-tag" icon={<EnvironmentOutlined />}>CGCS2000 · EPSG:4490</Tag>
          <Tag className="outline-tag">{scaleMode === 'wmts' ? '小比例尺 · WMTS' : '中比例尺 · WMS'}</Tag>
          <Tooltip title="重新读取空间服务">
            <Button type="text" icon={<ReloadOutlined />} onClick={() => setReloadToken((value) => value + 1)} aria-label="重新加载空间服务" />
          </Tooltip>
          {variant === 'dashboard' && (
            <Tooltip title="打开 GIS 工作台">
              <Button type="text" icon={<ExpandOutlined />} onClick={() => navigate('/gis')} aria-label="打开 GIS 工作台" />
            </Tooltip>
          )}
        </div>
      </div>

      <div className="map-stage">
        <div ref={containerRef} className="cesium-container" />
        <div className={`map-load-state map-load-state--${loadState}`} role="status"><i />{loadMessage}</div>
        {dispatchRunId && <div className="dispatch-map-state"><strong>模拟状态</strong><span>运行 #{dispatchRunId} · {timeSeconds} s</span><small>{selectedAsset ?? '全部设施'} · 计划/模型状态</small></div>}
        <div className={`basemap-status basemap-status--${basemapState}`} data-imagery-source={basemapState === 'imagery' ? 'arcgis-world-imagery' : basemapState}><i />{basemapMessage}</div>
        <div className="layer-control" aria-label="图层控制">
          <strong>GeoServer 图层</strong>
          <Checkbox checked={basemapVisible} onChange={(event) => toggleBasemap(event.target.checked)}>{basemapState === 'fallback' ? '经纬网底图' : '卫星影像'}</Checkbox>
          {(Object.keys(layerLabels) as LayerKey[]).map((key) => (
            <Checkbox key={key} checked={visibility[key]} onChange={(event) => toggleLayer(key, event.target.checked)}>{layerLabels[key]}</Checkbox>
          ))}
        </div>
        {selected && (
          <aside className="feature-inspector" aria-label="空间要素属性">
            <div className="feature-inspector__head"><span>FastAPI 业务属性</span><button type="button" onClick={() => setSelected(null)} aria-label="关闭属性面板">×</button></div>
            <dl>
              <div><dt>ID</dt><dd>{selected.id}</dd></div>
              {Object.entries(selected.properties).map(([key, value]) => <div key={key}><dt>{key}</dt><dd>{displayValue(value)}</dd></div>)}
            </dl>
            {selected.properties.feature_type === 'cross_section' && (
              <Button block type="primary" size="small" onClick={() => navigate(`/hydraulic/results?sectionId=${encodeURIComponent(selected.id)}`)}>查看该断面水动力结果</Button>
            )}
          </aside>
        )}
        <div className="map-coordinate">120.27°E / 30.27°N · CGCS2000</div>
      </div>
    </section>
  );
}
