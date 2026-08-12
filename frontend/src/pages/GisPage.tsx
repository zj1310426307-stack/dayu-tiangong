import { Alert, Button, Space, Tag } from 'antd';
import { useNavigate, useSearchParams } from 'react-router-dom';
import { CesiumMap } from '../components/gis/CesiumMap';

export function GisPage() {
  const navigate = useNavigate();
  const [params] = useSearchParams();
  const dispatchRunId = Number(params.get('dispatchRunId') || 0);
  const time = Number(params.get('time') || 0);
  const selectedAsset = params.get('selectedAsset') ?? undefined;
  return (
    <div className="gis-page">
      <header className="gis-page__header">
        <div>
          <span className="hero-kicker"><i /> SPATIAL FOUNDATION</span>
          <h1>GIS 一张图空间底座</h1>
          <p>真实 PostGIS 空间对象、GeoJSON 服务、Cesium 图层与调度仿真联动。</p>
        </div>
        <Space>
          {dispatchRunId > 0 && <Button onClick={() => navigate(`/dispatch/runs/${dispatchRunId}`)}>返回运行 #{dispatchRunId}</Button>}
          <span className="gis-page__badge">PHASE 4 · DEMO DATA</span>
        </Space>
      </header>
      {dispatchRunId > 0 && (
        <Alert
          className="data-alert"
          type="warning"
          showIcon
          message="仿真状态叠加：未下发真实设备"
          description={<Space wrap><Tag color="cyan">运行 #{dispatchRunId}</Tag><Tag>时刻 {time} s</Tag><Tag>{selectedAsset ?? '未指定设施'}</Tag><span>静态可用性、计划命令与模型状态分别展示；DEMO DATA 不得作为工程审定成果。</span></Space>}
        />
      )}
      <CesiumMap variant="workspace" dispatchRunId={dispatchRunId || undefined} timeSeconds={time} selectedAsset={selectedAsset} />
    </div>
  );
}
