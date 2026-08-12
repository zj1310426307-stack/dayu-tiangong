import { EnvironmentOutlined, ExpandOutlined, ReloadOutlined } from '@ant-design/icons';
import { Button, Checkbox, Tag, Tooltip } from 'antd';
import {
  ArcGisMapServerImageryProvider,
  Cartesian2,
  Cartesian3,
  Color,
  ColorMaterialProperty,
  ConstantProperty,
  GeoJsonDataSource,
  GridImageryProvider,
  type ImageryLayer,
  JulianDate,
  Math as CesiumMath,
  PointGraphics,
  ScreenSpaceEventType,
  Viewer,
  type Entity,
} from 'cesium';
import 'cesium/Build/Cesium/Widgets/widgets.css';
import { useEffect, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  getCrossSections,
  getGates,
  getPumps,
  getRivers,
  type GeoJSONFeatureCollection,
} from '../../api/generated/client';

type LayerKey = 'rivers' | 'gates' | 'pumps' | 'crossSections';
type LoadState = 'loading' | 'ready' | 'error';
type BasemapState = 'loading' | 'imagery' | 'fallback';

interface CesiumMapProps {
  variant?: 'dashboard' | 'workspace';
  dispatchRunId?: number;
  timeSeconds?: number;
  selectedAsset?: string;
}

interface SelectedFeature {
  id: string;
  properties: Record<string, unknown>;
}

const DEMO_BBOX = '119.9,30.0,120.65,30.55';
const WORLD_IMAGERY_URL =
  'https://services.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer';
const layerLabels: Record<LayerKey, string> = {
  rivers: '河道',
  gates: '闸门',
  pumps: '泵站',
  crossSections: '横断面',
};

function displayValue(value: unknown): string {
  if (value === null || value === undefined) return '—';
  if (typeof value === 'object') return JSON.stringify(value);
  return String(value);
}

function selectedEntity(entity: Entity | undefined): SelectedFeature | null {
  if (!entity) return null;
  const properties = entity.properties?.getValue(JulianDate.now()) as Record<string, unknown> | undefined;
  if (!properties) return null;
  return { id: entity.id, properties };
}

// 仅通过 OpenAPI 生成客户端读取空间数据，Cesium 只负责图层与交互渲染。
export function CesiumMap({ variant = 'dashboard', dispatchRunId, timeSeconds = 0, selectedAsset }: CesiumMapProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const viewerRef = useRef<Viewer | null>(null);
  const basemapLayerRef = useRef<ImageryLayer | null>(null);
  const dataSourcesRef = useRef(new Map<LayerKey, GeoJsonDataSource>());
  const navigate = useNavigate();
  const [loadState, setLoadState] = useState<LoadState>('loading');
  const [loadMessage, setLoadMessage] = useState('正在连接 PostGIS 空间服务');
  const [basemapState, setBasemapState] = useState<BasemapState>('loading');
  const [basemapMessage, setBasemapMessage] = useState('正在连接卫星影像');
  const [basemapVisible, setBasemapVisible] = useState(true);
  const [reloadToken, setReloadToken] = useState(0);
  const [selected, setSelected] = useState<SelectedFeature | null>(null);
  const [visibility, setVisibility] = useState<Record<LayerKey, boolean>>({
    rivers: true,
    gates: true,
    pumps: true,
    crossSections: true,
  });

  useEffect(() => {
    if (!containerRef.current) return undefined;
    let cancelled = false;

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
    basemapLayerRef.current = null;
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

    viewer.screenSpaceEventHandler.setInputAction((event: { position: Cartesian2 }) => {
      const picked = viewer.scene.pick(event.position) as { id?: Entity } | undefined;
      setSelected(selectedEntity(picked?.id));
    }, ScreenSpaceEventType.LEFT_CLICK);

    let removeImageryErrorListener: (() => void) | undefined;
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
      setBasemapMessage('正在连接 Esri World Imagery');
      try {
        const provider = await ArcGisMapServerImageryProvider.fromUrl(WORLD_IMAGERY_URL);
        if (cancelled) return;
        removeImageryErrorListener = provider.errorEvent.addEventListener((error) => {
          if (error.timesRetried < 2) {
            error.retry = true;
            return;
          }
          activateFallback('卫星影像请求失败，已切换经纬网');
        });
        activeBasemapLayer = viewer.imageryLayers.addImageryProvider(provider);
        activeBasemapLayer.show = basemapVisible;
        basemapLayerRef.current = activeBasemapLayer;
        setBasemapState('imagery');
        setBasemapMessage('Esri World Imagery 卫星影像');
        viewer.scene.requestRender();
      } catch {
        activateFallback('卫星影像连接失败，已切换经纬网');
      }
    }

    async function loadLayers() {
      try {
        setLoadState('loading');
        setLoadMessage('正在加载 CGCS2000 / EPSG:4490 DEMO DATA');

        const [rivers, gates, pumps, crossSections] = await Promise.all([
          getRivers({ bbox: DEMO_BBOX, limit: 100 }),
          getGates({ bbox: DEMO_BBOX, limit: 100 }),
          getPumps({ bbox: DEMO_BBOX, limit: 100 }),
          getCrossSections({ bbox: DEMO_BBOX, limit: 100 }),
        ]);
        if (cancelled) return;

        const collections: Array<[LayerKey, GeoJSONFeatureCollection]> = [
          ['rivers', rivers],
          ['gates', gates],
          ['pumps', pumps],
          ['crossSections', crossSections],
        ];
        for (const [key, collection] of collections) {
          const source = await GeoJsonDataSource.load(collection as unknown as object, {
            clampToGround: true,
          });
          source.name = layerLabels[key];
          source.show = visibility[key];
          for (const entity of source.entities.values) {
            const properties = entity.properties?.getValue(JulianDate.now()) as Record<string, unknown> | undefined;
            const assetKey = `${properties?.feature_type}:${entity.id}`;
            if (key === 'rivers' && entity.polyline) {
              entity.polyline.material = new ColorMaterialProperty(Color.fromCssColorString('#2fe6d6'));
              entity.polyline.width = new ConstantProperty(5);
            }
            if (key !== 'rivers') {
              entity.billboard = undefined;
              const color = key === 'gates'
                ? Color.fromCssColorString('#ffcf66')
                : key === 'pumps'
                  ? Color.fromCssColorString('#38a8ff')
                  : Color.fromCssColorString('#b49cff');
              entity.point = new PointGraphics({
                color,
                pixelSize: selectedAsset === assetKey ? 18 : key === 'crossSections' ? 7 : 12,
                outlineColor: Color.fromCssColorString('#06101c'),
                outlineWidth: 2,
                disableDepthTestDistance: Number.POSITIVE_INFINITY,
              });
            }
          }
          dataSourcesRef.current.set(key, source);
          await viewer.dataSources.add(source);
        }

        const total = collections.reduce((sum, [, collection]) => sum + collection.meta.total, 0);
        setLoadState('ready');
        setLoadMessage(`PostGIS 已加载 ${total} 个空间要素`);
        viewer.scene.requestRender();
      } catch (error) {
        if (cancelled) return;
        setLoadState('error');
        setLoadMessage(error instanceof Error ? error.message : '空间数据加载失败');
      }
    }

    void loadBasemap();
    void loadLayers();
    return () => {
      cancelled = true;
      removeImageryErrorListener?.();
      dataSourcesRef.current.clear();
      basemapLayerRef.current = null;
      viewerRef.current = null;
      if (!viewer.isDestroyed()) viewer.destroy();
    };
  }, [reloadToken, variant]);

  function toggleLayer(key: LayerKey, checked: boolean) {
    setVisibility((current) => ({ ...current, [key]: checked }));
    const source = dataSourcesRef.current.get(key);
    if (source) source.show = checked;
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
          <span className="panel-kicker">POSTGIS · CESIUMJS / 01</span>
          <h2>GIS 河网空间一张图</h2>
        </div>
        <div className="map-toolbar">
          <Tag className="outline-tag" icon={<EnvironmentOutlined />}>CGCS2000 · EPSG:4490</Tag>
          <Tooltip title="重新读取空间数据">
            <Button type="text" icon={<ReloadOutlined />} onClick={() => setReloadToken((value) => value + 1)} aria-label="重新加载空间数据" />
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
        <div className={`map-load-state map-load-state--${loadState}`} role="status">
          <i />{loadMessage}
        </div>
        {dispatchRunId && <div className="dispatch-map-state"><strong>模拟状态</strong><span>运行 #{dispatchRunId} · {timeSeconds} s</span><small>{selectedAsset ?? '全部设施'} · 计划/模型状态</small></div>}
        <div
          className={`basemap-status basemap-status--${basemapState}`}
          data-imagery-source={basemapState === 'imagery' ? 'arcgis-world-imagery' : basemapState}
        >
          <i />{basemapMessage}
        </div>
        <div className="layer-control" aria-label="图层控制">
          <strong>图层控制</strong>
          <Checkbox checked={basemapVisible} onChange={(event) => toggleBasemap(event.target.checked)}>
            {basemapState === 'fallback' ? '经纬网底图' : '卫星影像'}
          </Checkbox>
          {(Object.keys(layerLabels) as LayerKey[]).map((key) => (
            <Checkbox key={key} checked={visibility[key]} onChange={(event) => toggleLayer(key, event.target.checked)}>
              {layerLabels[key]}
            </Checkbox>
          ))}
        </div>
        {selected && (
          <aside className="feature-inspector" aria-label="空间要素属性">
            <div className="feature-inspector__head">
              <span>要素属性</span>
              <button type="button" onClick={() => setSelected(null)} aria-label="关闭属性面板">×</button>
            </div>
            <dl>
              <div><dt>ID</dt><dd>{selected.id}</dd></div>
              {Object.entries(selected.properties).map(([key, value]) => (
                <div key={key}><dt>{key}</dt><dd>{displayValue(value)}</dd></div>
              ))}
            </dl>
            {selected.properties.feature_type === 'cross_section' && (
              <Button
                block
                type="primary"
                size="small"
                onClick={() => navigate(`/hydraulic/results?sectionId=${encodeURIComponent(selected.id)}`)}
              >
                查看该断面水动力结果
              </Button>
            )}
          </aside>
        )}
        <div className="map-coordinate">120.27°E / 30.27°N · CGCS2000</div>
      </div>
    </section>
  );
}
