import { Alert, Button, Collapse, Select, Space, Tag } from 'antd';
import { type Cesium3DTileset } from 'cesium';
import { useCallback, useEffect, useState } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import {
  getGeoServerHealth,
  getGISHealth,
  getGISInteractionFrame,
  getDGISCatalog,
  getDGISThreeDTiles,
  type DGISCatalogResponse,
  type FeatureStateCollection,
  type GISComparisonFrame,
  type GISInteractionFrame,
  type SpatialFeature,
} from '../api/generated/client';
import { CesiumMap } from '../components/gis/CesiumMap';
import { Catalog } from '../components/dgis/Catalog';
import { DataManager } from '../components/dgis/DataManager';
import { LayerTree } from '../components/dgis/LayerTree';
import { RasterLayer } from '../components/dgis/RasterLayer';
import { ThreeDViewer } from '../components/dgis/ThreeDViewer';
import { TimeController } from '../components/dgis/TimeController';
import { VectorTileLayer } from '../components/dgis/VectorTileLayer';
import { SpatialAnalysis } from '../components/gis/SpatialAnalysis';
import { TimelineController } from '../components/gis/TimelineController';
import { useDatasetVersion } from '../context/DatasetVersionContext';

type ServiceState = 'checking' | 'online' | 'offline';

/** Render one consistent health label for the three spatial runtime boundaries. */
function serviceTag(label: string, state: ServiceState) {
  const color = state === 'online' ? 'success' : state === 'offline' ? 'error' : 'processing';
  const text = state === 'online' ? '在线' : state === 'offline' ? '离线' : '检查中';
  return <Tag color={color}>{label}: {text}</Tag>;
}

/** Coordinate versions, model frames, basemap search, and professional Phase 1D workflows. */
export function GisPage() {
  const navigate = useNavigate();
  const [params, setParams] = useSearchParams();
  const { versions, datasetVersionId, loading: versionsLoading, setDatasetVersionId } = useDatasetVersion();
  const dispatchRunId = Number(params.get('dispatchRunId') || 0);
  const taskId = Number(params.get('taskId') || 0);
  const requestedTime = Number(params.get('time') || 0);
  const selectedAsset = params.get('selectedAsset') ?? undefined;
  const [interactionFrame, setInteractionFrame] = useState<GISInteractionFrame | null>(null);
  const [interactionLoading, setInteractionLoading] = useState(false);
  const [interactionError, setInteractionError] = useState('');
  const [analysisFeatures, setAnalysisFeatures] = useState<SpatialFeature[]>([]);
  const [comparisonFrame, setComparisonFrame] = useState<GISComparisonFrame | null>(null);
  const [dgisCatalog, setDgisCatalog] = useState<DGISCatalogResponse | null>(null);
  const [dgisLoading, setDgisLoading] = useState(false);
  const [selectedVectorSource, setSelectedVectorSource] = useState<string | null>(null);
  const [selectedRasterId, setSelectedRasterId] = useState<number | null>(null);
  const [selectedThreeDId, setSelectedThreeDId] = useState<number | null>(null);
  const [threeDAssets, setThreeDAssets] = useState<Awaited<ReturnType<typeof getDGISThreeDTiles>>>([]);
  const [threeDTilesets, setThreeDTilesets] = useState<Cesium3DTileset[]>([]);
  const [replayedStates, setReplayedStates] = useState<FeatureStateCollection | null>(null);
  const [viewportBbox, setViewportBbox] = useState<[number, number, number, number]>([120, 30, 120.6, 30.5]);
  const [services, setServices] = useState<Record<'postgis' | 'geoserver' | 'cesium', ServiceState>>({
    postgis: 'checking', geoserver: 'checking', cesium: 'checking',
  });
  const gateStateCount = interactionFrame?.structure_samples.filter((sample) => sample.structure_type === 'gate').length ?? 0;
  const pumpStateCount = interactionFrame?.structure_samples.filter((sample) => sample.structure_type === 'pump').length ?? 0;
  const handleCesiumStatusChange = useCallback((online: boolean) => {
    setServices((current) => ({ ...current, cesium: online ? 'online' : 'offline' }));
  }, []);
  const handleViewportChange = useCallback((bbox: [number, number, number, number]) => {
    setViewportBbox(bbox);
  }, []);

  useEffect(() => {
    let cancelled = false;
    void Promise.allSettled([getGISHealth(), getGeoServerHealth()]).then(([postgis, geoserver]) => {
      if (cancelled) return;
      setServices((current) => ({
        ...current,
        postgis: postgis.status === 'fulfilled' ? 'online' : 'offline',
        geoserver: geoserver.status === 'fulfilled' ? 'online' : 'offline',
      }));
    });
    return () => { cancelled = true; };
  }, []);

  useEffect(() => {
    if (!datasetVersionId) return;
    let cancelled = false;
    setInteractionLoading(true);
    setInteractionError('');
    void getGISInteractionFrame({
      dataset_version_id: datasetVersionId,
      time_seconds: requestedTime,
      task_id: taskId || undefined,
      dispatch_run_id: dispatchRunId || undefined,
    })
      .then((frame) => {
        if (!cancelled) setInteractionFrame(frame);
      })
      .catch((reason: unknown) => {
        if (cancelled) return;
        setInteractionFrame(null);
        setInteractionError(reason instanceof Error ? reason.message : '动态 GIS 结果读取失败');
      })
      .finally(() => { if (!cancelled) setInteractionLoading(false); });
    return () => { cancelled = true; };
  }, [datasetVersionId, dispatchRunId, requestedTime, taskId]);

  useEffect(() => {
    if (!datasetVersionId) return;
    let cancelled = false;
    setDgisLoading(true);
    void Promise.all([getDGISCatalog(datasetVersionId), getDGISThreeDTiles(datasetVersionId)])
      .then(([catalog, assets]) => {
        if (cancelled) return;
        setDgisCatalog(catalog);
        setThreeDAssets(assets);
      })
      .catch(() => { if (!cancelled) { setDgisCatalog(null); setThreeDAssets([]); } })
      .finally(() => { if (!cancelled) setDgisLoading(false); });
    return () => { cancelled = true; };
  }, [datasetVersionId]);

  const setTimelineTime = useCallback((timeSeconds: number) => {
    const next = new URLSearchParams(params);
    next.set('time', String(timeSeconds));
    setParams(next, { replace: true });
  }, [params, setParams]);

  const changeDatasetVersion = (value: number) => {
    setInteractionFrame(null);
    setAnalysisFeatures([]);
    setComparisonFrame(null);
    setDgisCatalog(null);
    setSelectedVectorSource(null);
    setSelectedRasterId(null);
    setSelectedThreeDId(null);
    setThreeDTilesets([]);
    setReplayedStates(null);
    setDatasetVersionId(value);
  };

  return (
    <div className="gis-page">
      <header className="gis-page__header">
        <div>
          <span className="hero-kicker"><i /> ARCGIS-STYLE HYDRAULIC WORKBENCH</span>
          <h1>GIS 空间分析与水动力融合工作台</h1>
          <p>基础地图、坐标地名定位、工程图层、空间分析、水动力演进、调度状态与专题制图保持同版本联动。</p>
        </div>
        <Space wrap>
          <label className="gis-version-select">数据版本
            <Select
              loading={versionsLoading}
              value={datasetVersionId}
              options={versions.map((version) => ({ value: version.id, label: `${version.version} · ${version.name}` }))}
              onChange={changeDatasetVersion}
              style={{ minWidth: 220 }}
            />
          </label>
          {dispatchRunId > 0 && <Button onClick={() => navigate(`/dispatch/runs/${dispatchRunId}`)}>返回运行 #{dispatchRunId}</Button>}
          <span className="gis-page__badge">DGIS FOUNDATION · DEMO DATA</span>
        </Space>
      </header>
      <div className="spatial-service-strip" aria-label="空间服务状态">
        <strong>空间服务状态</strong>
        <Space wrap>
          {serviceTag('PostGIS', services.postgis)}
          {serviceTag('GeoServer', services.geoserver)}
          {serviceTag('Cesium', services.cesium)}
        </Space>
        <span>静态：WMS / WMTS · 矢量：MVT · 动态：FastAPI / Cesium Primitive</span>
      </div>
      {interactionError && <Alert className="data-alert" type="error" showIcon message="动态结果未加载" description={interactionError} />}
      {interactionFrame && (
        <Alert
          className="data-alert"
          type="warning"
          showIcon
          message="仿真状态叠加：未下发真实设备"
          description={(
            <Space wrap>
              <Tag color="cyan">版本 #{interactionFrame.dataset_version_id}</Tag>
              <Tag>任务 #{interactionFrame.task_id ?? '无'}</Tag>
              <Tag>运行 #{interactionFrame.dispatch_run_id ?? '无'}</Tag>
              <Tag>时刻 {interactionFrame.selected_time_seconds ?? '—'} s</Tag>
              <Tag color="blue">水动力 {interactionFrame.water_samples.length} 点</Tag>
              <Tag color="green">闸门状态 {gateStateCount}</Tag>
              <Tag color="purple">泵站状态 {pumpStateCount}</Tag>
              <span>水位、流速、流向与闸泵状态均为 DEMO 模拟结果，不得作为工程审定成果。</span>
            </Space>
          )}
        />
      )}
      {replayedStates && (
        <Alert
          className="data-alert" type="info" showIcon
          message={`时空状态已恢复 · ${replayedStates.total} 个对象`}
          description="来源为 TimescaleDB feature_state 超表；观测、调度和模拟状态不会改写工程对象静态设计状态。"
        />
      )}
      <Collapse className="dgis-console" defaultActiveKey={['catalog']} items={[
        {
          key: 'catalog', label: 'DGIS 开源生态与时空底座控制台',
          children: <div className="dgis-grid">
            <Catalog catalog={dgisCatalog} loading={dgisLoading} />
            <LayerTree catalog={dgisCatalog} />
            <VectorTileLayer
              sources={dgisCatalog?.vector_tile_sources ?? []}
              selected={selectedVectorSource} onChange={setSelectedVectorSource}
            />
            <RasterLayer
              layers={(dgisCatalog?.simulation_layers ?? []).filter((layer) => layer.service_type === 'TITILER')}
              selectedId={selectedRasterId} onChange={setSelectedRasterId}
            />
            <ThreeDViewer
              assets={threeDAssets} selectedId={selectedThreeDId}
              onChange={setSelectedThreeDId} onTilesetsChange={setThreeDTilesets}
            />
            {datasetVersionId && <TimeController datasetVersionId={datasetVersionId} onReplay={setReplayedStates} />}
            <DataManager />
          </div>,
        },
      ]} />
      <div className="gis-workspace-shell">
        <CesiumMap
          variant="workspace"
          datasetVersionId={datasetVersionId}
          interactionFrame={interactionFrame}
          dynamicLoading={interactionLoading}
          selectedAsset={selectedAsset}
          analysisFeatures={analysisFeatures}
          comparisonFrame={comparisonFrame}
          dgisVectorTileSource={selectedVectorSource}
          dgisRasterTileUrl={selectedRasterId === null ? null : `/api/v1/dgis/raster/${selectedRasterId}/{z}/{x}/{y}.png`}
          dgisThreeDTilesets={threeDTilesets}
          onViewportChange={handleViewportChange}
          onCesiumStatusChange={handleCesiumStatusChange}
        />
        <SpatialAnalysis
          datasetVersionId={datasetVersionId!}
          timeSeconds={interactionFrame?.selected_time_seconds ?? requestedTime}
          taskId={interactionFrame?.task_id ?? undefined}
          viewportBbox={viewportBbox}
          onSpatialResult={setAnalysisFeatures}
          onComparisonResult={setComparisonFrame}
        />
        <TimelineController
          timeline={interactionFrame?.timeline ?? []}
          selectedTime={interactionFrame?.selected_time_seconds}
          loading={interactionLoading}
          onChange={setTimelineTime}
        />
      </div>
    </div>
  );
}
