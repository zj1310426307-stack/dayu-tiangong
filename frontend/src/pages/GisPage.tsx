import { Alert, Select, Space, Tag } from 'antd';
import { useEffect, useState } from 'react';
import { getGeoServerHealth, getGISHealth } from '../api/generated/client';
import { useDatasetVersion } from '../context/DatasetVersionContext';
import { MapView } from '../gis/MapView';

type ServiceState = 'checking' | 'online' | 'offline';

/** Render one consistent runtime label for the unified GIS dependency chain. */
function serviceTag(label: string, state: ServiceState) {
  const color = state === 'online' ? 'success' : state === 'offline' ? 'error' : 'processing';
  const text = state === 'online' ? '在线' : state === 'offline' ? '离线' : '检查中';
  return <Tag color={color}>{label}: {text}</Tag>;
}

/** Present the minimal WebGIS while QGIS remains an offline professional producer. */
export function GisPage() {
  const { versions, datasetVersionId, loading: versionsLoading, setDatasetVersionId } = useDatasetVersion();
  const [services, setServices] = useState<Record<'postgis' | 'geoserver' | 'openlayers', ServiceState>>({
    postgis: 'checking',
    geoserver: 'checking',
    openlayers: 'online',
  });

  useEffect(() => {
    let cancelled = false;
    void Promise.allSettled([getGISHealth(), getGeoServerHealth()]).then(([postgis, geoserver]) => {
      if (cancelled) return;
      setServices({
        postgis: postgis.status === 'fulfilled' ? 'online' : 'offline',
        geoserver: geoserver.status === 'fulfilled' ? 'online' : 'offline',
        openlayers: 'online',
      });
    });
    return () => { cancelled = true; };
  }, []);

  const publicVersions = versions.filter((version) => version.status === 'published');

  useEffect(() => {
    if (publicVersions.length === 0 || publicVersions.some((version) => version.id === datasetVersionId)) return;
    const latest = publicVersions.reduce((current, version) => version.id > current.id ? version : current);
    setDatasetVersionId(latest.id);
  }, [datasetVersionId, publicVersions, setDatasetVersionId]);

  return (
    <div className="gis-page">
      <header className="gis-page__header">
        <div>
          <span className="hero-kicker"><i /> UNIFIED HYDRAULIC WEBGIS</span>
          <h1>统一 GIS 底座</h1>
          <p>PostGIS 是唯一数据中心，GeoServer 是唯一 GIS 服务，OpenLayers 是唯一 WebGIS 渲染端。</p>
        </div>
        <Space wrap>
          <label className="gis-version-select">已发布数据版本
            <Select
              loading={versionsLoading}
              value={datasetVersionId}
              options={publicVersions.map((version) => ({ value: version.id, label: `${version.version} · ${version.name}` }))}
              onChange={setDatasetVersionId}
              style={{ minWidth: 230 }}
            />
          </label>
          <span className="gis-page__badge">GIS-RESET-01 · EPSG:3857</span>
        </Space>
      </header>
      <div className="spatial-service-strip" aria-label="空间服务状态">
        <strong>核心链路</strong>
        <Space wrap>
          {serviceTag('PostGIS', services.postgis)}
          {serviceTag('GeoServer', services.geoserver)}
          {serviceTag('OpenLayers', services.openlayers)}
        </Space>
        <span>QGIS Desktop 仅用于受控数据生产，不在 Web 运行链中</span>
      </div>
      {!datasetVersionId ? (
        <Alert type="warning" showIcon message="暂无可用的已发布数据版本" description="请先完成数据质检、审核、晋级与发布。" />
      ) : (
        <MapView key={datasetVersionId} datasetVersionId={datasetVersionId} />
      )}
      <Alert
        className="gis-scope-note"
        type="info"
        showIcon
        message="专业生产边界"
        description="权威数据保持 EPSG:4490；QGIS 只写 staging_qgis，经质检和人工审核后发布到 publish 视图。Web 端无编辑、无 WFS-T、无第二套 GIS 数据库。"
      />
    </div>
  );
}
