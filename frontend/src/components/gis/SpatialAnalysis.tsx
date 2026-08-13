import { AimOutlined, BorderOutlined, DeploymentUnitOutlined, RadarChartOutlined } from '@ant-design/icons';
import { Button, Input, InputNumber, Select, Space, Tag, message } from 'antd';
import { useState } from 'react';
import {
  bufferGISFeatures, getGISComparisonFrame,
  getNearestGISFacilities, selectGISFeatures, traceGISRiver,
  type GISComparisonFrame, type SpatialFeature,
} from '../../api/generated/client';
import { MapExport } from './MapExport';

interface SpatialAnalysisProps {
  datasetVersionId: number;
  timeSeconds: number;
  taskId?: number;
  viewportBbox: [number, number, number, number];
  onSpatialResult: (features: SpatialFeature[]) => void;
  onComparisonResult: (frame: GISComparisonFrame | null) => void;
}

/** Coordinate professional spatial tools while keeping all requests on the generated client. */
export function SpatialAnalysis({
  datasetVersionId, timeSeconds, taskId, viewportBbox = [120, 30, 120.6, 30.5],
  onSpatialResult, onComparisonResult,
}: SpatialAnalysisProps) {
  const [busy, setBusy] = useState('');
  const [riverId, setRiverId] = useState(1);
  const [objectType, setObjectType] = useState<'river' | 'gate' | 'pump' | 'cross_section'>('gate');
  const [objectId, setObjectId] = useState(1);
  const [distance, setDistance] = useState(5000);
  const [longitude, setLongitude] = useState(120.2);
  const [latitude, setLatitude] = useState(30.2);
  const [baselineTaskId, setBaselineTaskId] = useState<number | null>(null);
  const [comparisonTaskId, setComparisonTaskId] = useState<number | null>(null);

  async function run(key: string, action: () => Promise<void>) {
    setBusy(key);
    try { await action(); } catch (reason) {
      message.error(reason instanceof Error ? reason.message : '空间分析失败');
    } finally { setBusy(''); }
  }

  return (
    <aside className="spatial-analysis" aria-label="专业空间分析工具">
      <div className="spatial-analysis__head"><strong>SpatialAnalysis</strong><Tag color="cyan">EPSG:4490 / 米</Tag></div>
      <div className="spatial-analysis__tool">
        <span>当前视域 {viewportBbox.map((value) => value.toFixed(3)).join(', ')}</span>
        <Button loading={busy === 'select'} icon={<BorderOutlined />} onClick={() => void run('select', async () => {
          const result = await selectGISFeatures({ dataset_version_id: datasetVersionId, bbox: viewportBbox, object_types: ['river', 'gate', 'pump', 'cross_section'], limit_per_type: 500 });
          onSpatialResult(result.features); onComparisonResult(null);
        })}>框选当前视域</Button>
      </div>
      <div className="spatial-analysis__tool spatial-analysis__tool--inline">
        <InputNumber min={1} value={riverId} onChange={(value) => setRiverId(value ?? 1)} />
        <Button loading={busy === 'trace'} icon={<DeploymentUnitOutlined />} onClick={() => void run('trace', async () => {
          const result = await traceGISRiver(datasetVersionId, riverId);
          onSpatialResult([result.selected_river, ...result.upstream_rivers, ...result.downstream_rivers, ...result.gates, ...result.pumps, ...result.cross_sections]); onComparisonResult(null);
        })}>上下游追踪</Button>
      </div>
      <div className="spatial-analysis__tool spatial-analysis__tool--grid">
        <Select value={objectType} onChange={setObjectType} options={['river', 'gate', 'pump', 'cross_section'].map((value) => ({ value, label: value }))} />
        <InputNumber min={1} value={objectId} onChange={(value) => setObjectId(value ?? 1)} />
        <Space.Compact><InputNumber min={1} value={distance} onChange={(value) => setDistance(value ?? 5000)} /><Button disabled>m</Button></Space.Compact>
        <Button loading={busy === 'buffer'} icon={<RadarChartOutlined />} onClick={() => void run('buffer', async () => {
          const result = await bufferGISFeatures({ dataset_version_id: datasetVersionId, object_type: objectType, object_id: objectId, distance_m: distance, include_types: ['river', 'gate', 'pump', 'cross_section'] });
          onSpatialResult([result.source, ...result.impacted]); onComparisonResult(null);
        })}>缓冲</Button>
      </div>
      <div className="spatial-analysis__tool spatial-analysis__tool--grid">
        <InputNumber value={longitude} step={0.001} onChange={(value) => setLongitude(value ?? 120.2)} />
        <InputNumber value={latitude} step={0.001} onChange={(value) => setLatitude(value ?? 30.2)} />
        <Button loading={busy === 'nearest'} icon={<AimOutlined />} onClick={() => void run('nearest', async () => {
          const result = await getNearestGISFacilities({ dataset_version_id: datasetVersionId, longitude, latitude, facility_types: ['gate', 'pump', 'hydrology_station'], limit: 8 });
          onSpatialResult(result.facilities); onComparisonResult(null);
        })}>最近设施</Button>
      </div>
      <div className="spatial-analysis__tool">
        <span>方案 A / B 任务</span>
        <Space.Compact block><Input placeholder="A 任务 ID" value={baselineTaskId ?? ''} onChange={(event) => setBaselineTaskId(Number(event.target.value) || null)} /><Input placeholder="B 任务 ID" value={comparisonTaskId ?? ''} onChange={(event) => setComparisonTaskId(Number(event.target.value) || null)} /></Space.Compact>
        <Button disabled={!baselineTaskId || !comparisonTaskId} loading={busy === 'compare'} onClick={() => void run('compare', async () => {
          const frame = await getGISComparisonFrame({ dataset_version_id: datasetVersionId, baseline_task_id: baselineTaskId!, comparison_task_id: comparisonTaskId!, time_seconds: timeSeconds });
          onComparisonResult(frame); onSpatialResult([]);
        })}>渲染差异</Button>
      </div>
      <MapExport datasetVersionId={datasetVersionId} timeSeconds={timeSeconds} taskId={taskId} />
    </aside>
  );
}
