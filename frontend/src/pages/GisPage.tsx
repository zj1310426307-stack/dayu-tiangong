import { Alert, Button, Space, Tag } from 'antd';
import { useCallback, useEffect, useState } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import { getGeoServerHealth, getGISHealth } from '../api/generated/client';
import { CesiumMap } from '../components/gis/CesiumMap';

type ServiceState = 'checking' | 'online' | 'offline';

function serviceTag(label: string, state: ServiceState) {
  const color = state === 'online' ? 'success' : state === 'offline' ? 'error' : 'processing';
  const text = state === 'online' ? '在线' : state === 'offline' ? '离线' : '检查中';
  return <Tag color={color}>{label}: {text}</Tag>;
}

export function GisPage() {
  const navigate = useNavigate();
  const [params] = useSearchParams();
  const dispatchRunId = Number(params.get('dispatchRunId') || 0);
  const time = Number(params.get('time') || 0);
  const selectedAsset = params.get('selectedAsset') ?? undefined;
  const [services, setServices] = useState<Record<'postgis' | 'geoserver' | 'cesium', ServiceState>>({ postgis: 'checking', geoserver: 'checking', cesium: 'checking' });
  const handleCesiumStatusChange = useCallback((online: boolean) => {
    setServices((current) => ({ ...current, cesium: online ? 'online' : 'offline' }));
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
  return (
    <div className="gis-page">
      <header className="gis-page__header">
        <div>
          <span className="hero-kicker"><i /> SPATIAL FOUNDATION</span>
          <h1>GIS 一张图空间底座</h1>
          <p>PostGIS 唯一数据源、GeoServer WMS/WMTS 制图、FastAPI 业务查询与 Cesium 联动。</p>
        </div>
        <Space>
          {dispatchRunId > 0 && <Button onClick={() => navigate(`/dispatch/runs/${dispatchRunId}`)}>返回运行 #{dispatchRunId}</Button>}
          <span className="gis-page__badge">PHASE 1A · DEMO DATA</span>
        </Space>
      </header>
      <div className="spatial-service-strip" aria-label="空间服务状态">
        <strong>空间服务状态</strong>
        <Space wrap>
          {serviceTag('PostGIS', services.postgis)}
          {serviceTag('GeoServer', services.geoserver)}
          {serviceTag('Cesium', services.cesium)}
        </Space>
        <span>静态制图：WMS / WMTS · 精细查询：FastAPI GeoJSON</span>
      </div>
      {dispatchRunId > 0 && (
        <Alert
          className="data-alert"
          type="warning"
          showIcon
          message="仿真状态叠加：未下发真实设备"
          description={<Space wrap><Tag color="cyan">运行 #{dispatchRunId}</Tag><Tag>时刻 {time} s</Tag><Tag>{selectedAsset ?? '未指定设施'}</Tag><span>静态可用性、计划命令与模型状态分别展示；DEMO DATA 不得作为工程审定成果。</span></Space>}
        />
      )}
      <CesiumMap
        variant="workspace"
        dispatchRunId={dispatchRunId || undefined}
        timeSeconds={time}
        selectedAsset={selectedAsset}
        onCesiumStatusChange={handleCesiumStatusChange}
      />
    </div>
  );
}
